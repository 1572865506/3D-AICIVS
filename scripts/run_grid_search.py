"""
Grid Search runner for Step 4.2:
Tests combinations of:
- beam_width: [3, 5, 8, 12]
- multi_start_runs: [3, 5, 8]
- enable_local_search: [True, False]
- terminal_topfill_repair_enabled: [True, False]

Records placed_count, utilization, runtime_ms, is_valid, violations.
Outputs results to artifacts/search_config_grid_search_report.json
"""
import copy
import json
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.domain.models import ContainerSpec, CargoSKU
from backend.solver_v2.search.config import SearchConfig, SearchProfile
from backend.solver_v2.search.engine import HierarchicalSearchSolver
from backend.solver_v2.solver.unified_solver import UnifiedSolver


def run_grid_search():
    dataset_path = PROJECT_ROOT / "devkit" / "cleanroom_solver_v2_devkit" / "benchmarks" / "40hq_cleanroom_case_001.json"
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 14-SKU benchmark excludes SKU-15
    data["cargo"] = [item for item in data["cargo"] if item["sku"] != "SKU-15"]
    container = InputAdapter.parse_container(data["containerSeed"])
    cargo_list = InputAdapter.parse_cargo_list(data["cargo"], data.get("cargoProfiles"))

    print(f"Loaded 14-SKU benchmark with {len(cargo_list)} SKUs and {sum(s.quantity.required for s in cargo_list)} items.")

    # Compute baseline greedy incumbent
    t_inc_0 = time.perf_counter()
    incumbent = UnifiedSolver(container)._solve_greedy(cargo_list)
    t_inc = time.perf_counter() - t_inc_0
    print(f"Baseline Greedy Incumbent: placed={incumbent.placed_count}, util={incumbent.volume_utilization_pct:.2f}%, valid={incumbent.validation_result.is_valid}, time={t_inc:.2f}s")

    # Grid search space
    beam_widths = [3, 5, 8, 12]
    multi_start_runs = [3, 5, 8]
    enable_local_searches = [True, False]
    terminal_topfill_repairs = [True, False]

    total_combinations = len(beam_widths) * len(multi_start_runs) * len(enable_local_searches) * len(terminal_topfill_repairs)
    print(f"Total parameter combinations to evaluate: {total_combinations}")

    results = []
    best_config = None
    best_util = -1.0
    best_under_20s = None

    idx = 0
    for bw in beam_widths:
        for ms in multi_start_runs:
            for ls in enable_local_searches:
                for tr in terminal_topfill_repairs:
                    idx += 1
                    # Per-trial time budget of 5.0s to ensure overall run finishes promptly and each test stays responsive
                    # while bounded within the <20s envelope
                    cfg = SearchConfig.for_profile(
                        SearchProfile.BALANCED,
                        seed=42,
                        beam_width=bw,
                        multi_start_runs=ms,
                        enable_local_search=ls,
                        terminal_topfill_repair_enabled=tr,
                        time_budget_sec=5.0,
                    )

                    solver = HierarchicalSearchSolver(config=cfg, incumbent_solution=incumbent)

                    t0 = time.perf_counter()
                    solution = solver.solve(container, cargo_list)
                    elapsed_ms = (time.perf_counter() - t0) * 1000.0
                    elapsed_s = elapsed_ms / 1000.0

                    util = solution.volume_utilization_pct
                    placed = solution.placed_count
                    is_valid = solution.validation_result.is_valid
                    violations_cnt = len(solution.validation_result.violations)

                    record = {
                        "run_index": idx,
                        "params": {
                            "beam_width": bw,
                            "multi_start_runs": ms,
                            "enable_local_search": ls,
                            "terminal_topfill_repair_enabled": tr,
                            "time_budget_sec": 5.0,
                        },
                        "placed_count": placed,
                        "utilization_pct": round(util, 4),
                        "runtime_ms": round(elapsed_ms, 2),
                        "runtime_sec": round(elapsed_s, 2),
                        "is_valid": is_valid,
                        "violations_count": violations_cnt,
                    }
                    results.append(record)

                    print(f"[{idx:02d}/{total_combinations}] bw={bw:2d}, ms={ms}, ls={str(ls):5s}, tr={str(tr):5s} -> placed={placed:4d}, util={util:6.2f}%, time={elapsed_s:5.2f}s, valid={is_valid}")

                    if is_valid and util > best_util:
                        best_util = util
                        best_config = record

                    if is_valid and elapsed_s < 20.0 and util > 75.0:
                        if best_under_20s is None or util > best_under_20s["utilization_pct"] or (abs(util - best_under_20s["utilization_pct"]) < 1e-4 and elapsed_ms < best_under_20s["runtime_ms"]):
                            best_under_20s = record

    report = {
        "benchmark": "14-SKU Canonical Benchmark (40HQ)",
        "total_combinations": total_combinations,
        "grid_space": {
            "beam_width": beam_widths,
            "multi_start_runs": multi_start_runs,
            "enable_local_search": enable_local_searches,
            "terminal_topfill_repair_enabled": terminal_topfill_repairs,
        },
        "incumbent_baseline": {
            "placed_count": incumbent.placed_count,
            "utilization_pct": round(incumbent.volume_utilization_pct, 4),
            "is_valid": incumbent.validation_result.is_valid,
            "runtime_sec": round(t_inc, 2),
        },
        "optimal_balanced_config": best_under_20s or best_config,
        "results": results,
    }

    out_path = PROJECT_ROOT / "artifacts" / "search_config_grid_search_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n[REPORT SAVED] Grid search results saved to {out_path}")
    print(f"[OPTIMAL BALANCED CONFIG]: {json.dumps(best_under_20s, indent=2)}")


if __name__ == "__main__":
    run_grid_search()
