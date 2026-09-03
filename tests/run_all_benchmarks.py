"""
Baseline Report & Regression Verification Runner (TASK-07 / Step 7.2)
Generates and verifies the performance baseline report comparing Phase 2 optimized solver against legacy baseline.
"""

import os
import sys
import json
import time
from typing import Dict, Any

# Ensure UTF-8 output encoding on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.benchmark_suite import run_benchmark_suite
from tests.test_bad_case_001 import run_bad_case_001_legacy_audit

BASELINE_REPORT_PATH = os.path.join(PROJECT_ROOT, "tests", "baseline_report.json")

# Historic Legacy Baseline constants (Pre-Phase 2)
LEGACY_BASELINE = {
    "14-SKU-1845": {
        "solver": "Legacy V1.0 (Unoptimized)",
        "placed_count": 1317,
        "requested_cartons": 2145,
        "volume_utilization_pct": 72.7746,
        "overlap_pair_count": 0,
        "penetration_volume": 0.0,
        "out_of_bounds_count": 0,
    }
}


def generate_and_verify_baseline_report() -> Dict[str, Any]:
    print("=" * 80)
    print("3D-AICIVS Solver Phase 2: Baseline Performance & Regression Audit (Step 7.2)")
    print("=" * 80)

    # 1. Run all 5 standard benchmarks
    suite_output = run_benchmark_suite()
    results = suite_output["results"]

    # 2. Extract 14-SKU benchmark result
    sku14_result = results.get("14-SKU-1845", {})
    legacy_14sku = LEGACY_BASELINE["14-SKU-1845"]

    # 3. Calculate 14-SKU deltas
    old_placed = legacy_14sku["placed_count"]
    new_placed = sku14_result.get("placed_count", 0)
    placed_delta = new_placed - old_placed
    placed_pct_change = (placed_delta / old_placed * 100.0) if old_placed > 0 else 0.0

    old_util = legacy_14sku["volume_utilization_pct"]
    new_util = sku14_result.get("volume_utilization_pct", sku14_result.get("utilization", 0.0))
    util_delta_pp = new_util - old_util  # Percentage points increase
    util_ratio = (new_util / old_util) if old_util > 0 else 1.0

    # Verification checks
    passes_14sku_threshold = new_util >= 78.0  # Acceptance criteria: >= 78% (from 72.77% +5pp)
    passes_util_improvement_5pp = util_delta_pp >= 5.0
    passes_no_regression_98pct = util_ratio >= 0.98
    all_zero_collisions = suite_output["all_zero_collisions"]

    # 4. Bad case 001 audit
    bad_case_report = run_bad_case_001_legacy_audit()

    # 5. Build comprehensive baseline report
    comparison_14sku = {
        "legacy_baseline": {
            "solver": legacy_14sku["solver"],
            "placed_count": old_placed,
            "volume_utilization_pct": round(old_util, 4),
            "collisions": legacy_14sku["overlap_pair_count"]
        },
        "phase2_optimized": {
            "solver": "Phase 2 Solver (GlobalPlan + MultiStart + WallOptimization)",
            "placed_count": new_placed,
            "volume_utilization_pct": round(new_util, 4),
            "runtime_ms": sku14_result.get("runtime_ms", 0.0),
            "collisions": sku14_result.get("collisions", 0),
            "violations": sku14_result.get("violations", 0)
        },
        "delta": {
            "placed_count_diff": placed_delta,
            "placed_count_pct_change": round(placed_pct_change, 2),
            "utilization_diff_percentage_points": round(util_delta_pp, 4),
            "utilization_ratio_vs_legacy": round(util_ratio, 4)
        },
        "acceptance_evaluation": {
            "utilization_target_ge_78pct": {
                "target": ">= 78.0%",
                "actual": f"{new_util:.2f}%",
                "passed": passes_14sku_threshold
            },
            "utilization_improvement_ge_5pp": {
                "target": ">= +5.0 pp",
                "actual": f"+{util_delta_pp:.2f} pp",
                "passed": passes_util_improvement_5pp
            },
            "no_regression_ge_98pct_of_legacy": {
                "target": ">= 98.0% of legacy",
                "actual": f"{util_ratio * 100.0:.2f}%",
                "passed": passes_no_regression_98pct
            },
            "zero_collisions": {
                "target": "== 0",
                "actual": sku14_result.get("collisions", 0),
                "passed": sku14_result.get("collisions", 0) == 0
            }
        }
    }

    full_baseline_report = {
        "report_type": "3D-AICIVS Phase 2 Solver Baseline & Regression Report",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "PASS" if (passes_14sku_threshold and passes_no_regression_98pct and all_zero_collisions) else "FAIL",
        "benchmark_14sku_comparison": comparison_14sku,
        "benchmark_suite_summary": suite_output["summary"],
        "all_cases_detailed": results,
        "bad_case_001_audit": bad_case_report,
        **results
    }

    # Save to tests/baseline_report.json
    with open(BASELINE_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(full_baseline_report, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 80)
    print("Baseline Comparison & Verification Summary:")
    print(f"  * 14-SKU Placed Count: {old_placed} -> {new_placed} (diff: {placed_delta:+d} / {placed_pct_change:+.2f}%)")
    print(f"  * 14-SKU Utilization : {old_util:.2f}% -> {new_util:.2f}% (diff: {util_delta_pp:+.2f} percentage points)")
    print(f"  * Target >= 78.0%    : {'[PASS]' if passes_14sku_threshold else '[FAIL]'} ({new_util:.2f}%)")
    print(f"  * Improvement >= +5pp: {'[PASS]' if passes_util_improvement_5pp else '[FAIL]'} (+{util_delta_pp:.2f}pp)")
    print(f"  * Regression Guard   : {'[PASS]' if passes_no_regression_98pct else '[FAIL]'} ({util_ratio*100:.2f}% of baseline)")
    print(f"  * Collisions across suite: {'[PASS] 0 collisions' if all_zero_collisions else '[FAIL] collisions detected'}")
    print(f"[OK] Baseline report saved to: {BASELINE_REPORT_PATH}")
    print("=" * 80)

    return full_baseline_report


if __name__ == "__main__":
    generate_and_verify_baseline_report()
