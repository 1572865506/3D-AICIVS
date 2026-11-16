"""PlanScore 基准数据一致性测试（自测试环节的基础设施）。

钉住三件事：
1. 基准覆盖全部 56 个用例，且分数/等级/分项在合法区间；
2. 等级由分数与 T0 状态唯一决定（避免手改/口径漂移）；
3. T0 作废的方案必须对应交付门禁 REJECT（评分与门禁语义一致）。

不重算求解（基准由 `python scripts/build_plan_score_baseline.py` 从
`tests/benchmark_results.json` 生成），因此测试可在 1s 内完成。

被谁调用：pytest 测试收集器（tests/ 目录）。
"""

import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in (__import__("sys").path):
    __import__("sys").path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.evaluation.spec import grade_for

BASELINE_PATH = os.path.join(PROJECT_ROOT, "tests", "plan_score_baseline.json")
BENCHMARK_PATH = os.path.join(PROJECT_ROOT, "tests", "benchmark_results.json")


class TestPlanScoreBaseline:
    @pytest.fixture(scope="class")
    def baseline(self):
        assert os.path.exists(BASELINE_PATH), "缺少 PlanScore 基准文件，请先运行 scripts/build_plan_score_baseline.py"
        return json.load(open(BASELINE_PATH, encoding="utf-8"))

    @pytest.fixture(scope="class")
    def benchmark(self):
        return json.load(open(BENCHMARK_PATH, encoding="utf-8"))

    def test_covers_all_benchmark_cases(self, baseline, benchmark):
        results = benchmark.get("results") or {}
        assert baseline["case_count"] >= 50
        assert len(baseline["cases"]) == baseline["case_count"]
        assert set(baseline["cases"]) == set(results)

    def test_scores_and_tiers_in_range(self, baseline):
        for case_id, rec in baseline["cases"].items():
            score = rec["score"]
            assert isinstance(score, (int, float)) and 0.0 <= score <= 100.0, case_id
            assert rec["grade"] in ("A", "B", "C", "D", "F"), case_id
            assert set(rec["tiers"]) == {"T0", "T1", "T2", "T3", "T4"}, case_id
            for tier, value in rec["tiers"].items():
                assert 0.0 <= float(value) <= 100.0, (case_id, tier)

    def test_grade_is_derived_from_score_and_t0(self, baseline):
        for case_id, rec in baseline["cases"].items():
            expected = grade_for(float(rec["score"]), bool(rec["hard_fail"]))
            assert rec["grade"] == expected, (case_id, rec["grade"], expected)

    def test_hard_fail_aligns_with_gate_reject(self, baseline, benchmark):
        results = benchmark.get("results") or {}
        for case_id, rec in baseline["cases"].items():
            if not rec["hard_fail"]:
                continue
            gate = (results.get(case_id) or {}).get("delivery_gate") or {}
            assert gate.get("verdict") == "REJECT", case_id

    def test_policy_distribution_is_populated(self, baseline):
        assert baseline["policy_counts"]
        assert sum(baseline["policy_counts"].values()) == baseline["case_count"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
