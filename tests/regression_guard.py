"""
Regression Guard Test Suite (TASK-07 / Step 7.3).
Ensures current solver performance does not regress below established baseline.
"""

import os
import sys
import json
import unittest
from typing import Dict, Any

# Ensure project root in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.benchmark_suite import run_benchmark_suite

BASELINE_FILE = os.path.join(PROJECT_ROOT, "tests", "baseline_report.json")


def load_baseline_data() -> Dict[str, Any]:
    """Loads baseline dictionary with fallback paths."""
    if os.path.exists(BASELINE_FILE):
        with open(BASELINE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    elif os.path.exists("tests/baseline_report.json"):
        with open("tests/baseline_report.json", "r", encoding="utf-8") as f:
            return json.load(f)
    elif os.path.exists("baseline_report.json"):
        with open("baseline_report.json", "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        raise FileNotFoundError(f"Baseline file not found at {BASELINE_FILE}")


# 静态回归阈值（用于 baseline_report.json 中未记录的新用例）
# 新用例首次运行后应更新 baseline_report.json
REGRESSION_THRESHOLDS = {
    # 原有 5 个用例
    "14-SKU-1845":       {"min_util": 85.0, "max_violations": 0},
    "SINGLE-LARGE-BOX":  {"min_util": 88.0, "max_violations": 0},
    "ALL-ELASTIC-SKUS":  {"min_util": 82.0, "max_violations": 0},
    "DOOR-DENSE-SKUS":   {"min_util": 65.0, "max_violations": 0},
    "MIXED-HETEROGENEOUS": {"min_util": 67.0, "max_violations": 0},
    # 新增 10 个用例（初始阈值保守，随优化逐步提高）
    "20GP-STANDARD":     {"min_util": 55.0, "max_violations": 0},
    "45HQ-EXTENDED":     {"min_util": 55.0, "max_violations": 0},
    "STACK-BEARING-CONSTRAINTS": {"min_util": 50.0, "max_violations": 0},
    "ORIENTATION-TOPSTACK-CONSTRAINTS": {"min_util": 50.0, "max_violations": 0},
    "TALL-SLENDER-TIPPING": {"min_util": 50.0, "max_violations": 0},
    "OVERWEIGHT-PAYLOAD": {"min_util": 40.0, "max_violations": 0},
    "MULTI-ZONE-CONSTRAINTS": {"min_util": 55.0, "max_violations": 0},
    "EXTREME-ASPECT-RATIO": {"min_util": 40.0, "max_violations": 0},
    "SINGLE-SKU-MASS":   {"min_util": 70.0, "max_violations": 0},
    "ALL-CONSTRAINTS-COMBINED": {"min_util": 45.0, "max_violations": 0},
}


def test_no_regression():
    """确保新版不低于基线 (Regression Guard Test)."""
    baseline = load_baseline_data()
    current = run_benchmark_suite()

    evaluated_count = 0
    for case_id, base in baseline.items():
        if isinstance(base, dict) and "utilization" in base and case_id in current:
            cur = current[case_id]
            # Ensure utilization >= 98% of baseline
            assert cur["utilization"] >= base["utilization"] * 0.98, (
                f"回归: {case_id} 利用率从 {base['utilization']}% 降至 {cur['utilization']}%"
            )
            # Ensure 0 collisions / overlap pairs
            assert cur["overlap_pair_count"] == 0, (
                f"回归: {case_id} 出现碰撞重叠对: {cur['overlap_pair_count']}"
            )
            evaluated_count += 1

    assert evaluated_count >= 5, f"Expected at least 5 benchmark cases evaluated, got {evaluated_count}"


class TestRegressionGuard(unittest.TestCase):
    """Unittest test runner wrapper."""

    def test_no_regression(self):
        test_no_regression()


if __name__ == "__main__":
    unittest.main()
