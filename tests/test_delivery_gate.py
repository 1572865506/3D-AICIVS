"""交付门禁（Delivery Gate）回归测试。

钉住：
1. 干净解 → PASS；违规/饥饿/超载/不可解释空腔 → REJECT；
2. 重心严重偏载 → REJECT（DG-011），轻度偏载 → WARN（DG-014）；
3. 超载货单不因履约率误拦截（DG-005 只在体积可装下时强制）；
4. 几何观感差（隐蔽洞/台阶/孤岛）→ WARN 但不阻断。

被谁调用：pytest 测试收集器（tests/ 目录）。
"""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in (__import__("sys").path):
    __import__("sys").path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.domain.models import BoxDim, CargoSKU, Placement, Point3D, Orientation3D, PlacementContext
from backend.solver_v2.validation.delivery_gate import evaluate_delivery, load_policy


@dataclass
class _StubViolation:
    violation_type_name: str = "FAKE"

    class _T:
        name = "FAKE"

    @property
    def violation_type(self):
        return self._T()


@dataclass
class _StubValidation:
    violations: List[Any] = field(default_factory=list)
    overlap_pair_count: int = 0


@dataclass
class _StubTelemetry:
    geometry_qa: Optional[Dict[str, Any]] = None
    cavity_diagnostics: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class _StubSolution:
    container: Any
    placements: List[Any]
    validation_result: Any = field(default_factory=_StubValidation)
    telemetry: Any = field(default_factory=_StubTelemetry)


def _container(l=6.0, w=2.4, h=2.6, payload=10000.0):
    return InputAdapter.parse_container({"usable": {"L": l, "W": w, "H": h}, "maxPayloadTons": payload / 1000.0})


def _sku(sku_id="A", w=1.0, d=1.0, h=1.0, weight=50.0, req=8):
    return CargoSKU(
        sku_id=sku_id, name=sku_id, box=BoxDim(w, d, h), weight_kg=weight,
        quantity=__import__("backend.solver_v2.domain.models", fromlist=["QuantityPlan"]).QuantityPlan(required=req),
    )


def _plc(pid, sku, x, y, z, dx=1.0, dy=1.0, dz=1.0, weight=50.0):
    return Placement(pid, "i" + pid, sku, Point3D(x, y, z), Orientation3D(dx, dy, dz),
                     weight, PlacementContext.MAIN_WALL)


def _clean_qa(**over):
    qa = {
        "bbox_void_ratio_pct": 10.0,
        "cavities": {"hidden_void_pct_of_bbox": 0.2, "skyline_void_pct_of_bbox": 5.0,
                     "enclosed_volume_m3": 0.0, "count": 0, "top": []},
        "top_surface": {"steep_step_ratio_pct": 2.0},
        "support": {"partial_support_ratio_pct": 0.5},
        "islands": 0,
    }
    qa.update(over)
    return qa


class TestDeliveryGate:
    def test_clean_solution_passes(self):
        """居中放置、无违规、无饥饿 → PASS。"""
        c = _container()
        # 居中对称摆放（重心 x/y 均 50%）
        sol = _StubSolution(container=c, placements=[
            _plc("p1", "A", 2.0, 0.2, 0.0), _plc("p2", "A", 3.0, 0.2, 0.0),
            _plc("p3", "A", 2.0, 1.2, 0.0), _plc("p4", "A", 3.0, 1.2, 0.0),
        ])
        sol.telemetry.geometry_qa = _clean_qa()
        rep = evaluate_delivery(sol, [_sku(req=4)], c)
        assert rep["verdict"] == "PASS", rep
        assert rep["cog"]["long_offset_pct"] < 10

    def test_violation_blocks_delivery(self):
        """硬约束违规 → REJECT（DG-001）。"""
        c = _container()
        sol = _StubSolution(container=c, placements=[_plc("p1", "A", 0, 0, 0)],
                            validation_result=_StubValidation(violations=[_StubViolation()]))
        rep = evaluate_delivery(sol, [_sku(req=1)], c)
        assert rep["verdict"] == "REJECT" and "DG-001" in rep["blocked_by"], rep

    def test_collision_blocks_delivery(self):
        """碰撞对 → REJECT（DG-002）。"""
        c = _container()
        sol = _StubSolution(container=c, placements=[_plc("p1", "A", 2, 0, 0)],
                            validation_result=_StubValidation(overlap_pair_count=1))
        rep = evaluate_delivery(sol, [_sku(req=1)], c)
        assert rep["verdict"] == "REJECT" and "DG-002" in rep["blocked_by"], rep

    def test_starved_rigid_sku_blocks(self):
        """刚性 SKU 有需求却 0 放置 → REJECT（DG-004）。"""
        c = _container()
        sol = _StubSolution(container=c, placements=[_plc("p1", "A", 2, 0, 0)])
        rep = evaluate_delivery(sol, [_sku("A", req=1), _sku("B", req=5)], c)
        assert rep["verdict"] == "REJECT" and "DG-004" in rep["blocked_by"], rep

    def test_overweight_solution_blocks(self):
        """超载 → REJECT（DG-003）。"""
        c = _container(payload=100.0)
        sol = _StubSolution(container=c, placements=[_plc("p1", "A", 2, 0, 0, weight=80),
                                                    _plc("p2", "A", 3, 0, 0, weight=80)])
        rep = evaluate_delivery(sol, [_sku(req=2)], c)
        assert rep["verdict"] == "REJECT" and "DG-003" in rep["blocked_by"], rep

    def test_over_requested_manifest_not_blocked_by_fulfillment(self):
        """请求体积远超柜容（超载货单）→ DG-005 不触发硬门槛（避免误拦截）。"""
        c = _container(l=2.4, w=1.0, h=1.0)  # 2.4 m3
        sol = _StubSolution(container=c, placements=[_plc("p1", "A", 0.7, 0.0, 0.0, 1.0, 1.0, 1.0)])
        sol.telemetry.geometry_qa = _clean_qa()
        # 请求 40 件 × 1 m3 = 40 m3 >> 柜容
        rep = evaluate_delivery(sol, [_sku(req=40)], c)
        assert "DG-005" not in rep["blocked_by"], rep
        assert rep["verdict"] != "REJECT", rep

    def test_severe_cog_offset_blocks(self):
        """重心严重偏载（纵向 > 20%）→ REJECT（DG-011）。"""
        c = _container(l=12.0, w=2.4)
        # 全部箱子压在柜尾一端 → 纵向偏载极大
        plcs = [_plc(f"p{i}", "A", 0.0, 0.0, 0.0, 1.0, 1.0, 1.0) for i in range(4)]
        sol = _StubSolution(container=c, placements=plcs)
        sol.telemetry.geometry_qa = _clean_qa()
        rep = evaluate_delivery(sol, [_sku(req=4)], c)
        assert rep["cog"]["long_offset_pct"] > 20
        assert rep["verdict"] == "REJECT" and "DG-011" in rep["blocked_by"], rep

    def test_mild_cog_offset_warns_not_blocks(self):
        """轻度偏载（10%~20%）→ WARN（DG-014）但不拦截。"""
        c = _container(l=12.0, w=2.4)
        plcs = [_plc(f"p{i}", "A", 3.7, 0.7, 0.0, 1.0, 1.0, 1.0) for i in range(3)]
        sol = _StubSolution(container=c, placements=plcs)
        sol.telemetry.geometry_qa = _clean_qa()
        rep = evaluate_delivery(sol, [_sku(req=3)], c)
        assert 10 < rep["cog"]["long_offset_pct"] < 20, rep["cog"]
        assert rep["verdict"] == "WARN" and "DG-014" in rep["warnings"], rep

    def test_ugly_geometry_warns(self):
        """隐蔽洞/台阶/孤岛超限 → WARN 但不阻断（视觉质量问题分级处理）。"""
        c = _container()
        sol = _StubSolution(container=c, placements=[_plc("p1", "A", 2.5, 0.7, 0.0)])
        sol.telemetry.geometry_qa = _clean_qa(
            cavities={"hidden_void_pct_of_bbox": 8.0, "skyline_void_pct_of_bbox": 20.0,
                      "enclosed_volume_m3": 5.0, "count": 3, "top": []},
            top_surface={"steep_step_ratio_pct": 40.0}, islands=3,
        )
        rep = evaluate_delivery(sol, [_sku(req=1)], c)
        assert rep["verdict"] == "WARN", rep
        assert {"DG-006", "DG-008", "DG-010"} <= set(rep["warnings"]), rep

    def test_unexplained_cavity_blocks(self):
        """无成因分类的空腔 → REJECT（DG-012，R3 棘轮不变量）。"""
        c = _container()
        sol = _StubSolution(container=c, placements=[_plc("p1", "A", 2.0, 0.0, 0.0)])
        sol.telemetry.geometry_qa = _clean_qa()
        sol.telemetry.cavity_diagnostics = [
            {"box": (0, 0, 0, 1, 1, 1), "volume": 1.0, "exclusion_category": None},
        ]
        rep = evaluate_delivery(sol, [_sku(req=1)], c)
        assert rep["verdict"] == "REJECT" and "DG-012" in rep["blocked_by"], rep

    def test_policy_file_loads(self):
        """配置文件可加载且覆盖默认策略。"""
        pol = load_policy()
        assert "DG-001" in pol["rules"] and pol["rules"]["DG-001"]["severity"] == "BLOCK"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
