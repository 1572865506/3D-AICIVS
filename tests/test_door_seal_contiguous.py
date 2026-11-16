"""低装载时封柜门货不应跳过中间空档直接贴到门区起点。

回归场景：其他货物只有 30 箱（只占柜尾 1m），封门板 40 箱。
旧行为把封门板直接放到门区预留线（约 11.4m），中间留出 10m 空档；
新行为应让封门板从当前前沿连续摆放（离中间货不超过一个墙深）。
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.solver.unified_solver import UnifiedSolver

CONTAINER = {"usable": {"L": 12.032, "W": 2.352, "H": 2.698}, "maxPayloadTons": 28.6}
CARGO = [
    {"sku": "MID", "name": "中间货", "w": 0.5, "d": 0.5, "h": 0.5,
     "weight": 5, "quantity": 30, "requirement": "放中间"},
    {"sku": "DOOR", "name": "封门板", "w": 0.553, "d": 0.08, "h": 0.355,
     "weight": 8, "quantity": 40, "requirement": "封柜门", "allowDoorZone": True},
]


def _solve(options):
    container = InputAdapter.parse_container(CONTAINER)
    cargo = InputAdapter.parse_cargo_list(CARGO)
    solver = UnifiedSolver(container)
    sol = solver.solve(cargo, time_budget=8, options=options)
    placed = {}
    for p in sol.placements:
        placed.setdefault(p.sku_id, []).append(
            (p.position.x, p.position.x + p.orientation.dx))
    return solver, sol, placed


class TestLowFillDoorContiguous:
    @pytest.mark.parametrize("options", [
        {"door_seal_confine": True, "door_step_depth": 0.25},
        {"door_seal_confine": True, "door_step_depth": 0.0},
    ])
    def test_door_panels_follow_middle_cargo(self, options):
        solver, sol, placed = _solve(options)
        assert sol.placed_count == 70
        assert not sol.validation_result.violations
        mid_max = max(x1 for _, x1 in placed["MID"])
        door_min = min(x0 for x0, _ in placed["DOOR"])
        door_max = max(x1 for _, x1 in placed["DOOR"])
        # 封门板应紧接中间货，而不是跳到门区预留线（约 11.4m）
        assert door_min <= mid_max + 0.8, (mid_max, door_min)
        assert door_max < 5.0, door_max

    def test_door_contiguous_mode_not_used_when_cargo_reaches_door(self):
        """货量足够填到门区时，仍按门区预留段摆放（不能把所有货都变成连续模式）。"""
        container = InputAdapter.parse_container(CONTAINER)
        cargo = InputAdapter.parse_cargo_list([
            {"sku": "MID", "name": "中间货", "w": 0.5, "d": 0.5, "h": 0.5,
             "weight": 5, "quantity": 1400, "requirement": "放中间"},
            {"sku": "DOOR", "name": "封门板", "w": 0.553, "d": 0.08, "h": 0.355,
             "weight": 8, "quantity": 120, "requirement": "封柜门", "allowDoorZone": True},
        ])
        solver = UnifiedSolver(container)
        sol = solver.solve(cargo, time_budget=15, options={
            "door_seal_confine": True, "door_step_depth": 0.25})
        door = [p for p in sol.placements if p.sku_id == "DOOR"]
        assert door
        # 门区模式下封门件必须落在门区预留段内
        assert min(p.position.x + p.orientation.dx for p in door) >= 10.0
