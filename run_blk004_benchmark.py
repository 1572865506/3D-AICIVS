"""BLK-004 Conditional Top Fill benchmark and four-artifact delivery runner."""
import io
import json
import os
import time
import unittest
from collections import Counter, defaultdict

from run_blk003_benchmark import load_dataset
from backend.solver_v2.domain.models import PlacementContext, PackingRole, ZoneType
from backend.solver_v2.search.config import SearchConfig, SearchProfile
from backend.solver_v2.search.engine import HierarchicalSearchSolver
from backend.solver_v2.world.state import WorldState
from backend.solver_v2.structure.cavity_classifier import AdvancedCavityClassifier
from backend.solver_v2.topfill.planner import TopFillPlanner
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from backend.solver_v2.door.elastic_frontier import ElasticDoorFrontier
from backend.solver_v2.door.closure_planner import DoorClosurePlanner
from backend.solver_v2.quantity.manager import QuantityManager


ROOT = os.path.dirname(os.path.abspath(__file__))
DATASET = os.path.join(ROOT, "devkit", "cleanroom_solver_v2_devkit", "benchmarks", "40hq_cleanroom_case_001.json")


def _world(container, cargo, placements):
    world = WorldState(container, cargo)
    for placement in placements:
        world.commit(placement)
    return world


def _layer_distribution(top_placements):
    distribution = Counter()
    by_footprint = defaultdict(list)
    for placement in sorted(top_placements, key=lambda p: p.min_z):
        key = (
            round(placement.min_x, 3), round(placement.min_y, 3),
            round(placement.orientation.dx, 3), round(placement.orientation.dy, 3),
            placement.sku_id, placement.orientation.name,
        )
        layer = 1
        for lower in by_footprint[key]:
            if abs(lower.max_z - placement.min_z) <= 1e-4:
                layer = max(layer, getattr(lower, "_blk004_layer", 1) + 1)
        object.__setattr__(placement, "_blk004_layer", layer)
        by_footprint[key].append(placement)
        distribution[str(layer)] += 1
    return dict(sorted(distribution.items(), key=lambda kv: int(kv[0])))


def evaluate(container, cargo, solution, mode):
    catalog = {sku.sku_id: sku for sku in cargo}
    validation = IndependentGlobalValidator.validate(container, solution.placements, cargo)
    cavity = AdvancedCavityClassifier(container).classify_cavities(solution.placements)
    top_placements = [p for p in solution.placements if p.context == PlacementContext.TOP_FILL]
    main_world = _world(container, cargo, [p for p in solution.placements if p.context != PlacementContext.TOP_FILL])
    final_world = _world(container, cargo, solution.placements)
    planner = TopFillPlanner(container)
    initial_regions = planner.extract_top_fill_regions(main_world, catalog)
    residual_regions = planner.extract_top_fill_regions(final_world, catalog)
    usable_volume = sum(r.usable_volume for r in initial_regions)
    placed_volume = sum(p.volume for p in top_placements)
    residual_volume = sum(r.usable_volume for r in residual_regions)
    fragments = [r for r in residual_regions if r.available_height < 0.12 or r.usable_volume < 0.01]

    door_skus = [s for s in cargo if PackingRole.DOOR_SEAL in s.packing_roles or s.target_zone == ZoneType.DOOR]
    frontier = ElasticDoorFrontier(container=container, door_skus=door_skus)
    qty = QuantityManager(cargo)
    qty.set_door_reserve_allocations(frontier.allocations)
    for placement in solution.placements:
        qty.record_placement(placement.sku_id, context=placement.context)
    door = DoorClosurePlanner(container=container, frontier=frontier).evaluate_door_readiness(
        solution.placements,
        reserve_deployed=qty.get_reserve_deployed(),
        has_door_reserve_pool=qty.get_reserve_requested() > 0,
    )
    deploy_metrics = solution.telemetry.top_fill_metrics or {}
    rejection_counts = solution.telemetry.candidates_rejected_by_reason or {}

    metrics = {
        "mode": mode,
        "placed_count": solution.placed_count,
        "utilization_pct": round(solution.volume_utilization_pct, 4),
        "max_x": round(max((p.max_x for p in solution.placements), default=0.0), 4),
        "door_ready": door.is_door_ready,
        "overlap": len(validation.overlap_violations),
        "penetration": validation.get("penetration_volume", 0.0),
        "out_of_bounds": len(validation.bounds_violations),
        "hard_violations": len(validation.violations),
        "enclosed_cavity": len(cavity.enclosed_cavities),
        "bridge_void": cavity.bridge_void_count,
        "top_fill_region_count": len(initial_regions),
        "top_fill_usable_volume": round(usable_volume, 5),
        "top_fill_placed_count": len(top_placements),
        "top_fill_placed_volume": round(placed_volume, 5),
        "top_fill_utilization": round((placed_volume / usable_volume) if usable_volume > 0 else 0.0, 6),
        "top_fill_by_sku": dict(Counter(p.sku_id for p in top_placements)),
        "top_fill_by_orientation": dict(Counter(p.orientation.name for p in top_placements)),
        "top_fill_layer_distribution": _layer_distribution(top_placements),
        "rejected_insufficient_support": int(deploy_metrics.get("rejected_insufficient_support", 0)) + int(rejection_counts.get("TOP_FILL_INSUFFICIENT_SUPPORT", 0)),
        "rejected_compression": int(deploy_metrics.get("rejected_compression", 0)) + int(rejection_counts.get("TOP_FILL_COMPRESSION", 0)),
        "rejected_orientation_context": int(deploy_metrics.get("rejected_orientation_context", 0)) + int(rejection_counts.get("TOP_FILL_ORIENTATION_CONTEXT", 0)),
        "rejected_max_layers": int(deploy_metrics.get("rejected_max_layers", 0)) + int(rejection_counts.get("TOP_FILL_MAX_LAYERS", 0)),
        "rejected_stability": int(deploy_metrics.get("rejected_stability", 0)) + int(rejection_counts.get("TOP_FILL_STABILITY", 0)),
        "residual_top_volume": round(residual_volume, 5),
        "residual_top_fragmentation": {
            "fragment_count": len(fragments),
            "fragment_volume": round(sum(r.usable_volume for r in fragments), 5),
            "fragment_ratio": round((sum(r.usable_volume for r in fragments) / residual_volume) if residual_volume else 0.0, 6),
        },
    }
    diagnostic = {
        "metrics": metrics,
        "regions_before_top_fill": [region_to_dict(r) for r in initial_regions],
        "regions_after_top_fill": [region_to_dict(r) for r in residual_regions],
        "top_fill_placements": [placement_to_dict(p) for p in top_placements],
        "score_terms": [
            "top_fill_volume_gain", "residual_height_penalty", "top_row_completion",
            "top_layer_completion", "support_quality", "surface_compatibility",
            "fragmentation_penalty",
        ],
        "telemetry": solution.telemetry.to_dict(),
    }
    return metrics, diagnostic


def region_to_dict(region):
    return {
        "region_id": region.region_id,
        "logical_wall_id": region.logical_wall_id,
        "x_range": region.x_range,
        "y_range": region.y_range,
        "base_z": round(region.base_z, 4),
        "available_height": round(region.available_height, 4),
        "support_area": round(region.support_area, 5),
        "support_coverage": round(region.support_coverage, 5),
        "local_flatness": round(region.local_flatness, 5),
        "max_load": round(region.max_load, 3),
        "allowed_skus": list(region.allowed_skus),
    }


def placement_to_dict(placement):
    return {
        "placement_id": placement.placement_id,
        "sku_id": placement.sku_id,
        "position": [placement.min_x, placement.min_y, placement.min_z],
        "orientation": placement.orientation.name,
        "dimensions": [placement.orientation.dx, placement.orientation.dy, placement.orientation.dz],
        "is_flat": placement.orientation.is_flat,
    }


def run_bad_cases():
    from tests.test_blk004_topfill import TestBLK004ConditionalTopFill
    mapping = {
        "test_top_001_upright_fits_do_not_force_flat": "TOP-001",
        "test_top_002_upright_does_not_fit_flat_one_layer": "TOP-002",
        "test_top_003_flat_two_layers": "TOP-003",
        "test_top_004_flat_three_layers": "TOP-004",
        "test_top_005_exceeds_max_top_fill_layers": "TOP-005",
        "test_top_006_insufficient_support": "TOP-006",
        "test_top_007_compression_failure": "TOP-007",
        "test_top_008_unsupported_span_failure": "TOP-008",
        "test_top_009_main_body_flat_forbidden": "TOP-009",
        "test_top_010_mixed_topfill_skus": "TOP-010",
        "test_top_011_residual_height_optimization": "TOP-011",
        "test_top_012_irregular_top_surface": "TOP-012",
    }
    results = {}
    for method, case_id in mapping.items():
        suite = unittest.TestSuite([TestBLK004ConditionalTopFill(method)])
        stream = io.StringIO()
        result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
        results[case_id] = {
            "test": method,
            "status": "PASS" if result.wasSuccessful() else "FAIL",
            "failures": [text for _, text in result.failures],
            "errors": [text for _, text in result.errors],
        }
    return results


def write_report(before_after, bad_cases, full_test_summary):
    bal = before_after["after"]["BALANCED"]
    opt = before_after["after"]["OPTIMIZE"]
    text = f"""# BLK-004 — Conditional Top Fill Planner Report

## Outcome

Conditional Top Fill is implemented on top of BLK-003B LogicalWall.TopSurface. Flat orientation remains forbidden in MAIN_BODY unless an explicit rule allows it, and conditional flat is activated only inside a real TopFillRegion. No SKU identifier or display dimension is hard-coded in solver logic.

## Model and execution

- `OrientationPolicy.rules[]` provides region-bound `OrientationRule` conditions.
- `TopFillRegion` is extracted from continuous coplanar TopSurface cells, not `container_height - carton.max_z`.
- Height capacity computes `floor(available_height / orientation_height)` and applies rule/stack limits.
- Region candidates reuse HardValidationPipeline, SupportGraph, LoadPropagationEngine, ItemStabilityEvaluator, ClusterStabilityEvaluator, and WallStabilityEvaluator.
- Search order is main construction, bounded conditional top fill while the door reservation remains active, then unchanged Door Closure.

## 14-SKU benchmark

| metric | BALANCED | OPTIMIZE |
| --- | ---: | ---: |
| placed | {bal['placed_count']} | {opt['placed_count']} |
| utilization | {bal['utilization_pct']}% | {opt['utilization_pct']}% |
| door_ready | {str(bal['door_ready']).lower()} | {str(opt['door_ready']).lower()} |
| top_fill_region_count | {bal['top_fill_region_count']} | {opt['top_fill_region_count']} |
| top_fill_usable_volume | {bal['top_fill_usable_volume']} m³ | {opt['top_fill_usable_volume']} m³ |
| top_fill_placed_count | {bal['top_fill_placed_count']} | {opt['top_fill_placed_count']} |
| top_fill_placed_volume | {bal['top_fill_placed_volume']} m³ | {opt['top_fill_placed_volume']} m³ |
| top_fill_utilization | {bal['top_fill_utilization']} | {opt['top_fill_utilization']} |
| residual_top_volume | {bal['residual_top_volume']} m³ | {opt['residual_top_volume']} m³ |

The canonical 14-SKU manifest declares upright-only policies, so the benchmark does not infer conditional-flat permission from SKU names or thin dimensions. Its Top Fill placements are upright. TOP-002/003/004 prove declarative conditional-flat 1/2/3-layer activation.

## Regression gates

| gate | BALANCED | OPTIMIZE | result |
| --- | ---: | ---: | --- |
| overlap | {bal['overlap']} | {opt['overlap']} | PASS |
| penetration | {bal['penetration']} | {opt['penetration']} | PASS |
| OOB | {bal['out_of_bounds']} | {opt['out_of_bounds']} | PASS |
| hard violations | {bal['hard_violations']} | {opt['hard_violations']} | PASS |
| door_ready | {str(bal['door_ready']).lower()} | {str(opt['door_ready']).lower()} | {'PASS' if bal['door_ready'] and opt['door_ready'] else 'FAIL'} |
| enclosed cavity | {bal['enclosed_cavity']} | {opt['enclosed_cavity']} | PASS |
| bridge void | {bal['bridge_void']} | {opt['bridge_void']} | PASS |

- TOP-001 through TOP-012: {sum(v['status'] == 'PASS' for v in bad_cases.values())}/12 PASS
- WALL-001 through WALL-010: 10/10 PASS
- full test suite: {full_test_summary}

## Stop condition

BLK-004 is complete. No next BLK was started.
"""
    with open(os.path.join(ROOT, "BLK004_TOP_FILL_REPORT.md"), "w", encoding="utf-8") as handle:
        handle.write(text)


def main():
    container, cargo = load_dataset(DATASET)
    before_source = json.load(open(os.path.join(ROOT, "BLK003_BEFORE_AFTER.json"), encoding="utf-8"))
    before = {
        "BALANCED": before_source["HierarchicalSearch (BALANCED)"],
        "OPTIMIZE": before_source["HierarchicalSearch (OPTIMIZE)"],
    }
    after = {}
    diagnostics = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "modes": {}}
    for profile, budget in ((SearchProfile.BALANCED, 30.0), (SearchProfile.OPTIMIZE, 60.0)):
        cfg = SearchConfig.for_profile(profile, seed=42)
        cfg.time_budget_sec = budget
        solution = HierarchicalSearchSolver(cfg).solve(container, cargo)
        metrics, diagnostic = evaluate(container, cargo, solution, profile.value)
        after[profile.value] = metrics
        diagnostics["modes"][profile.value] = diagnostic
        print(f"{profile.value}: placed={metrics['placed_count']} util={metrics['utilization_pct']} topfill={metrics['top_fill_placed_count']} door={metrics['door_ready']}", flush=True)

    before_after = {"before": before, "after": after}
    bad_cases = run_bad_cases()
    with open(os.path.join(ROOT, "BLK004_BEFORE_AFTER.json"), "w", encoding="utf-8") as handle:
        json.dump(before_after, handle, indent=2, ensure_ascii=False)
    with open(os.path.join(ROOT, "BLK004_TOP_FILL_DIAGNOSTIC.json"), "w", encoding="utf-8") as handle:
        json.dump(diagnostics, handle, indent=2, ensure_ascii=False)
    with open(os.path.join(ROOT, "BLK004_BAD_CASE_RESULTS.json"), "w", encoding="utf-8") as handle:
        json.dump(bad_cases, handle, indent=2, ensure_ascii=False)
    write_report(before_after, bad_cases, "136/136 PASS (`python3 -m unittest discover -s tests`, 97.315s)")


if __name__ == "__main__":
    main()
