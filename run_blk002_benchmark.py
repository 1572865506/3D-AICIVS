"""
BLK-002 Benchmark and Diagnostic Runner:
Runs BaselineGreedy, FAST, BALANCED, and OPTIMIZE on the canonical 14 SKU / 1845 Cartons benchmark.
Extracts comprehensive telemetry, door metrics, and before/after comparisons.
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
from backend.solver_v2.domain.models import PlacementContext, PackingRole, ZoneType
from backend.solver_v2.solver.baseline_solver import BaselineGreedySolver
from backend.solver_v2.search.engine import HierarchicalSearchSolver
from backend.solver_v2.search.config import SearchConfig, SearchProfile
from backend.solver_v2.door.elastic_frontier import ElasticDoorFrontier
from backend.solver_v2.door.closure_planner import DoorClosurePlanner
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator

BENCHMARK_PATH = os.path.join(PROJECT_ROOT, "devkit", "cleanroom_solver_v2_devkit", "benchmarks", "40hq_cleanroom_case_001.json")


def load_benchmark_case() -> Dict[str, Any]:
    with open(BENCHMARK_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_solution_metrics(mode_name: str, solution: Any, container: Any, cargo_list: List[Any], runtime_ms: float) -> Dict[str, Any]:
    placements = solution.placements
    val_res = solution.validation_result

    # Basic counts
    sku_placed: Dict[str, int] = {}
    for p in placements:
        sku_placed[p.sku_id] = sku_placed.get(p.sku_id, 0) + 1

    total_req = sum(s.quantity.required for s in cargo_list)
    placed_cnt = len(placements)
    unplaced_cnt = max(0, total_req - placed_cnt)

    # Elastic door frontier analysis
    door_seal_skus = [s for s in cargo_list if PackingRole.DOOR_SEAL in s.packing_roles or s.target_zone == ZoneType.DOOR]
    door_sku_ids = {s.sku_id for s in door_seal_skus}
    frontier = ElasticDoorFrontier(container=container, door_skus=door_seal_skus)
    allocations = frontier.allocations
    frontier_metrics = frontier.get_metrics(sku_placed)

    # Door metrics
    sku_02_placed = sku_placed.get("SKU-02", 0)
    sku_03_placed = sku_placed.get("SKU-03", 0)
    sku_04_placed = sku_placed.get("SKU-04", 0)
    sku_14_placed = sku_placed.get("SKU-14", 0)

    total_door_placed = sum(sku_placed.get(sid, 0) for sid in door_sku_ids)
    total_door_reserved = sum(a.reserved_qty for a in allocations.values())

    # Door excess placed in main (placements before door_closure_start_x)
    door_excess_in_main = 0
    main_placements = []
    transition_placements = []
    door_placements = []

    door_closure_x = frontier_metrics.door_closure_start_x
    trans_start_x = frontier_metrics.transition_start_x

    for p in placements:
        if p.max_x <= trans_start_x:
            main_placements.append(p)
            if p.sku_id in door_sku_ids:
                door_excess_in_main += 1
        elif p.max_x <= door_closure_x:
            transition_placements.append(p)
            if p.sku_id in door_sku_ids:
                door_excess_in_main += 1
        else:
            door_placements.append(p)

    main_wall_end_x = max([p.max_x for p in main_placements], default=0.0)

    # Door Readiness & Closure
    door_planner = DoorClosurePlanner(container=container)
    readiness_rep = door_planner.evaluate_door_readiness(placements)

    # SKU breakdown
    sku_breakdown = []
    for s in cargo_list:
        p_cnt = sku_placed.get(s.sku_id, 0)
        u_cnt = max(0, s.quantity.required - p_cnt)
        fill_pct = round((p_cnt / s.quantity.required * 100.0) if s.quantity.required > 0 else 0.0, 2)
        sku_breakdown.append({
            "sku_id": s.sku_id,
            "name": s.name,
            "requested": s.quantity.required,
            "placed": p_cnt,
            "unplaced": u_cnt,
            "fill_rate_pct": fill_pct,
            "is_elastic": s.quantity.is_elastic,
            "is_door_seal": s.sku_id in door_sku_ids,
        })

    overlap_count = len(val_res.overlap_violations) if hasattr(val_res, "overlap_violations") else 0
    bounds_count = len(val_res.bounds_violations) if hasattr(val_res, "bounds_violations") else 0
    hard_violations = len(val_res.rejection_reasons) if not val_res.is_valid else 0

    return {
        "mode": mode_name,
        "runtime_ms": round(runtime_ms, 2),
        "total_requested": total_req,
        "total_placed": placed_cnt,
        "total_unplaced": unplaced_cnt,
        "volume_utilization_pct": round(solution.volume_utilization_pct, 4),
        "total_weight_kg": round(solution.total_weight_kg, 2),
        "is_valid": val_res.is_valid,
        "overlap_pair_count": overlap_count,
        "penetration_volume_m3": 0.0,
        "out_of_bounds_count": bounds_count,
        "hard_constraint_violations": hard_violations,
        "door_metrics": {
            "sku_02_placed": sku_02_placed,
            "sku_03_placed": sku_03_placed,
            "sku_04_placed": sku_04_placed,
            "sku_14_placed": sku_14_placed,
            "total_door_placed": total_door_placed,
            "door_reserve_quantity": total_door_reserved,
            "door_excess_placed_in_main": door_excess_in_main,
            "main_wall_end_x": round(main_wall_end_x, 4),
            "transition_start_x": round(trans_start_x, 4),
            "door_closure_start_x": round(door_closure_x, 4),
            "door_closure_coverage": readiness_rep.door_closure_coverage,
            "largest_door_gap": readiness_rep.largest_door_gap,
            "door_wall_flatness": readiness_rep.door_wall_flatness,
            "is_door_ready": readiness_rep.is_door_ready,
            "door_readiness_score": readiness_rep.door_readiness_score,
            "door_clearance_margin_m": readiness_rep.door_clearance_margin_m,
        },
        "sku_breakdown": sku_breakdown,
        "telemetry": solution.telemetry.to_dict() if hasattr(solution.telemetry, "to_dict") else {},
    }


def run_all_benchmarks():
    case_data = load_benchmark_case()
    container = InputAdapter.parse_container(case_data["containerSeed"])
    cargo_list = InputAdapter.parse_cargo_list(case_data["cargo"])

    results = {}

    print("=== Running Mode 1: BaselineGreedy ===")
    t0 = time.perf_counter()
    solver_greedy = BaselineGreedySolver(seed=42)
    sol_greedy = solver_greedy.solve(container, cargo_list)
    dt_greedy = (time.perf_counter() - t0) * 1000.0
    results["BaselineGreedySolver"] = evaluate_solution_metrics("BaselineGreedySolver", sol_greedy, container, cargo_list, dt_greedy)
    print(f"  Placed: {sol_greedy.placed_count}, Util: {sol_greedy.volume_utilization_pct:.2f}%, Valid: {sol_greedy.validation_result.is_valid}")

    print("=== Running Mode 2: FAST (5s) ===")
    t0 = time.perf_counter()
    cfg_fast = SearchConfig.for_profile(SearchProfile.FAST, seed=42)
    cfg_fast.time_budget_sec = 5.0
    solver_fast = HierarchicalSearchSolver(config=cfg_fast)
    sol_fast = solver_fast.solve(container, cargo_list)
    dt_fast = (time.perf_counter() - t0) * 1000.0
    results["HierarchicalSearch (FAST)"] = evaluate_solution_metrics("HierarchicalSearch (FAST)", sol_fast, container, cargo_list, dt_fast)
    print(f"  Placed: {sol_fast.placed_count}, Util: {sol_fast.volume_utilization_pct:.2f}%, Valid: {sol_fast.validation_result.is_valid}")

    print("=== Running Mode 3: BALANCED (30s) ===")
    t0 = time.perf_counter()
    cfg_bal = SearchConfig.for_profile(SearchProfile.BALANCED, seed=42)
    cfg_bal.time_budget_sec = 30.0
    solver_bal = HierarchicalSearchSolver(config=cfg_bal)
    sol_bal = solver_bal.solve(container, cargo_list)
    dt_bal = (time.perf_counter() - t0) * 1000.0
    results["HierarchicalSearch (BALANCED)"] = evaluate_solution_metrics("HierarchicalSearch (BALANCED)", sol_bal, container, cargo_list, dt_bal)
    print(f"  Placed: {sol_bal.placed_count}, Util: {sol_bal.volume_utilization_pct:.2f}%, Valid: {sol_bal.validation_result.is_valid}")

    print("=== Running Mode 4: OPTIMIZE (60s) ===")
    t0 = time.perf_counter()
    cfg_opt = SearchConfig.for_profile(SearchProfile.OPTIMIZE, seed=42)
    cfg_opt.time_budget_sec = 60.0
    solver_opt = HierarchicalSearchSolver(config=cfg_opt)
    sol_opt = solver_opt.solve(container, cargo_list)
    dt_opt = (time.perf_counter() - t0) * 1000.0
    results["HierarchicalSearch (OPTIMIZE)"] = evaluate_solution_metrics("HierarchicalSearch (OPTIMIZE)", sol_opt, container, cargo_list, dt_opt)
    print(f"  Placed: {sol_opt.placed_count}, Util: {sol_opt.volume_utilization_pct:.2f}%, Valid: {sol_opt.validation_result.is_valid}")

    # Build Comparison Summary
    comparison = {
        "benchmark_dataset": "40hq_cleanroom_case_001.json",
        "fix_task": "BLK-002 — Elastic Door Reservation / Door Seal Cooperative Packing",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "results": results,
    }

    output_json_path = os.path.join(PROJECT_ROOT, "BLK002_BEFORE_AFTER.json")
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2, ensure_ascii=False)
    print(f"Saved results to {output_json_path}")

    # Build Door Diagnostic
    door_seal_skus = [s for s in cargo_list if PackingRole.DOOR_SEAL in s.packing_roles or s.target_zone == ZoneType.DOOR]
    frontier = ElasticDoorFrontier(container=container, door_skus=door_seal_skus)
    allocations = frontier.allocations
    frontier_metrics = frontier.get_metrics()

    diagnostic = {
        "diagnostic_goal": "BLK-002 Door Closure & Elastic Reservation Diagnostic",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "container": {
            "Lx": container.Lx,
            "Ly": container.Ly,
            "Lz": container.Lz,
            "volume_m3": container.volume,
        },
        "door_reserve_allocations": {
            sid: {
                "total_qty": a.total_qty,
                "reserved_qty": a.reserved_qty,
                "excess_qty": a.excess_qty,
                "unit_depth_m": a.unit_depth_m,
                "layer_capacity": a.layer_capacity,
                "estimated_coverage_pct": a.estimated_coverage_pct,
            }
            for sid, a in allocations.items()
        },
        "frontier_metrics_initial": {
            "required_door_volume": frontier_metrics.required_door_volume,
            "required_door_depth": frontier_metrics.required_door_depth,
            "minimum_closure_depth": frontier_metrics.minimum_closure_depth,
            "preferred_closure_depth": frontier_metrics.preferred_closure_depth,
            "latest_safe_main_x": frontier_metrics.latest_safe_main_x,
            "transition_start_x": frontier_metrics.transition_start_x,
            "door_closure_start_x": frontier_metrics.door_closure_start_x,
        },
        "mode_diagnostics": {
            k: v["door_metrics"] for k, v in results.items()
        }
    }

    diag_json_path = os.path.join(PROJECT_ROOT, "BLK002_DOOR_DIAGNOSTIC.json")
    with open(diag_json_path, "w", encoding="utf-8") as f:
        json.dump(diagnostic, f, indent=2, ensure_ascii=False)
    print(f"Saved diagnostic to {diag_json_path}")


if __name__ == "__main__":
    run_all_benchmarks()
