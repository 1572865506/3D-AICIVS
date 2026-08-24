"""
BLK-003 Benchmark and Evaluation Runner:
Wall Formation, Layer/Row Coherence, Cavity Metrics, and Regression Gate Verification.
Runs:
1. BaselineGreedy
2. FAST (5s)
3. BALANCED (30s)
4. OPTIMIZE (60s)
Outputs:
- BLK003_BEFORE_AFTER.json
- BLK003_WALL_METRICS.json
- BLK003_BAD_CASE_RESULTS.json
- BLK003_WALL_DEBUG_SNAPSHOT.json
"""
import os
import sys
import json
import time
from typing import Dict, Any, List

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.domain.models import (
    ContainerSpec,
    CargoSKU,
    BoxDim,
    OrientationPolicy,
    StackingPolicy,
    QuantityPlan,
    PackingRole,
    ZoneType,
    PlacementContext,
)
from backend.solver_v2.solver.baseline_solver import BaselineGreedySolver
from backend.solver_v2.search.engine import HierarchicalSearchSolver
from backend.solver_v2.search.config import SearchConfig, SearchProfile
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from backend.solver_v2.door.elastic_frontier import ElasticDoorFrontier
from backend.solver_v2.door.closure_planner import DoorClosurePlanner
from backend.solver_v2.quantity.manager import QuantityManager
from backend.solver_v2.structure.wall_model import WallStructureAnalyzer, WallState
from backend.solver_v2.structure.cavity_classifier import AdvancedCavityClassifier, ComprehensiveCavityReport
from backend.solver_v2.world.state import WorldState


def load_dataset(json_path: str):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    container = InputAdapter.parse_container(data["containerSeed"])
    cargo_list = InputAdapter.parse_cargo_list(data["cargo"], data.get("cargoProfiles"))
    return container, cargo_list


def evaluate_solution_wall_metrics(container: ContainerSpec, cargo_list: List[CargoSKU], solution, mode_name: str) -> Dict[str, Any]:
    val_res = IndependentGlobalValidator.validate(container, solution.placements, cargo_list)

    door_seal_skus = [s for s in cargo_list if PackingRole.DOOR_SEAL in s.packing_roles or s.target_zone == ZoneType.DOOR]
    frontier = ElasticDoorFrontier(container=container, door_skus=door_seal_skus)
    allocations = frontier.allocations
    frontier_metrics = frontier.get_metrics()

    qty_mgr = QuantityManager(cargo_list=cargo_list)
    qty_mgr.set_door_reserve_allocations(allocations)
    for p in solution.placements:
        qty_mgr.record_placement(p.sku_id, context=p.context)

    # Cargo X statistics
    placed_xs = [p.max_x for p in solution.placements] if solution.placements else [0.0]
    main_wall_end_x = max(placed_xs)

    # SKU breakdown
    sku_counts = {}
    for p in solution.placements:
        sku_counts[p.sku_id] = sku_counts.get(p.sku_id, 0) + 1

    door_placed = sum(sku_counts.get(s.sku_id, 0) for s in door_seal_skus)
    non_door_placed = sum(cnt for sid, cnt in sku_counts.items() if sid not in [s.sku_id for s in door_seal_skus])

    door_planner = DoorClosurePlanner(container=container, frontier=frontier)
    readiness = door_planner.evaluate_door_readiness(
        solution.placements,
        reserve_deployed=qty_mgr.get_reserve_deployed(),
        has_door_reserve_pool=(qty_mgr.get_reserve_requested() > 0),
    )

    # Wall Model & Cavity Analysis (BLK-003)
    wall_analyzer = WallStructureAnalyzer(container=container)
    wall_slices = wall_analyzer.extract_wall_slices(solution.placements)
    walls = wall_analyzer.extract_logical_walls(wall_slices)
    cavity_classifier = AdvancedCavityClassifier(container=container)
    cavity_report = cavity_classifier.classify_cavities(solution.placements)

    wall_flatnesses = [w.wall_flatness for w in walls] if walls else [1.0]
    wall_occupancies = [w.wall_occupancy for w in walls] if walls else [0.0]
    wall_height_deltas = [w.max_height_delta for w in walls] if walls else [0.0]

    all_rows = [r for w in walls for r in w.rows]
    all_layers = [l for w in walls for l in w.layers]

    row_comp_rate = (sum(1 for r in all_rows if r.is_complete) / len(all_rows) * 100.0) if all_rows else 100.0
    layer_comp_rate = (sum(1 for l in all_layers if l.is_complete) / len(all_layers) * 100.0) if all_layers else 100.0

    wall_metrics = {
        "wall_count": len(walls),
        "logical_wall_count": len(walls),
        "wall_slice_count": len(wall_slices),
        "avg_items_per_logical_wall": round(
            sum(w.item_count for w in walls) / len(walls), 4
        ) if walls else 0.0,
        "wall_occupancy_avg": round(sum(wall_occupancies) / len(wall_occupancies), 4),
        "wall_occupancy_min": round(min(wall_occupancies), 4),
        "wall_flatness_avg": round(wall_analyzer.weighted_wall_flatness(walls), 4),
        "weighted_wall_flatness": round(wall_analyzer.weighted_wall_flatness(walls), 4),
        "wall_flatness_min": round(min(wall_flatnesses), 4),
        "max_wall_height_delta": round(max(wall_height_deltas), 4),
        "enclosed_cavity_count": len(cavity_report.enclosed_cavities),
        "enclosed_cavity_volume_m3": round(cavity_report.enclosed_volume_m3, 5),
        "reachable_cavity_volume_m3": round(cavity_report.reachable_volume_m3, 5),
        "open_notch_volume_m3": round(cavity_report.open_notch_volume_m3, 5),
        "future_free_space_volume_m3": round(cavity_report.future_free_space_volume_m3, 5),
        "dead_space_volume_m3": round(cavity_report.dead_space_volume_m3, 5),
        "sliver_volume_m3": round(cavity_report.sliver_volume_m3, 5),
        "row_completion_rate_pct": round(row_comp_rate, 2),
        "layer_completion_rate_pct": round(layer_comp_rate, 2),
        "bridge_void_count": cavity_report.bridge_void_count,
        "max_bridge_span_m": cavity_report.max_bridge_span_m,
        "top_surface_available": sum(
            bool(w.top_surface and w.top_surface.available) for w in walls
        ),
        "walls": [w.to_dict() for w in walls],
    }

    door_metrics = {
        "mode": mode_name,
        "sku_counts": sku_counts,
        "sku_diversity_count": len(sku_counts),
        "total_door_placed": door_placed,
        "non_door_placed": non_door_placed,
        "door_reserve_requested": qty_mgr.get_reserve_requested(),
        "door_reserve_deployed": qty_mgr.get_reserve_deployed(),
        "door_reserve_remaining": qty_mgr.get_reserve_remaining(),
        "main_wall_end_x": round(main_wall_end_x, 3),
        "transition_reached": readiness.reached_transition_zone,
        "door_zone_reached": readiness.reached_door_closure_zone,
        "door_closure_coverage": round(readiness.door_closure_coverage, 4),
        "largest_door_gap": round(readiness.largest_door_gap, 3),
        "door_zone_occupancy": round(readiness.door_zone_occupancy, 4),
        "door_wall_flatness": round(readiness.door_wall_flatness, 4),
        "is_door_ready": readiness.is_door_ready,
        "door_readiness_score": round(readiness.door_readiness_score, 2),
        "door_clearance_margin_m": round(readiness.door_clearance_margin_m, 3),
        "rejection_reasons": readiness.rejection_reasons,
    }

    return {
        "placed_count": solution.placed_count,
        "unplaced_count": sum(s.quantity.required for s in cargo_list) - solution.placed_count,
        "volume_utilization_pct": round(solution.volume_utilization_pct, 2),
        "total_weight_kg": round(solution.total_weight_kg, 2),
        "is_valid": val_res.is_valid,
        "overlap_pair_count": len(val_res.overlap_violations),
        "penetration_volume_m3": val_res.get("penetration_volume", 0.0),
        "out_of_bounds_count": len(val_res.bounds_violations),
        "hard_constraint_violations": len(val_res.violations),
        "door_metrics": door_metrics,
        "wall_metrics": wall_metrics,
        "telemetry": solution.telemetry.to_dict() if hasattr(solution.telemetry, "to_dict") else {},
    }


def run_all_blk003_benchmarks():
    dataset_path = os.path.join(PROJECT_ROOT, "devkit", "cleanroom_solver_v2_devkit", "benchmarks", "40hq_cleanroom_case_001.json")
    container, cargo_list = load_dataset(dataset_path)

    results = {}
    wall_snapshots = {}

    # 1. BaselineGreedy
    print("=== Running Mode 1: BaselineGreedy ===", flush=True)
    solver1 = BaselineGreedySolver(seed=42, max_candidates_per_step=150)
    sol1 = solver1.solve(container, cargo_list)
    results["BaselineGreedySolver"] = evaluate_solution_wall_metrics(container, cargo_list, sol1, "BaselineGreedy")
    wall_snapshots["BaselineGreedySolver"] = results["BaselineGreedySolver"]["wall_metrics"]["walls"]
    print(f"  Placed: {sol1.placed_count}, Util: {sol1.volume_utilization_pct:.2f}%, Valid: {results['BaselineGreedySolver']['is_valid']}, FlatnessAvg: {results['BaselineGreedySolver']['wall_metrics']['wall_flatness_avg']}", flush=True)

    # 2. FAST (5s)
    print("=== Running Mode 2: FAST (5s) ===", flush=True)
    cfg_fast = SearchConfig.for_profile(SearchProfile.FAST, seed=42)
    cfg_fast.time_budget_sec = 5.0
    solver2 = HierarchicalSearchSolver(config=cfg_fast)
    sol2 = solver2.solve(container, cargo_list)
    results["HierarchicalSearch (FAST)"] = evaluate_solution_wall_metrics(container, cargo_list, sol2, "FAST")
    wall_snapshots["HierarchicalSearch (FAST)"] = results["HierarchicalSearch (FAST)"]["wall_metrics"]["walls"]
    print(f"  Placed: {sol2.placed_count}, Util: {sol2.volume_utilization_pct:.2f}%, Valid: {results['HierarchicalSearch (FAST)']['is_valid']}, FlatnessAvg: {results['HierarchicalSearch (FAST)']['wall_metrics']['wall_flatness_avg']}", flush=True)

    # 3. BALANCED (30s)
    print("=== Running Mode 3: BALANCED (30s) ===", flush=True)
    cfg_bal = SearchConfig.for_profile(SearchProfile.BALANCED, seed=42)
    cfg_bal.time_budget_sec = 30.0
    solver3 = HierarchicalSearchSolver(config=cfg_bal)
    sol3 = solver3.solve(container, cargo_list)
    results["HierarchicalSearch (BALANCED)"] = evaluate_solution_wall_metrics(container, cargo_list, sol3, "BALANCED")
    wall_snapshots["HierarchicalSearch (BALANCED)"] = results["HierarchicalSearch (BALANCED)"]["wall_metrics"]["walls"]
    print(f"  Placed: {sol3.placed_count}, Util: {sol3.volume_utilization_pct:.2f}%, Valid: {results['HierarchicalSearch (BALANCED)']['is_valid']}, DoorReady: {results['HierarchicalSearch (BALANCED)']['door_metrics']['is_door_ready']}, FlatnessAvg: {results['HierarchicalSearch (BALANCED)']['wall_metrics']['wall_flatness_avg']}", flush=True)

    # 4. OPTIMIZE (60s)
    print("=== Running Mode 4: OPTIMIZE (60s) ===", flush=True)
    cfg_opt = SearchConfig.for_profile(SearchProfile.OPTIMIZE, seed=42)
    cfg_opt.time_budget_sec = 60.0
    solver4 = HierarchicalSearchSolver(config=cfg_opt)
    sol4 = solver4.solve(container, cargo_list)
    results["HierarchicalSearch (OPTIMIZE)"] = evaluate_solution_wall_metrics(container, cargo_list, sol4, "OPTIMIZE")
    wall_snapshots["HierarchicalSearch (OPTIMIZE)"] = results["HierarchicalSearch (OPTIMIZE)"]["wall_metrics"]["walls"]
    print(f"  Placed: {sol4.placed_count}, Util: {sol4.volume_utilization_pct:.2f}%, Valid: {results['HierarchicalSearch (OPTIMIZE)']['is_valid']}, DoorReady: {results['HierarchicalSearch (OPTIMIZE)']['door_metrics']['is_door_ready']}, FlatnessAvg: {results['HierarchicalSearch (OPTIMIZE)']['wall_metrics']['wall_flatness_avg']}", flush=True)

    # Save outputs
    out_before_after = os.path.join(PROJECT_ROOT, "BLK003_BEFORE_AFTER.json")
    with open(out_before_after, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Saved results to {out_before_after}")

    out_metrics = os.path.join(PROJECT_ROOT, "BLK003_WALL_METRICS.json")
    wall_metrics_summary = {
        m_name: {
            "placed_count": m_res["placed_count"],
            "utilization_pct": m_res["volume_utilization_pct"],
            "is_valid": m_res["is_valid"],
            "wall_metrics": m_res["wall_metrics"],
            "door_metrics": m_res["door_metrics"],
        }
        for m_name, m_res in results.items()
    }
    with open(out_metrics, "w", encoding="utf-8") as f:
        json.dump(wall_metrics_summary, f, indent=2)
    print(f"Saved wall metrics to {out_metrics}")

    # Visual debug snapshot for Three.js
    out_debug = os.path.join(PROJECT_ROOT, "BLK003_WALL_DEBUG_SNAPSHOT.json")
    debug_snapshot_data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "container": {"Lx": container.Lx, "Ly": container.Ly, "Lz": container.Lz},
        "mode_wall_snapshots": wall_snapshots,
        "mode_placements": {
            "BaselineGreedySolver": [p.to_dict() if hasattr(p, "to_dict") else {"sku": p.sku_id, "pos": [p.position.x, p.position.y, p.position.z], "dim": [p.orientation.dx, p.orientation.dy, p.orientation.dz]} for p in sol1.placements],
            "HierarchicalSearch (BALANCED)": [p.to_dict() if hasattr(p, "to_dict") else {"sku": p.sku_id, "pos": [p.position.x, p.position.y, p.position.z], "dim": [p.orientation.dx, p.orientation.dy, p.orientation.dz]} for p in sol3.placements],
        }
    }
    with open(out_debug, "w", encoding="utf-8") as f:
        json.dump(debug_snapshot_data, f, indent=2)
    print(f"Saved visual debug snapshot to {out_debug}")


if __name__ == "__main__":
    run_all_blk003_benchmarks()
