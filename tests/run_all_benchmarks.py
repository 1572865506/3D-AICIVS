"""
Benchmark and Regression Suite Runner
Generates comprehensive baseline performance and validation reports.
"""

import os
import sys
import json
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.test_benchmark_14sku import run_legacy_14sku_benchmark
from tests.test_bad_case_001 import run_bad_case_001_legacy_audit

def run_all_benchmarks():
    print("=" * 70)
    print("3D-AICIVS Solver V2 Migration: Baseline Benchmark & Audit Runner")
    print("=" * 70)

    # 1. 14 SKU Benchmark
    print("\n[1/2] Running 14 SKU Benchmark (40HQ Cleanroom Case 001)...")
    t0 = time.time()
    bm_report = run_legacy_14sku_benchmark()
    print(f"  -> Done in {time.time() - t0:.2f}s")
    print(f"  -> Placed: {bm_report['placed_count']}/{bm_report['requested_cartons']}")
    print(f"  -> Utilization: {bm_report['volume_utilization_pct']:.2f}%")
    print(f"  -> Overlaps: {bm_report['overlap_pair_count']}, Penetration Vol: {bm_report['penetration_volume']:.4f} m³")
    print(f"  -> Out of Bounds: {bm_report['out_of_bounds_count']}")

    # 2. BAD_CASE_001 Regression Audit
    print("\n[2/2] Running BAD_CASE_001 Regression Audit...")
    bc_report = run_bad_case_001_legacy_audit()
    print(f"  -> Evaluated: {bc_report['case_name']}")

    full_report = {
        "benchmark_14sku": bm_report,
        "bad_case_001": bc_report
    }

    report_path = os.path.join(PROJECT_ROOT, "tests", "baseline_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(full_report, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 70)
    print(f"✅ Baseline report saved to: {report_path}")
    print("=" * 70)
    return full_report

if __name__ == "__main__":
    run_all_benchmarks()
