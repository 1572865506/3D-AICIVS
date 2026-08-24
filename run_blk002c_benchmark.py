"""
Benchmark and Diagnostic Runner for BLK-002C:
Door Reserve Deployment & Boundary Unification.
Runs 4 Solver Modes on 40hq_cleanroom_case_001.json (14 SKUs / 1845 Cartons):
1. BaselineGreedySolver
2. HierarchicalSearchSolver (FAST - 5s)
3. HierarchicalSearchSolver (BALANCED - 30s)
4. HierarchicalSearchSolver (OPTIMIZE - 60s)
Validates with IndependentGlobalValidator and DoorClosurePlanner.
Generates:
- BLK002C_BEFORE_AFTER.json
- BLK002C_DOOR_TRACE.json
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


def load_dataset(json_path: str):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    container = InputAdapter.parse_container(data["containerSeed"])
    cargo_list = InputAdapter.parse_cargo_list(data["cargo"])
    return container, cargo_list


def evaluate_solution_metrics(container: ContainerSpec, cargo_list: List[CargoSKU], solution, mode_name: str) -> Dict[str, Any]:
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

    # Required vs Elastic fill rates
    req_skus = [s for s in cargo_list if not s.quantity.is_elastic]
    req_total = sum(s.quantity.required for s in req_skus)
    req_placed = sum(sku_counts.get(s.sku_id, 0) for s in req_skus)
    req_fill_rate = (req_placed / req_total * 100.0) if req_total > 0 else 100.0

    elastic_skus = [s for s in cargo_list if s.quantity.is_elastic]
    elastic_total = sum(s.quantity.required for s in elastic_skus)
    elastic_placed = sum(sku_counts.get(s.sku_id, 0) for s in elastic_skus)
    elastic_fill_rate = (elastic_placed / elastic_total * 100.0) if elastic_total > 0 else 100.0

    door_planner = DoorClosurePlanner(container=container, frontier=frontier)
    readiness = door_planner.evaluate_door_readiness(
        solution.placements,
        reserve_deployed=qty_mgr.get_reserve_deployed(),
        has_door_reserve_pool=(qty_mgr.get_reserve_requested() > 0),
    )

    door_metrics = {
        "mode": mode_name,
        "sku_counts": sku_counts,
        "sku_diversity_count": len(sku_counts),
        "total_door_placed": door_placed,
        "non_door_placed": non_door_placed,
        "door_reserve_requested": qty_mgr.get_reserve_requested(),
        "door_reserve_deployed": qty_mgr.get_reserve_deployed(),
        "door_reserve_remaining": qty_mgr.get_reserve_remaining(),
        "door_excess_placed_in_main": qty_mgr.get_excess_placed_in_main(),
        "door_excess_placed_in_transition": qty_mgr.get_excess_placed_in_transition(),
        "required_sku_fill_rate_pct": round(req_fill_rate, 2),
        "elastic_sku_fill_rate_pct": round(elastic_fill_rate, 2),
        "main_wall_end_x": round(main_wall_end_x, 3),
        "transition_start_x": round(frontier_metrics.transition_start_x, 3),
        "door_closure_start_x": round(frontier_metrics.door_closure_start_x, 3),
        "transition_reached": readiness.reached_transition_zone,
        "door_zone_reached": readiness.reached_door_closure_zone,
        "door_closure_coverage": readiness.door_closure_coverage,
        "largest_door_gap": readiness.largest_door_gap,
        "door_zone_occupancy": readiness.door_zone_occupancy,
        "door_wall_flatness": readiness.door_wall_flatness,
        "is_door_ready": readiness.is_door_ready,
        "door_readiness_score": readiness.door_readiness_score,
        "door_clearance_margin_m": readiness.door_clearance_margin_m,
        "authoritative_transition_start_x": readiness.authoritative_transition_start_x,
        "authoritative_door_start_x": readiness.authoritative_door_start_x,
        "boundary_source": readiness.boundary_source,
        "rejection_reasons": list(readiness.rejection_reasons),
    }

    telemetry_data = solution.telemetry.to_dict() if hasattr(solution.telemetry, "to_dict") else {}
    if not telemetry_data:
        telemetry_data = {
            "runtime_ms": getattr(solution.telemetry, "runtime_ms", 0.0),
            "steps_committed": getattr(solution.telemetry, "steps_committed", 0),
            "candidates_generated": getattr(solution.telemetry, "candidates_generated", 0),
            "candidates_evaluated": getattr(solution.telemetry, "candidates_evaluated", 0),
            "candidates_rejected_by_reason": getattr(solution.telemetry, "candidates_rejected_by_reason", {}),
            "phases_completed": getattr(solution.telemetry, "phases_completed", []),
        }

    overlap_count = len(val_res.overlap_violations) if hasattr(val_res, "overlap_violations") else 0
    bounds_count = len(val_res.bounds_violations) if hasattr(val_res, "bounds_violations") else 0
    hard_violations = len(val_res.rejection_reasons) if not val_res.is_valid else 0

    return {
        "placed_count": solution.placed_count,
        "unplaced_count": solution.unplaced_count,
        "volume_utilization_pct": round(solution.volume_utilization_pct, 2),
        "total_weight_kg": round(solution.total_weight_kg, 2),
        "is_valid": val_res.is_valid,
        "overlap_pair_count": overlap_count,
        "penetration_volume_m3": 0.0,
        "out_of_bounds_count": bounds_count,
        "hard_constraint_violations": hard_violations,
        "door_metrics": door_metrics,
        "telemetry": telemetry_data,
    }


def run_all_benchmarks():
    dataset_path = os.path.join(
        PROJECT_ROOT,
        "devkit",
        "cleanroom_solver_v2_devkit",
        "benchmarks",
        "40hq_cleanroom_case_001.json",
    )
    container, cargo_list = load_dataset(dataset_path)

    results = {}
    door_traces = {}

    door_seal_skus = [s for s in cargo_list if PackingRole.DOOR_SEAL in s.packing_roles or s.target_zone == ZoneType.DOOR]
    frontier = ElasticDoorFrontier(container=container, door_skus=door_seal_skus)
    allocations = frontier.allocations
    frontier_metrics = frontier.get_metrics()

    # 1. BaselineGreedy
    print("=== Running Mode 1: BaselineGreedy ===")
    solver1 = BaselineGreedySolver(max_candidates_per_step=150)
    sol1 = solver1.solve(container, cargo_list)
    results["BaselineGreedySolver"] = evaluate_solution_metrics(container, cargo_list, sol1, "BaselineGreedy")
    door_traces["BaselineGreedySolver"] = sol1.telemetry.door_readiness.get("door_deployment_trace", {}) if hasattr(sol1, "telemetry") and getattr(sol1.telemetry, "door_readiness", None) else {}
    print(f"  Placed: {sol1.placed_count}, Util: {sol1.volume_utilization_pct:.2f}%, Valid: {results['BaselineGreedySolver']['is_valid']}, DoorReady: {results['BaselineGreedySolver']['door_metrics']['is_door_ready']}")

    # 2. FAST (5s)
    print("=== Running Mode 2: FAST (5s) ===")
    cfg_fast = SearchConfig.for_profile(SearchProfile.FAST, seed=42)
    cfg_fast.time_budget_sec = 5.0
    solver2 = HierarchicalSearchSolver(config=cfg_fast)
    sol2 = solver2.solve(container, cargo_list)
    results["HierarchicalSearch (FAST)"] = evaluate_solution_metrics(container, cargo_list, sol2, "FAST")
    door_traces["HierarchicalSearch (FAST)"] = sol2.telemetry.door_readiness.get("door_deployment_trace", {}) if hasattr(sol2, "telemetry") and getattr(sol2.telemetry, "door_readiness", None) else {}
    print(f"  Placed: {sol2.placed_count}, Util: {sol2.volume_utilization_pct:.2f}%, Valid: {results['HierarchicalSearch (FAST)']['is_valid']}, DoorReady: {results['HierarchicalSearch (FAST)']['door_metrics']['is_door_ready']}")

    # 3. BALANCED (30s)
    print("=== Running Mode 3: BALANCED (30s) ===")
    cfg_bal = SearchConfig.for_profile(SearchProfile.BALANCED, seed=42)
    cfg_bal.time_budget_sec = 30.0
    solver3 = HierarchicalSearchSolver(config=cfg_bal)
    sol3 = solver3.solve(container, cargo_list)
    results["HierarchicalSearch (BALANCED)"] = evaluate_solution_metrics(container, cargo_list, sol3, "BALANCED")
    door_traces["HierarchicalSearch (BALANCED)"] = sol3.telemetry.door_readiness.get("door_deployment_trace", {}) if hasattr(sol3, "telemetry") and getattr(sol3.telemetry, "door_readiness", None) else {}
    print(f"  Placed: {sol3.placed_count}, Util: {sol3.volume_utilization_pct:.2f}%, Valid: {results['HierarchicalSearch (BALANCED)']['is_valid']}, DoorReady: {results['HierarchicalSearch (BALANCED)']['door_metrics']['is_door_ready']}")

    # 4. OPTIMIZE (60s)
    print("=== Running Mode 4: OPTIMIZE (60s) ===")
    cfg_opt = SearchConfig.for_profile(SearchProfile.OPTIMIZE, seed=42)
    cfg_opt.time_budget_sec = 60.0
    solver4 = HierarchicalSearchSolver(config=cfg_opt)
    sol4 = solver4.solve(container, cargo_list)
    results["HierarchicalSearch (OPTIMIZE)"] = evaluate_solution_metrics(container, cargo_list, sol4, "OPTIMIZE")
    door_traces["HierarchicalSearch (OPTIMIZE)"] = sol4.telemetry.door_readiness.get("door_deployment_trace", {}) if hasattr(sol4, "telemetry") and getattr(sol4.telemetry, "door_readiness", None) else {}
    print(f"  Placed: {sol4.placed_count}, Util: {sol4.volume_utilization_pct:.2f}%, Valid: {results['HierarchicalSearch (OPTIMIZE)']['is_valid']}, DoorReady: {results['HierarchicalSearch (OPTIMIZE)']['door_metrics']['is_door_ready']}")

    # Save outputs
    out_before_after = os.path.join(PROJECT_ROOT, "BLK002C_BEFORE_AFTER.json")
    with open(out_before_after, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Saved results to {out_before_after}")

    out_trace = os.path.join(PROJECT_ROOT, "BLK002C_DOOR_TRACE.json")
    diagnostic_data = {
        "diagnostic_goal": "BLK-002C Door Reserve Deployment & Boundary Unification Trace",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "container": {
            "Lx": container.Lx,
            "Ly": container.Ly,
            "Lz": container.Lz,
            "volume_m3": container.volume,
        },
        "authoritative_boundaries": {
            "transition_start_x": frontier_metrics.transition_start_x,
            "door_closure_start_x": frontier_metrics.door_closure_start_x,
            "latest_safe_main_x": frontier_metrics.latest_safe_main_x,
            "minimum_closure_depth": frontier_metrics.minimum_closure_depth,
            "preferred_closure_depth": frontier_metrics.preferred_closure_depth,
            "boundary_source": "ElasticDoorFrontier",
        },
        "door_reserve_allocations": {
            alloc.sku_id: {
                "total_qty": alloc.total_qty,
                "reserved_qty": alloc.reserved_qty,
                "excess_qty": alloc.excess_qty,
                "unit_depth_m": alloc.unit_depth_m,
                "layer_capacity": alloc.layer_capacity,
                "estimated_coverage_pct": alloc.estimated_coverage_pct,
            }
            for alloc in allocations.values()
        },
        "mode_door_traces": door_traces,
        "mode_metrics_summary": {
            m_name: {
                "placed_count": m_res["placed_count"],
                "utilization_pct": m_res["volume_utilization_pct"],
                "is_valid": m_res["is_valid"],
                "door_metrics": m_res["door_metrics"],
            }
            for m_name, m_res in results.items()
        }
    }
    with open(out_trace, "w", encoding="utf-8") as f:
        json.dump(diagnostic_data, f, indent=2)
    print(f"Saved door trace to {out_trace}")


if __name__ == "__main__":
    run_all_benchmarks()
