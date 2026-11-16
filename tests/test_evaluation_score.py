"""PlanScore 统一评分与多方案候选集测试。

钉住四件事：
1. 场景识别：15-SKU（含刚性封门薄板）→ DOOR_THIN_PANEL / SAFETY_FIRST；
2. T0 硬约束一票否决：违规/门禁 BLOCK → score=0、grade=F；
3. 推荐方案选择：不安全的高分方案不得被推荐（只提示"未达安全底线"）；
4. 求解器候选集：默认不保留（零影响），keep_candidates>0 时可按需转换，
   且不改变主解本身。

被谁调用：pytest 测试收集器（tests/ 目录）。
"""

import json
import os
import types

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in (__import__("sys").path):
    __import__("sys").path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.evaluation import (
    compare_plans,
    detect_scenario,
    evaluate_plan,
    rank_plans,
    score_plan,
)
from backend.solver_v2.evaluation.trial import door_open_stats, score_trial
from backend.solver_v2.evaluation.spec import POLICY_SAFETY_FIRST
from backend.solver_v2.solver.unified_solver import UnifiedSolver

FIXTURE = os.path.join(PROJECT_ROOT, "tests", "fixtures", "production_15sku.json")


def _mini_problem():
    case = {
        "container": {"usable": {"L": 6.0, "W": 2.35, "H": 2.69}, "maxPayloadTons": 28.6},
        "cargo": [
            {"sku": "BOX-A", "name": "A", "w": 0.5, "d": 0.5, "h": 0.5,
             "weight": 8.0, "quantity": 24, "requirement": "放中间"},
            {"sku": "BOX-B", "name": "B", "w": 0.4, "d": 0.6, "h": 0.3,
             "weight": 4.0, "quantity": 30, "requirement": "放中间"},
        ],
    }
    container = InputAdapter.parse_container(case["container"])
    cargo = InputAdapter.parse_cargo_list(case["cargo"])
    return container, cargo


def _fake_qa(min_sf=2.5, unstable_vol=0.1, pq=82.0):
    return {
        "door_open": {
            "column_count": 2 if min_sf is not None else 0,
            "unsafe_columns": 0 if (min_sf is None or min_sf >= 1.5) else 2,
            "min_sf": min_sf,
            "at_risk_volume_m3": 0.0 if (min_sf is None or min_sf >= 1.5) else 0.4,
        },
        "transport": {"slender_boxes": 2, "unstable_boxes": 0,
                      "unstable_volume_m3": unstable_vol},
        "support": {"partial_support_ratio_pct": 2.0},
        "islands": 0,
        "cavities": {"hidden_void_pct_of_bbox": 0.5},
        "plan_quality": {"score": pq, "grade": "A" if pq >= 80 else "C", "components": {}},
        "verdict": "GOOD",
    }


def _fake_gate():
    return {"verdict": "PASS", "blocked_by": [], "warnings": [],
            "checks": [{"id": "DG-013", "passed": True}],
            "cog": {"long_offset_pct": 1.0, "lat_offset_pct": 0.5}}


def _boxes():
    return [
        {"sku_id": "BOX-A", "x": 0.0, "y": 0.0, "z": 0.0, "dx": 0.5, "dy": 0.5, "dz": 0.5},
        {"sku_id": "BOX-B", "x": 0.5, "y": 0.0, "z": 0.0, "dx": 0.4, "dy": 0.6, "dz": 0.3},
    ]


def _compact_setup():
    """2×2×2 的 0.5m 方块 + 1.05m 柜：利用率 ~86%，用于验证"正常方案得高分"。"""
    case = {
        "container": {"usable": {"L": 1.05, "W": 1.05, "H": 1.05}},
        "cargo": [{"sku": "BOX-A", "name": "A", "w": 0.5, "d": 0.5, "h": 0.5,
                   "weight": 8.0, "quantity": 8, "requirement": "放中间"}],
    }
    container = InputAdapter.parse_container(case["container"])
    cargo = InputAdapter.parse_cargo_list(case["cargo"])
    boxes = [
        {"sku_id": "BOX-A", "x": float(x), "y": float(y), "z": float(z),
         "dx": 0.5, "dy": 0.5, "dz": 0.5}
        for x in (0.0, 0.5) for y in (0.0, 0.5) for z in (0.0, 0.5)
    ]
    return container, cargo, boxes


class TestScenarioAndScore:
    def test_scenario_detects_door_thin_panel(self):
        case = json.load(open(FIXTURE, encoding="utf-8"))
        container = InputAdapter.parse_container(case["container"])
        cargo = InputAdapter.parse_cargo_list(case["cargo"])
        scen = detect_scenario(cargo, container)
        assert scen["scenario"] == "DOOR_THIN_PANEL"
        assert scen["policy"] == POLICY_SAFETY_FIRST
        assert scen["flags"]["has_rigid_door"] is True
        assert scen["flags"]["has_thin_panel"] is True
        assert scen["reasons"]

    def test_score_plan_safe_plan_is_high(self):
        container, cargo, boxes = _compact_setup()
        ev = score_plan(boxes, cargo, container, qa=_fake_qa(), gate=_fake_gate())
        assert ev["hard_fail"] is False
        assert ev["score"] >= 85.0, ev
        assert ev["grade"] in ("A", "B")
        assert ev["tiers"]["T0"]["passed"] is True
        assert ev["tiers"]["T1"]["passed"] is True
        assert ev["metrics"]["rigid_ratio"] == pytest.approx(1.0)

    def test_t0_hard_fail_zeroes_score(self):
        container, cargo = _mini_problem()
        val = types.SimpleNamespace(violations=[object()], overlap_pair_count=1)
        ev = score_plan(_boxes(), cargo, container, qa=_fake_qa(),
                        gate=_fake_gate(), validation_result=val)
        assert ev["hard_fail"] is True
        assert ev["score"] == 0.0
        assert ev["grade"] == "F"
        assert ev["tiers"]["T0"]["reasons"]

    def test_gate_block_is_hard_fail(self):
        container, cargo = _mini_problem()
        gate = _fake_gate()
        gate["blocked_by"] = ["DG-004"]
        ev = score_plan(_boxes(), cargo, container, qa=_fake_qa(), gate=gate)
        assert ev["hard_fail"] is True
        assert "DG-004" in ev["tiers"]["T0"]["reasons"][0]

    def test_unsafe_plan_gets_deduction(self):
        container, cargo = _mini_problem()
        ev = score_plan(_boxes(), cargo, container,
                        qa=_fake_qa(min_sf=0.5, unstable_vol=1.2), gate=_fake_gate())
        assert ev["tiers"]["T1"]["passed"] is False
        assert any("SF" in d for d in ev["deductions"])
        assert any("侧向失稳" in d for d in ev["deductions"])

    def test_unmeasured_sequence_is_not_full_marks(self):
        """未测量顺序时不得给 10% 满分：T2 在刚性/弹性两项上重新归一。"""
        container, cargo = _mini_problem()
        ev_none = score_plan(_boxes(), cargo, container,
                             qa=_fake_qa(), gate=_fake_gate(), sequence_feasible=None)
        ev_ok = score_plan(_boxes(), cargo, container,
                           qa=_fake_qa(), gate=_fake_gate(), sequence_feasible=True)
        assert ev_none["metrics"]["sequence_measured"] is False
        assert ev_none["metrics"]["sequence_feasible"] is None
        assert ev_none["tiers"]["T2"]["components"]["loading_sequence"] is None
        assert ev_ok["tiers"]["T2"]["components"]["loading_sequence"] == 100.0
        assert ev_none["tiers"]["T2"]["score"] != ev_ok["tiers"]["T2"]["score"]


class TestRanking:
    def test_unsafe_plan_never_recommended(self):
        container, cargo = _mini_problem()
        safe = score_plan(_boxes(), cargo, container, qa=_fake_qa(), gate=_fake_gate())
        unsafe = score_plan(_boxes(), cargo, container,
                            qa=_fake_qa(min_sf=0.4, unstable_vol=1.5, pq=99.0),
                            gate=_fake_gate())
        rank = rank_plans([
            {"key": "safe", "label": "安全方案", "evaluation": safe},
            {"key": "unsafe", "label": "高装载方案", "evaluation": unsafe},
        ])
        assert rank["recommended_key"] == "safe"
        assert any("安全底线" in n for n in rank["notes"])

    def test_tradeoffs_are_explainable(self):
        container, cargo = _mini_problem()
        safe = score_plan(_boxes(), cargo, container, qa=_fake_qa(), gate=_fake_gate())
        other = json.loads(json.dumps(safe))
        other["metrics"]["utilization_pct"] = safe["metrics"]["utilization_pct"] + 1.8
        other["metrics"]["door_min_sf"] = 1.2
        other["score"] = safe["score"] + 2.0
        diffs = compare_plans(safe, other)
        assert any("装载率" in d for d in diffs)
        assert any("门面" in d for d in diffs)
        assert any("综合评分" in d for d in diffs)


class TestSolverCandidateSet:
    def test_default_keeps_no_candidates(self):
        container, cargo = _mini_problem()
        solver = UnifiedSolver(container)
        sol = solver.solve(cargo, time_budget=2)
        assert solver._candidate_plans == []
        assert sol.placed_count > 0

    def test_keep_candidates_builds_scored_ready_set(self):
        container, cargo = _mini_problem()
        solver = UnifiedSolver(container)
        sol = solver.solve(cargo, time_budget=3, options={"keep_candidates": 2})
        assert len(solver._candidate_plans) >= 1
        plans = solver.build_candidate_solutions(cargo, limit=2)
        assert 1 <= len(plans) <= 2
        # 主解不受候选集影响：首个候选就是最终解
        assert plans[0]["solution"].placed_count == sol.placed_count
        # 候选可直接评分（透传 telemetry.geometry_qa 或按需复算）
        ev = evaluate_plan(plans[0]["solution"], cargo, container)
        assert ev["metrics"]["placed_count"] == sol.placed_count
        assert 0.0 <= ev["score"] <= 100.0


class TestTrialScore:
    """trial 快速评分：公式必须与历史内联实现逐项等价。"""

    def test_formula_matches_legacy_scalar(self):
        info = score_trial(
            rigid_ratio=0.98, placed_volume=50.0, utilization=65.4,
            is_valid=True, violations=0, starved_rigid_count=0,
            priority_inversion=False, container_length=None,
        )
        expected = 0.98 * 5000.0 + 50.0 * 100.0 + 65.4
        assert info["score"] == pytest.approx(expected, abs=1e-3)
        assert info["hard_fail"] is False

    def test_hard_fail_flags(self):
        base = dict(rigid_ratio=1.0, placed_volume=10.0, utilization=50.0,
                    is_valid=True, violations=0, starved_rigid_count=0,
                    priority_inversion=False, container_length=None)
        assert score_trial(**base)["hard_fail"] is False
        assert score_trial(**{**base, "starved_rigid_count": 1})["hard_fail"] is True
        assert score_trial(**{**base, "is_valid": False})["hard_fail"] is True
        assert score_trial(**{**base, "priority_inversion": True})["hard_fail"] is True

    def test_door_open_stats_columns(self):
        # 门面 x=12.0：低矮宽列 SF=2*0.5/0.5=2.0；高薄列 SF=2*0.2/1.5=0.267
        placements = [
            {"x": 11.8, "y": 0.0, "dx": 0.2, "dy": 0.4, "dz": 1.5},
            {"x": 11.5, "y": 1.0, "dx": 0.5, "dy": 0.4, "dz": 0.5},
        ]
        stats = door_open_stats(placements, 12.032)
        assert stats["column_count"] == 2
        assert stats["unsafe_columns"] == 1
        assert stats["min_sf"] == pytest.approx(0.267, abs=1e-3)

    def test_no_door_cargo_has_no_sf(self):
        stats = door_open_stats(
            [{"x": 0.0, "y": 0.0, "dx": 0.2, "dy": 0.4, "dz": 1.5}], 12.032)
        assert stats["min_sf"] is None


class TestTrialBandChoice:
    """安全模式下，得分带内优先门面 SF；非安全模式保持"只比重心". """

    def _solver(self, safety_mode):
        solver = UnifiedSolver.__new__(UnifiedSolver)
        solver._safety_mode = safety_mode
        solver._balance_penalty = lambda placements: float(placements)
        return solver

    def _candidates(self):
        return [
            {"score": 100.0, "placements": 10.0, "balance_penalty": 9.0,
             "metrics": {"trial_score": {"door_min_sf": 3.0}},
             "trial_score": {"door_min_sf": 3.0}},
            {"score": 99.5, "placements": 20.0, "balance_penalty": 1.0,
             "metrics": {"trial_score": {"door_min_sf": 1.6}},
             "trial_score": {"door_min_sf": 1.6}},
        ]

    def test_safety_mode_prefers_higher_door_sf(self):
        chosen = self._solver(True)._choose_band_candidate(
            self._candidates(), 5.0, {"trial_score": {"door_min_sf": 1.6}})
        assert chosen is not None
        assert chosen["trial_score"]["door_min_sf"] == 3.0

    def test_non_safety_mode_keeps_balance_tiebreak(self):
        chosen = self._solver(False)._choose_band_candidate(
            self._candidates(), 5.0, {"trial_score": {"door_min_sf": 1.6}})
        assert chosen is not None
        assert chosen["balance_penalty"] == 1.0

    def test_non_safety_mode_no_replace_when_balance_worse(self):
        chosen = self._solver(False)._choose_band_candidate(
            self._candidates(), 0.5, {"trial_score": {"door_min_sf": 1.6}})
        assert chosen is None


class TestPlanSwitchRegistry:
    def test_plans_route_returns_full_loading_result(self):
        """多方案切换：/loading/{job}/plans/{idx} 必须返回可渲染的完整结果。"""
        from backend.api.service import LoadingAPIService

        container, cargo = _mini_problem()
        sol = UnifiedSolver(container).solve(cargo, time_budget=2)
        ev = evaluate_plan(sol, cargo, container)
        svc = LoadingAPIService()
        svc.register_solver_output(
            "job-test", sol, container, cargo,
            plan_score={"score": ev["score"]},
            plans=[{"key": "main", "label": "主方案", "recommended": True,
                    "score": ev["score"]}],
            recommended_plan="main",
            plan_group_id="job-test",
        )
        svc.register_alternatives("job-test", [{
            "key": "alt-0", "label": "备选", "recommended": False,
            "evaluation": ev, "solution": sol,
        }], container, cargo)

        code, body = svc.dispatch("/api/v1/loading/job-test/plans")
        assert code == 200
        assert [p["key"] for p in body["plans"]] == ["alt-0"]

        code, alt = svc.dispatch("/api/v1/loading/job-test/plans/0")
        assert code == 200
        assert alt["version"] == "BLK007C"
        assert alt["metrics"]["plan_group_id"] == "job-test"
        assert len(alt["cargo"]) == sol.placed_count


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
