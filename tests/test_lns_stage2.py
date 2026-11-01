"""阶段二 LNS（破坏-重建）回归测试。

路线图硬性要求：重建路径的每一次放置必须走与主流程完全相同的约束过滤器
（统一门禁）；接受准则为棘轮（体积升 + 刚性履行不降）；仅批处理模式
显式启用（options["lns_enabled"]），默认路径零影响。

被谁调用：pytest 测试收集器（tests/ 目录）。
"""

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in (__import__("sys").path):
    __import__("sys").path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.solver.unified_solver import UnifiedSolver

CONTAINER_SPEC = {"usable": {"L": 12.032, "W": 2.352, "H": 2.698}}

CARGO = [
    {"sku": "A1", "name": "标准箱A", "w": 1.2, "d": 1.0, "h": 1.0, "weight": 80.0, "quantity": 30},
    {"sku": "B1", "name": "中箱B", "w": 0.8, "d": 0.6, "h": 0.6, "weight": 25.0, "quantity": 50},
    {"sku": "C1", "name": "扁平箱C", "w": 1.0, "d": 0.8, "h": 0.35, "weight": 15.0, "quantity": 40},
]


def _solve(lns_enabled: bool, budget_s: float = 3.0):
    container = InputAdapter.parse_container(CONTAINER_SPEC)
    cargo = InputAdapter.parse_cargo_list(CARGO)
    solver = UnifiedSolver(container)
    options = {"lns_enabled": lns_enabled, "lns_budget_s": budget_s, "lns_rounds": 10} if lns_enabled else None
    return solver.solve(cargo, options=options)


class TestLNSStage2:
    def test_lns_disabled_by_default(self):
        """默认路径零影响：未显式启用时无 LNS 遥测、行为与基线一致。"""
        sol = _solve(lns_enabled=False)
        assert sol.telemetry.lns_metrics is None, "默认路径不应触发 LNS"
        assert sol.validation_result.is_valid

    def test_lns_enabled_ratchet_holds(self):
        """启用 LNS：违规 0、利用率不降、刚性履行不降、LNS 真实运行。"""
        base = _solve(lns_enabled=False)
        lns = _solve(lns_enabled=True, budget_s=3.0)

        assert lns.telemetry.lns_metrics is not None, "LNS 未运行"
        assert lns.telemetry.lns_metrics["rounds"] > 0, "LNS 未执行任何破坏-重建轮"
        assert not lns.validation_result.violations, (
            f"LNS 解存在违规: {lns.validation_result.violations[:3]}"
        )
        assert lns.volume_utilization_pct >= base.volume_utilization_pct - 1e-6, (
            f"LNS 利用率回退: {base.volume_utilization_pct:.2f} -> {lns.volume_utilization_pct:.2f}"
        )
        # 刚性履行不降（按已放置箱数比较，两解请求量相同）
        base_rigid = sum(1 for p in base.placements if p.sku_id in ("A1", "B1", "C1"))
        lns_rigid = len(lns.placements)
        assert lns_rigid >= base_rigid, f"LNS 放置数回退: {base_rigid} -> {lns_rigid}"

    def test_lns_rebuild_uses_unified_gate(self):
        """结构钉住：重建入口必须调用统一门禁（源码级，防未来绕过过滤器）。"""
        import re
        src_path = os.path.join(PROJECT_ROOT, "backend", "solver_v2", "solver", "unified_solver.py")
        with open(src_path, "r", encoding="utf-8") as f:
            src = f.read()
        lns_body = src[src.index("def _lns_rebuild"):src.index("def _lns_rebuild") + 6000]
        assert "_check_candidate_validity_with_reason" in lns_body, (
            "LNS 重建未走统一门禁（违反路线图\"重建路径不得绕过过滤器\"硬性要求）"
        )
        assert "_has_collision(cand" not in lns_body.replace(
            "_check_candidate_validity_with_reason(cand, placements)", ""
        ), "LNS 重建存在绕过门禁的裸碰撞检查"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
