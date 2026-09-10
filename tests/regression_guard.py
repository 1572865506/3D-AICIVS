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


def assert_reports(current, baseline):
    """任何用例硬约束或业务门禁失败均阻止发布；基准缺项也不能静默跳过。"""
    current = current.get('results', current)
    assert current, "没有基准结果"
    baseline = baseline.get('results', baseline)
    for case_id, cur in current.items():
        assert cur['is_valid'], f"{case_id}: 布局无效"
        assert cur['violations'] == 0, f"{case_id}: 存在违规"
        assert cur['overlap_pair_count'] == 0, f"{case_id}: 存在碰撞"
        fulfillment = cur['sku_fulfillment']
        assert not fulfillment['starved_skus'], f"{case_id}: SKU 饥饿"
        assert not fulfillment['priority_inversion'], f"{case_id}: 刚性/弹性优先级倒挂"
        base = baseline.get(case_id)
        if isinstance(base, dict) and 'utilization' in base:
            assert cur['utilization'] >= base['utilization'] * .98, f"{case_id}: 利用率回归"
            if 'sku_fulfillment' in base:
                assert fulfillment['rigid_completion_pct'] >= base['sku_fulfillment']['rigid_completion_pct'], f"{case_id}: 刚性履行率回归"
        else:
            assert case_id in REGRESSION_THRESHOLDS, f"{case_id}: 缺少基准或阈值"
            assert cur['utilization'] >= REGRESSION_THRESHOLDS[case_id]['min_util'], f"{case_id}: 未达到阈值"
    missing = [key for key, value in baseline.items()
               if isinstance(value, dict) and 'utilization' in value and key not in current]
    assert not missing, f"基准用例缺失: {missing}"


def test_no_regression():
    assert_reports(run_benchmark_suite(), load_baseline_data())


class TestRegressionGuard(unittest.TestCase):
    """Unittest test runner wrapper."""

    def test_no_regression(self):
        test_no_regression()


if __name__ == "__main__":
    unittest.main()
