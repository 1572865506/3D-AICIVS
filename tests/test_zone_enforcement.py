"""区域约束执行（zone_enforcement）回归测试。

背景：区域要求（放柜子最里面/封柜门/放中间）此前只用于排序偏好，
门禁无任何硬约束 —— 实测"放中间"的 SKU 被放到柜尾 0.24m、门端 11.64m。
本测试钉住 strict 模式的语义：
1) MIDDLE 不得进入门区锁定线；
2) 货单存在 INNER 货物时，MIDDLE 不得占用后区（竞争占用）；无 INNER 时允许；
3) INNER 不得进入门区；
4) 弹性件豁免区域硬约束（填充物，业务已授权灵活）。

被谁调用：pytest 测试收集器（tests/ 目录）。
"""

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in (__import__("sys").path):
    __import__("sys").path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.solver.unified_solver import UnifiedSolver

CONTAINER = {"usable": {"L": 12.0, "W": 2.4, "H": 2.6}, "maxPayloadTons": 28.6}


def _setup(cargo_raw, zone_mode="strict", has_inner=None):
    container = InputAdapter.parse_container(CONTAINER)
    cargo = InputAdapter.parse_cargo_list(cargo_raw)
    solver = UnifiedSolver(container)
    tensors = solver._convert_cargo_skus_to_tensors(cargo)
    solver._sku_tensor_map = {t.sku_id: t for t in tensors}
    solver._current_rejection_counts = {}
    solver._zone_enforcement = zone_mode
    solver._actual_door_zone_len = 0.2
    if has_inner is None:
        has_inner = any(x.sku_id == "INNER" for x in cargo)
    solver._has_inner_skus = has_inner
    return container, solver, tensors


def _cand(sku, x, w=1.0):
    return {"sku_id": sku, "x": x, "y": 0.0, "z": 0.0, "dx": w, "dy": 0.8, "dz": 0.6,
            "weight_kg": 10.0, "orientation": "UPRIGHT_NORMAL"}


MID = {"sku": "MID", "name": "中间件", "w": 1.0, "d": 0.8, "h": 0.6, "weight": 10, "quantity": 5,
       "requirement": "放中间"}
INNER = {"sku": "INNER", "name": "最里面件", "w": 1.0, "d": 0.8, "h": 0.6, "weight": 10, "quantity": 5,
         "requirement": "放柜子最里面"}
ELAS = {"sku": "ELAS", "name": "弹性填充", "w": 1.0, "d": 0.8, "h": 0.6, "weight": 5, "quantity": 10,
        "requirement": "放中间; 可以减少点"}


class TestZoneEnforcement:
    def test_middle_blocked_from_door_zone(self):
        """MIDDLE 不得进入门区锁定线（x + dx > L - door_len）。"""
        _, solver, _ = _setup([MID, INNER])
        cand = _cand("MID", 11.5)  # 11.5+1.0 > 11.8
        assert solver._check_placement_constraints(cand, []) is False
        assert solver._current_rejection_counts.get("ZONE_MIDDLE_IN_DOOR", 0) >= 1

    def test_middle_blocked_from_rear_when_inner_present(self):
        """存在 INNER 货物时，MIDDLE 不得占用后区（竞争占用）。"""
        _, solver, _ = _setup([MID, INNER], has_inner=True)
        cand = _cand("MID", 0.2)  # 0.2 < rear_zone(1.0)
        assert solver._check_placement_constraints(cand, []) is False
        assert solver._current_rejection_counts.get("ZONE_MIDDLE_IN_REAR", 0) >= 1

    def test_middle_allowed_in_rear_when_no_inner(self):
        """无 INNER 货物时后区无人认领，MIDDLE 可用（避免无谓损失）。"""
        _, solver, _ = _setup([MID], has_inner=False)
        solver._zone_enforcement = "strict"
        cand = _cand("MID", 0.2)
        assert solver._check_placement_constraints(cand, []) is True

    def test_inner_blocked_from_door_zone(self):
        """INNER 不得进入门区。"""
        _, solver, _ = _setup([INNER])
        cand = _cand("INNER", 11.5)
        assert solver._check_placement_constraints(cand, []) is False
        assert solver._current_rejection_counts.get("ZONE_INNER_IN_DOOR", 0) >= 1

    def test_elastic_exempt_from_zone_gate(self):
        """弹性件豁免区域硬约束（可放后区）。"""
        _, solver, _ = _setup([ELAS, INNER], has_inner=True)
        cand = _cand("ELAS", 0.2)
        assert solver._check_placement_constraints(cand, []) is True

    def test_soft_mode_not_blocked(self):
        """soft 模式（未声明区域指令）不拦截，保持既有行为。"""
        _, solver, _ = _setup([MID], zone_mode="soft", has_inner=True)
        cand = _cand("MID", 0.2)
        assert solver._check_placement_constraints(cand, []) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
