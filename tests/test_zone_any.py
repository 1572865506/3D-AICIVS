"""“随意放置”（不限纵向区间）语义测试。

钉住：
1. 解析层把“随意/任意位置/无要求”识别为 ZoneType.ANY，而非默认 MIDDLE；
2. 求解器把 ANY 映射为 UniversalZone.FLEXIBLE，不触发区域硬约束；
3. 只有 ANY 货单时 zone_enforcement 保持 soft，且能正常装载不饥饿。
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter, InputNormalizer
from backend.solver_v2.domain.models import (
    PackingRole, UniversalZone, ZoneType)
from backend.solver_v2.solver.unified_solver import UnifiedSolver

CONTAINER = {"usable": {"L": 4.0, "W": 2.35, "H": 2.69}, "maxPayloadTons": 28.6}


def _cargo(requirement):
    return InputAdapter.parse_cargo_list([{
        "sku": "ANY-01", "name": "任意位置货", "w": 0.5, "d": 0.5, "h": 0.5,
        "weight": 5, "quantity": 20, "requirement": requirement,
    }])


class TestAnyZoneParsing:
    @pytest.mark.parametrize("text", ["随意放置", "任意位置", "不限位置", "无要求", "自由摆放"])
    def test_any_keywords_map_to_any(self, text):
        zone, roles = InputNormalizer.parse_zone_and_roles(text)
        assert zone == ZoneType.ANY, (text, zone)
        assert PackingRole.MAIN_WALL in roles

    def test_explicit_zones_still_win(self):
        assert InputNormalizer.parse_zone_and_roles("放柜子最里面")[0] == ZoneType.REAR
        assert InputNormalizer.parse_zone_and_roles("封柜门")[0] == ZoneType.DOOR
        assert InputNormalizer.parse_zone_and_roles("放中间")[0] == ZoneType.MIDDLE

    def test_empty_requirement_keeps_legacy_none(self):
        assert InputNormalizer.parse_zone_and_roles("")[0] is None


class TestAnyZoneSolver:
    def test_any_maps_to_flexible_tensor(self):
        container = InputAdapter.parse_container(CONTAINER)
        cargo = _cargo("随意放置")
        assert cargo[0].target_zone == ZoneType.ANY
        tensors = UnifiedSolver(container)._convert_cargo_skus_to_tensors(cargo)
        assert tensors[0].zone_preference == UniversalZone.FLEXIBLE

    def test_any_only_manifest_stays_soft_and_places(self):
        container = InputAdapter.parse_container(CONTAINER)
        cargo = _cargo("随意放置")
        solver = UnifiedSolver(container)
        sol = solver.solve(cargo, time_budget=5)
        assert solver._zone_enforcement == "soft"
        assert sol.placed_count == 20
        assert not sol.validation_result.violations
        assert not sol.telemetry.candidates_rejected_by_reason.get("ZONE_MIDDLE_IN_REAR")
        assert not sol.telemetry.candidates_rejected_by_reason.get("ZONE_MIDDLE_IN_DOOR")

    def test_explicit_middle_still_strict_when_mixed(self):
        container = InputAdapter.parse_container(CONTAINER)
        cargo = InputAdapter.parse_cargo_list([
            {"sku": "MID", "name": "中间货", "w": 0.5, "d": 0.5, "h": 0.5,
             "weight": 5, "quantity": 10, "requirement": "放中间"},
            {"sku": "ANY", "name": "任意货", "w": 0.5, "d": 0.5, "h": 0.5,
             "weight": 5, "quantity": 10, "requirement": "随意放置"},
        ])
        solver = UnifiedSolver(container)
        sol = solver.solve(cargo, time_budget=5)
        assert solver._zone_enforcement == "strict"
        assert sol.placed_count == 20
        assert not sol.validation_result.violations
