"""多点卸货（Multi-Stop）模块测试。

业务规则：先卸的货必须靠门（后装），后卸的货在柜内深处（先装）。
实现：按站序划分纵深区段 + 门禁硬约束 + 按站序降序装载。
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in (__import__("sys").path):
    __import__("sys").path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.loading.multistop import plan_stop_regions, loading_order_by_stop
from backend.solver_v2.solver.unified_solver import UnifiedSolver
from backend.solver_v2.validation.config_precheck import precheck_manifest

CONTAINER = {"usable": {"L": 8.0, "W": 2.4, "H": 2.6}, "maxPayloadTons": 28.6}
CARGO = [
    {"sku": "S1-A", "name": "一站货", "w": 0.8, "d": 0.6, "h": 0.5, "weight": 15, "quantity": 12, "unloadStop": 1},
    {"sku": "S2-A", "name": "二站货", "w": 0.8, "d": 0.6, "h": 0.5, "weight": 15, "quantity": 20, "unloadStop": 2},
]


class TestMultistopPlanning:
    def test_regions_ordered_deepest_end_first(self):
        """终点站（站序大）在柜尾，第一站在门端。"""
        cargo = InputAdapter.parse_cargo_list(CARGO)
        regions, errors = plan_stop_regions(cargo, InputAdapter.parse_container(CONTAINER))
        assert not errors
        assert regions[2].x_start < regions[1].x_start
        assert regions[2].x_end <= regions[1].x_start + 1e-6
        assert regions[1].x_end <= 8.0

    def test_loading_order_is_reverse_of_unloading(self):
        """装载顺序 = 站序降序（终点站先装）。"""
        cargo = InputAdapter.parse_cargo_list(CARGO)
        order = loading_order_by_stop(cargo)
        assert order.index("S2-A") < order.index("S1-A")

    def test_e2e_region_hard_constraint(self):
        """端到端：一站货在门侧区段、二站货在柜尾区段，且零违规。"""
        container = InputAdapter.parse_container(CONTAINER)
        cargo = InputAdapter.parse_cargo_list(CARGO)
        solver = UnifiedSolver(container)
        sol = solver.solve(cargo)
        assert sol.placed_count == 32
        assert not sol.validation_result.violations

        regions = getattr(solver, "_stop_regions", {})
        xs = {}
        for p in sol.placements:
            xs.setdefault(p.sku_id, []).append(p.position.x)
        s1 = xs["S1-A"]; s2 = xs["S2-A"]
        assert min(s1) >= regions[1].x_start - 1e-4, "一站货必须在门侧区段内"
        assert max(s2) + 0.8 <= regions[2].x_end + 1e-4, "二站货必须在柜尾区段内"
        # 拒绝原因栈应出现区段违规（证明门禁在起作用）
        assert sol.telemetry.candidates_rejected_by_reason.get("MULTISTOP_REGION_VIOLATION", 0) > 0

    def test_precheck_partial_stops_warns(self):
        cargo = InputAdapter.parse_cargo_list([
            {"sku": "A", "name": "A", "w": 0.8, "d": 0.6, "h": 0.5, "weight": 10, "quantity": 5, "unloadStop": 1},
            {"sku": "B", "name": "B", "w": 0.8, "d": 0.6, "h": 0.5, "weight": 10, "quantity": 5},
        ])
        r = precheck_manifest(cargo, InputAdapter.parse_container(CONTAINER))
        assert any(w["code"] == "UNLOAD_STOP_PARTIAL" for w in r["warnings"])

    def test_precheck_single_stop_warns(self):
        cargo = InputAdapter.parse_cargo_list([
            {"sku": "A", "name": "A", "w": 0.8, "d": 0.6, "h": 0.5, "weight": 10, "quantity": 5, "unloadStop": 1},
        ])
        r = precheck_manifest(cargo, InputAdapter.parse_container(CONTAINER))
        assert any(w["code"] == "UNLOAD_STOP_SINGLE" for w in r["warnings"])

    def test_precheck_multistop_capacity_error(self):
        """某站货量明显超过区段容量时，预检必须报错而不是让求解器静默饥饿。"""
        cargo = InputAdapter.parse_cargo_list([
            {"sku": "S1-HUGE", "name": "一站巨量", "w": 0.8, "d": 0.6, "h": 0.5,
             "weight": 10, "quantity": 1000, "unloadStop": 1},
            {"sku": "S2-BOX", "name": "二站", "w": 0.8, "d": 0.6, "h": 0.5,
             "weight": 10, "quantity": 5, "unloadStop": 2},
        ])
        r = precheck_manifest(cargo, InputAdapter.parse_container(CONTAINER))
        assert any(e["code"] == "MULTISTOP_UNSATISFIABLE" for e in r["errors"]), r

    def test_no_stop_means_no_regions(self):
        """未设置站序时行为完全不变（零影响）。"""
        cargo = InputAdapter.parse_cargo_list([
            {"sku": "A", "name": "A", "w": 0.8, "d": 0.6, "h": 0.5, "weight": 10, "quantity": 5},
        ])
        regions, errors = plan_stop_regions(cargo, InputAdapter.parse_container(CONTAINER))
        assert regions == {} and not errors

    def test_three_stops_with_door_seal_no_starvation(self):
        """3 站 + 第 1 站封门薄板：全部装完、区段合规、封门件不被饿死。"""
        container = InputAdapter.parse_container(
            {"usable": {"L": 8.0, "W": 2.4, "H": 2.6}, "maxPayloadTons": 28.6})
        cargo = InputAdapter.parse_cargo_list([
            {"sku": "S1-DOOR", "name": "一站封门板", "w": 0.55, "d": 0.08, "h": 0.35,
             "weight": 3, "quantity": 30, "requirement": "封柜门",
             "allowDoorZone": True, "unloadStop": 1},
            {"sku": "S2-BOX", "name": "二站货", "w": 0.5, "d": 0.5, "h": 0.5,
             "weight": 8, "quantity": 20, "unloadStop": 2},
            {"sku": "S3-BOX", "name": "三站货", "w": 0.5, "d": 0.5, "h": 0.5,
             "weight": 8, "quantity": 20, "unloadStop": 3},
        ])
        solver = UnifiedSolver(container)
        sol = solver.solve(cargo, time_budget=8, options={
            "door_seal_confine": True, "door_step_depth": 0.25})
        assert sol.placed_count == 70
        assert not sol.validation_result.violations

        regions = getattr(solver, "_stop_regions", {})
        assert regions[3].x_start == pytest.approx(0.0, abs=1e-6)
        assert regions[3].x_end <= regions[2].x_start + 1e-6
        assert regions[2].x_end <= regions[1].x_start + 1e-6
        assert regions[1].x_end == pytest.approx(8.0 - 0.04, abs=1e-4)

        for p in sol.placements:
            stop = {"S1-DOOR": 1, "S2-BOX": 2, "S3-BOX": 3}[p.sku_id]
            assert p.position.x >= regions[stop].x_start - 1e-4
            assert p.position.x + p.orientation.dx <= regions[stop].x_end + 1e-4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
