"""弹性填充规则与薄板码放回归测试（15-SKU 真实货单驱动）。

钉住两件事：
1. 弹性填充放行判据 = 刚性履行率 ≥ 99%（而非"刚性剩余为 0"）——
   防止 6 箱刚性卡死导致 674 箱弹性件全部弃装；
2. 薄板件自由空间网格码放：必须能从货堆顶面起码，且逐格走统一门禁。

被谁调用：pytest 测试收集器（tests/ 目录）。
"""

import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in (__import__("sys").path):
    __import__("sys").path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.solver.unified_solver import UnifiedSolver


class TestElasticFillPolicy:
    def test_allowed_at_or_above_99pct(self):
        s = UnifiedSolver.__new__(UnifiedSolver)
        assert UnifiedSolver._elastic_fill_allowed(s, 99.0) is True
        assert UnifiedSolver._elastic_fill_allowed(s, 99.59) is True
        assert UnifiedSolver._elastic_fill_allowed(s, 100.0) is True

    def test_blocked_below_99pct(self):
        """低于 99% 必须禁止弹性填充（防优先级倒挂铁律）。"""
        s = UnifiedSolver.__new__(UnifiedSolver)
        assert UnifiedSolver._elastic_fill_allowed(s, 98.99) is False
        assert UnifiedSolver._elastic_fill_allowed(s, 50.0) is False
        assert UnifiedSolver._elastic_fill_allowed(s, 0.0) is False


class TestProductionManifest:
    """15-SKU 真实产线单：算法与门禁契合度基线。"""

    @pytest.fixture(scope="class")
    def result(self):
        from backend.solver_v2.api.adapter import InputAdapter
        from backend.solver_v2.validation.delivery_gate import evaluate_delivery

        path = os.path.join(PROJECT_ROOT, "tests", "fixtures", "production_15sku.json")
        case = json.load(open(path, encoding="utf-8"))
        container = InputAdapter.parse_container(case["container"])
        cargo = InputAdapter.parse_cargo_list(case["cargo"])
        sol = UnifiedSolver(container).solve(cargo)
        gate = evaluate_delivery(sol, cargo, container)
        return case, container, cargo, sol, gate

    def test_zero_violations(self, result):
        _, _, _, sol, _ = result
        assert not sol.validation_result.violations

    def test_no_rigid_starvation(self, result):
        """刚性 SKU 不得 0 放置（弹性件不受此限）。"""
        case, _, _, sol, _ = result
        placed = {}
        for p in sol.placements:
            placed[p.sku_id] = placed.get(p.sku_id, 0) + 1
        for c in case["cargo"]:
            req = c["requirement"]
            is_elastic = "可以减少" in req or "可减少" in req
            if not is_elastic and c["quantity"] > 0:
                assert placed.get(c["sku"], 0) > 0, f"刚性 SKU {c['sku']} 饥饿"

    def test_elastic_filler_actually_places(self, result):
        """弹性薄板件（SKU-14）必须实际装入（此前被 6 箱刚性卡死为 0）。"""
        case, _, _, sol, _ = result
        placed = sum(1 for p in sol.placements if p.sku_id == "SKU-14")
        assert placed > 0, "弹性填充未生效：SKU-14 仍为 0 装"

    def test_gate_not_rejected(self, result):
        *_, gate = result
        assert gate["verdict"] != "REJECT", gate["blocked_by"]
        assert not (set(gate["blocked_by"]) & {"DG-001", "DG-002", "DG-003", "DG-004", "DG-012"})

    def test_utilization_floor(self, result):
        """利用率底线（当前已达成 85%+，防回退）。"""
        _, _, _, sol, _ = result
        assert sol.volume_utilization_pct >= 84.0, sol.volume_utilization_pct


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
