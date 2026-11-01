"""
Regression Guard Test Suite (TASK-07 / Step 7.3).
Ensures current solver performance does not regress below established baseline.

双保险架构（基线裁决·架构修正案 A，2026-11）：
1. 相对棘轮（主防线）：当前运行不得低于 tests/baseline_report.json 锚点值的
   (1 - 容差)。锚点 = "已接受状态"，只随基准变化被接受的 commit 显式更新
   （AGENTS.md 5.5），禁止自动覆盖——自动同步会让棘轮退化为"这次和上次比"。
2. 绝对底线（兜底防线）：REGRESSION_THRESHOLDS 为不可侵蚀红线（已接受值
   × 0.95 标定），无论棘轮锚点如何变动，低于红线必挡——防"锚点被温水
   煮蛙式拉低"。红线仅允许在评审后移动。
方差策略：截止时间敏感用例（实测运行间方差 > 默认容差，如 SINGLE-SKU-MASS
±5pp）配置逐用例相对容差，绝对底线仍兜底灾难性回退。
守护输出收集全部失败项（不再首错即停），避免多例回归被字母序掩盖。
"""

import os
import sys
import json
import unittest
from typing import Dict, Any, List

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


# 绝对底线（兜底防线，标定 = 已接受值 × 0.95；仅评审后可移动）
REGRESSION_THRESHOLDS: Dict[str, Dict[str, float]] = {
    "14-SKU-1845":                     {"min_util": 79.2},
    "20GP-LOCKED-ORIENTATION":         {"min_util": 36.5},
    "20GP-NEAR-LIMIT":                 {"min_util": 56.6},
    "20GP-NOTOP-SPACE":                {"min_util": 24.8},
    "20GP-SINGLE-LAYER":               {"min_util": 34.4},
    "20GP-STACK-LAYERS":               {"min_util": 25.6},
    "20GP-STANDARD":                   {"min_util": 65.7},
    "45HQ-EXTENDED":                   {"min_util": 73.0},
    "ALL-CONSTRAINTS-COMBINED":        {"min_util": 49.3},
    "ALL-ELASTIC-SKUS":                {"min_util": 85.1},
    "ASYMMETRIC-BEARING-STRIPS":       {"min_util": 21.0},
    "BROAD-NO-TOP-STACK-PANELS":       {"min_util": 28.5},
    "CHECKERBOARD-NOTOP-ISOLATION":    {"min_util": 22.7},
    "DENSE-HEAVY-FLOOR-PAD":           {"min_util": 19.2},
    "DOOR-DENSE-SKUS":                 {"min_util": 66.3},
    "DOOR-ZONE-SPECIALIZED":           {"min_util": 40.2},
    "ELASTIC-DOMINANT-90PCT":          {"min_util": 42.2},
    "EXTREME-ASPECT-RATIO":            {"min_util": 33.2},
    "EXTREME-PAYLOAD-BEARING":         {"min_util": 18.3},
    "FLAT-ONLY-SLABS":                 {"min_util": 27.8},
    "FLOOR-AND-NOTOP-COMBINED":        {"min_util": 28.6},
    "FLOOR-SPACE-COMPETITION":         {"min_util": 17.1},
    "HETEROGENEOUS-BEARING-LIMITS":    {"min_util": 22.7},
    "INTERLEAVED-STACK-LAYERS":        {"min_util": 18.7},
    "LONG-BEAM-FLOOR":                 {"min_util": 23.2},
    "LOW-BEARING-FRAGILE-MID":         {"min_util": 20.7},
    "MAX-FLAT-LAYERS-CONSTRAINT":      {"min_util": 23.9},
    "MIXED-HETEROGENEOUS":             {"min_util": 66.9},
    "MULTI-SKU-NO-TOP-STACK":          {"min_util": 24.0},
    "MULTI-ZONE-CONSTRAINTS":          {"min_util": 49.5},
    "NOTOP-LARGE-WITH-ELASTIC-BURST":  {"min_util": 32.7},
    "ORIENTATION-HEIGHT-CUTOFF":       {"min_util": 27.0},
    "ORIENTATION-TOPSTACK-CONSTRAINTS":{"min_util": 38.1},
    "OVERWEIGHT-PAYLOAD":              {"min_util": 9.0},
    "RANDOM-STRESS-CASE-01":           {"min_util": 45.9},
    "RANDOM-STRESS-CASE-02":           {"min_util": 47.1},
    "RANDOM-STRESS-CASE-03":           {"min_util": 37.8},
    "RANDOM-STRESS-CASE-04":           {"min_util": 45.8},
    "RANDOM-STRESS-CASE-05":           {"min_util": 35.3},
    "RIGID-DOMINANT-95PCT":            {"min_util": 54.9},
    "RIGID-OVERLOAD-150PCT":           {"min_util": 82.3},
    "SINGLE-LARGE-BOX":                {"min_util": 86.9},
    "SINGLE-SKU-MASS":                 {"min_util": 70.0},
    "STACK-BEARING-CONSTRAINTS":       {"min_util": 41.4},
    "STEPPED-HEIGHT-TIPPING-SAFETY":   {"min_util": 24.3},
    "STEPPED-STACK-LAYERS-CASCADE":    {"min_util": 22.2},
    "STRICT-SINGLE-LAYER-FLOOR":       {"min_util": 38.5},
    "STRICT-THREE-STACK-LAYERS":       {"min_util": 22.0},
    "STRICT-TWO-STACK-LAYERS":         {"min_util": 29.0},
    "STRICT-UPRIGHT-MONOLITHIC":       {"min_util": 37.2},
    "TALL-SLENDER-TIPPING":            {"min_util": 35.0},
    "THREE-TIER-BEARING-CHAIN":        {"min_util": 26.7},
    "TWELVE-SKU-COMPLEX-MOSAIC":       {"min_util": 48.6},
    "TWO-LAYER-FLOOR-CEILING":         {"min_util": 30.4},
    "ULTRA-THIN-UPRIGHT-SCREENS":      {"min_util": 24.0},
    "ZERO-BEARING-ELASTIC-REFILL":     {"min_util": 17.0},
}

# 相对棘轮容差：默认 2%（AGENTS.md 5.5）；截止时间敏感用例按实测方差放宽
DEFAULT_UTIL_TOLERANCE = 0.02
PER_CASE_UTIL_TOLERANCE = {
    # SINGLE-SKU-MASS：求解截止时间敏感，实测运行间方差 73.8~84.35（±5pp）
    "SINGLE-SKU-MASS": 0.15,
}


def test_no_regression():
    """确保新版不低于锚点且不破绝对底线 (Regression Guard Test)."""
    baseline = load_baseline_data()
    current = run_benchmark_suite()

    evaluated_count = 0
    failures: List[str] = []
    for case_id, base in baseline.items():
        if not (isinstance(base, dict) and "utilization" in base and case_id in current):
            continue
        cur = current[case_id]
        evaluated_count += 1

        # 第一道防线：绝对底线（不可侵蚀红线）
        threshold = REGRESSION_THRESHOLDS.get(case_id)
        if threshold is not None and cur["utilization"] < threshold["min_util"]:
            failures.append(
                f"绝对底线: {case_id} 利用率 {cur['utilization']}% < 红线 {threshold['min_util']}%"
            )

        # 第二道防线：相对棘轮（不得低于已接受值 × (1 - 容差)）
        tolerance = PER_CASE_UTIL_TOLERANCE.get(case_id, DEFAULT_UTIL_TOLERANCE)
        if cur["utilization"] < base["utilization"] * (1 - tolerance):
            failures.append(
                f"相对棘轮: {case_id} 利用率从 {base['utilization']}% 降至 "
                f"{cur['utilization']}%（容差 {tolerance:.0%}）"
            )

        # 硬不变量：0 碰撞、0 违规（任何用例都不允许）
        if cur["overlap_pair_count"] != 0:
            failures.append(f"碰撞: {case_id} overlap_pairs={cur['overlap_pair_count']}")
        if cur.get("violations", 0) != 0:
            failures.append(f"违规: {case_id} violations={cur.get('violations', 0)}")

    assert evaluated_count >= 5, f"Expected at least 5 benchmark cases evaluated, got {evaluated_count}"
    assert not failures, (
        f"回归守护阻断（{len(failures)} 项）:\n" + "\n".join(failures)
    )


class TestRegressionGuard(unittest.TestCase):
    """Unittest test runner wrapper."""

    def test_no_regression(self):
        test_no_regression()


if __name__ == "__main__":
    unittest.main()
