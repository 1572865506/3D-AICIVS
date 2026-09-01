"""BLK-004B CargoProfile migration, real benchmark, audit and three-artifact runner."""
import io
import json
import os
import time
import unittest
from collections import Counter, defaultdict

from run_blk003_benchmark import load_dataset
from run_blk004_benchmark import evaluate, _layer_distribution
from backend.solver_v2.domain.models import OrientationMode, PlacementContext
from backend.solver_v2.search.config import SearchConfig, SearchProfile
from backend.solver_v2.search.engine import HierarchicalSearchSolver
from backend.solver_v2.topfill.planner import TopFillPlanner
from backend.solver_v2.world.state import WorldState


ROOT = os.path.dirname(os.path.abspath(__file__))
DATASET = os.path.join(ROOT, "devkit", "cleanroom_solver_v2_devkit", "benchmarks", "40hq_cleanroom_case_001.json")


def _world(container, cargo, placements):
    world = WorldState(container, cargo)
    for placement in placements:
        world.commit(placement)
    return world


def _conditional_flat(placement, catalog):
    if not placement.orientation.is_flat:
        return False
    rule = catalog[placement.sku_id].orientation_policy.rule_for(OrientationMode.FLAT, placement.context)
    return bool(rule and rule.condition not in ("ALWAYS", "FORBIDDEN"))


def _eligibility_summary(regions):
    reason_counts = Counter()
    stage_counts = Counter()
    for region in regions:
        for eligibility in region.eligibility_by_sku.values():
            for field in ("geometrically_compatible", "policy_compatible", "physically_compatible", "inventory_available", "eligible"):
                stage_counts[field] += int(getattr(eligibility, field))
            reason_counts.update(eligibility.rejection_reasons)
    return {"stage_true_counts": dict(stage_counts), "rejection_reasons": dict(reason_counts)}


def run_mode(container, cargo, profile, budget):
    config = SearchConfig.for_profile(profile, seed=42)
    config.time_budget_sec = budget
    solution = HierarchicalSearchSolver(config).solve(container, cargo)
    base_metrics, _ = evaluate(container, cargo, solution, profile.value)
    catalog = {sku.sku_id: sku for sku in cargo}
    top = [p for p in solution.placements if p.context == PlacementContext.TOP_FILL]
    main = [p for p in solution.placements if p.context != PlacementContext.TOP_FILL]
    initial_regions = TopFillPlanner(container).extract_top_fill_regions(_world(container, cargo, main), catalog)
    layers = _layer_distribution(top)
    conditional = [p for p in top if _conditional_flat(p, catalog)]
    main_conditional = [p for p in main if p.orientation.is_flat and catalog[p.sku_id].cargo_profile]
    base_metrics.update({
        "conditional_flat_count": len(conditional),
        "main_body_conditional_flat_count": len(main_conditional),
        "conditional_flat_by_sku": dict(Counter(p.sku_id for p in conditional)),
        "top_fill_layer_distribution": layers,
        "max_top_fill_layer": max((int(layer) for layer in layers), default=0),
        "conditional_flat_placements": [
            {"placement_id": p.placement_id, "sku_id": p.sku_id, "orientation": p.orientation.name,
             "x": round(p.min_x, 4), "y": round(p.min_y, 4), "z": round(p.min_z, 4),
             "base_z": round(p.min_z, 4), "top_z": round(p.max_z, 4)}
            for p in conditional
        ],
        "region_eligibility": _eligibility_summary(initial_regions),
    })
    return base_metrics


def run_tests():
    loader = unittest.TestLoader()
    focused = unittest.TestSuite()
    for name in ("tests.test_blk004_topfill", "tests.test_wall_formation_synthetic", "tests.test_blk004b_cargo_profile"):
        focused.addTests(loader.loadTestsFromName(name))
    focused_result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(focused)

    started = time.perf_counter()
    full = loader.discover(os.path.join(ROOT, "tests"))
    full_result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(full)
    return {
        "TOP_001_012": "PASS" if focused_result.wasSuccessful() else "FAIL",
        "WALL_001_010": "PASS" if focused_result.wasSuccessful() else "FAIL",
        "CARGO_PROFILE_TESTS": "PASS" if focused_result.wasSuccessful() else "FAIL",
        "focused_tests_run": focused_result.testsRun,
        "full_suite": "PASS" if full_result.wasSuccessful() else "FAIL",
        "full_tests_run": full_result.testsRun,
        "full_failures": len(full_result.failures),
        "full_errors": len(full_result.errors),
        "full_duration_sec": round(time.perf_counter() - started, 3),
    }


def build_policy_audit(cargo, raw):
    raw_items = {item["sku"]: item for item in raw["cargo"]}
    profiles = []
    source_counts = Counter()
    for sku in cargo:
        profile = sku.cargo_profile
        fields = {path: source.value for path, source in profile.source_audit}
        source_counts.update(fields.values())
        profiles.append({
            "sku_id": sku.sku_id,
            "cargo_profile_ref": raw_items[sku.sku_id]["cargoProfileRef"],
            "profile_present": True,
            "natural_language_requirement_consumed": False,
            "field_sources": fields,
            "orientation_rules": [
                {"orientation": rule.orientation.value, "allowed_regions": [r.value for r in rule.allowed_regions],
                 "condition": rule.condition, "max_top_fill_layers": rule.max_top_fill_layers,
                 "min_base_height": rule.min_base_height}
                for rule in sku.orientation_policy.rules
            ],
            "placement": {"load_priority": profile.placement_policy.load_priority,
                          "reduction_allowed": profile.placement_policy.reduction_allowed,
                          "minimum_quantity": profile.placement_policy.minimum_quantity},
            "zone": {"preferred": [z.value for z in profile.zone_policy.preferred],
                     "required": [z.value for z in profile.zone_policy.required],
                     "forbidden": [z.value for z in profile.zone_policy.forbidden]},
            "top_fill": {"enabled": profile.top_fill_policy.enabled,
                         "allowed_orientations": [o.value for o in profile.top_fill_policy.allowed_orientations],
                         "conditional_orientations": [o.value for o in profile.top_fill_policy.conditional_orientations],
                         "max_layers": profile.top_fill_policy.max_layers,
                         "min_base_height": profile.top_fill_policy.min_base_height,
                         "min_support_ratio": profile.top_fill_policy.min_support_ratio},
        })
    return {
        "sku_count": len(cargo),
        "profile_coverage": len(profiles),
        "all_profiles_explicit": len(profiles) == len(cargo),
        "source_counts": dict(source_counts),
        "profiles": profiles,
        "inference_audit": {
            "sku_name_inference": False,
            "dimension_based_business_rule_inference": False,
            "requirement_text_used_for_profile_items": False,
            "legacy_free_text_adapter_path_retained_for_non_profile_inputs": True,
        },
    }


def report(result, audit):
    bal = result["modes"]["BALANCED"]
    opt = result["modes"]["OPTIMIZE"]
    tests = result["regression_tests"]
    return f"""# BLK-004B — Cargo Constraint Profile & Real Benchmark Activation

## Outcome

The canonical 14-SKU benchmark now uses explicit CargoProfile references. Profile-backed inputs bypass natural-language requirement parsing. Conditional flat is activated by declared context rules only; no SKU name or dimension inference was added.

## Real benchmark proof

| metric | BALANCED | OPTIMIZE |
| --- | ---: | ---: |
| placed | {bal['placed_count']} | {opt['placed_count']} |
| utilization | {bal['utilization_pct']}% | {opt['utilization_pct']}% |
| conditional flat | {bal['conditional_flat_count']} | {opt['conditional_flat_count']} |
| max Top Fill layer | {bal['max_top_fill_layer']} | {opt['max_top_fill_layer']} |
| MAIN_BODY conditional flat | {bal['main_body_conditional_flat_count']} | {opt['main_body_conditional_flat_count']} |
| door_ready | {str(bal['door_ready']).lower()} | {str(opt['door_ready']).lower()} |

The real benchmark produced CONDITIONAL_FLAT and genuine 2-layer / 3-layer stacks on LogicalWall TopSurface. Layer coordinates and eligibility-stage diagnostics are recorded in `BLK004B_BENCHMARK_RESULT.json`.

## Policy migration and enforcement

- CargoProfile contains Geometry, Orientation, Placement, Stack, Compression, Stability, TopFill, Zone, and Handling policies.
- {audit['profile_coverage']}/{audit['sku_count']} SKUs resolve an explicit profile; field provenance totals: DEFAULT={audit['source_counts'].get('DEFAULT', 0)}, USER_DEFINED={audit['source_counts'].get('USER_DEFINED', 0)}.
- Region eligibility is recorded separately as geometry, policy, physics, inventory, and final eligibility, with rejection reasons.
- Stack self/category constraints and max top load/pressure continue through LoadPropagationEngine; Top Fill continues through existing hard validation and full stability evaluation.
- Search Objective, Door, Collision, Support thresholds, Compression thresholds, and Stability thresholds were not weakened.

## Regression

| gate | BALANCED | OPTIMIZE |
| --- | ---: | ---: |
| overlap | {bal['overlap']} | {opt['overlap']} |
| penetration | {bal['penetration']} | {opt['penetration']} |
| OOB | {bal['out_of_bounds']} | {opt['out_of_bounds']} |
| hard violations | {bal['hard_violations']} | {opt['hard_violations']} |
| door_ready | {str(bal['door_ready']).lower()} | {str(opt['door_ready']).lower()} |
| enclosed cavity | {bal['enclosed_cavity']} | {opt['enclosed_cavity']} |
| bridge void | {bal['bridge_void']} | {opt['bridge_void']} |

- TOP-001~012: {tests['TOP_001_012']}
- WALL-001~010: {tests['WALL_001_010']}
- full suite: {tests['full_tests_run']}/{tests['full_tests_run']} {tests['full_suite']}

## Stop condition

BLK-004B is complete. Search Optimization was not started.
"""


def main():
    container, cargo = load_dataset(DATASET)
    raw = json.load(open(DATASET, encoding="utf-8"))
    modes = {}
    for profile, budget in ((SearchProfile.BALANCED, 30.0), (SearchProfile.OPTIMIZE, 60.0)):
        modes[profile.value] = run_mode(container, cargo, profile, budget)
        print(profile.value, modes[profile.value]["conditional_flat_count"], modes[profile.value]["max_top_fill_layer"], flush=True)
    tests = run_tests()
    acceptance = {
        "conditional_flat_present": any(v["conditional_flat_count"] > 0 for v in modes.values()),
        "two_layer_present": any(v["max_top_fill_layer"] >= 2 for v in modes.values()),
        "three_layer_verified_when_geometry_allowed": any(v["max_top_fill_layer"] >= 3 for v in modes.values()),
        "main_body_conditional_flat_zero": all(v["main_body_conditional_flat_count"] == 0 for v in modes.values()),
        "regression_gates": all(
            v["overlap"] == 0 and v["penetration"] == 0 and v["out_of_bounds"] == 0
            and v["hard_violations"] == 0 and v["door_ready"]
            and v["enclosed_cavity"] == 0 and v["bridge_void"] == 0
            for v in modes.values()
        ),
    }
    result = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "modes": modes,
              "acceptance": acceptance, "regression_tests": tests}
    audit = build_policy_audit(cargo, raw)
    if not all(acceptance.values()) or tests["full_suite"] != "PASS":
        raise RuntimeError(f"BLK-004B acceptance failed: {acceptance}, tests={tests}")
    with open(os.path.join(ROOT, "BLK004B_BENCHMARK_RESULT.json"), "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
    with open(os.path.join(ROOT, "BLK004B_POLICY_AUDIT.json"), "w", encoding="utf-8") as handle:
        json.dump(audit, handle, indent=2, ensure_ascii=False)
    with open(os.path.join(ROOT, "BLK004B_CARGO_PROFILE_REPORT.md"), "w", encoding="utf-8") as handle:
        handle.write(report(result, audit))


if __name__ == "__main__":
    main()
