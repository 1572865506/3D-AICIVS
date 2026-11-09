"""适配器解析 → 求解器消费 全链路接线测试（本轮审计发现的两处缺口）。

1) orientationRules（显式朝向规则）：求解器此前完全不读，与验证器按 region
   校验的语义分裂；现按"朝向家族 + context(region)"共同裁决。
2) topFillPolicy.enabled：显式关闭时该 SKU 不得进入 TOP_FILL 上下文
   （未提供时保持默认 AUTO 行为不变）。
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in (__import__("sys").path):
    __import__("sys").path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.solver.unified_solver import UnifiedSolver

CONTAINER = {"usable": {"L": 4.0, "W": 2.4, "H": 2.6}}


def _solver(cargo_raw):
    container = InputAdapter.parse_container(CONTAINER)
    cargo = InputAdapter.parse_cargo_list(cargo_raw)
    solver = UnifiedSolver(container)
    tensors = solver._convert_cargo_skus_to_tensors(cargo)
    solver._sku_tensor_map = {t.sku_id: t for t in tensors}
    solver._current_rejection_counts = {}
    solver._has_door_skus = False
    solver._has_any_bearing_constraints = False
    solver._has_flat_cover_skus = False
    solver._zone_enforcement = "soft"
    return solver, tensors[0]


def _cand(ctx, orientation="FLAT_NORMAL"):
    return {"sku_id": "P", "x": 0.5, "y": 0.5, "z": 0.5, "dx": 1.0, "dy": 0.3, "dz": 0.8,
            "weight_kg": 8.0, "orientation": orientation, "context": ctx}


class TestExplicitOrientationRules:
    RULE_CARGO = {"sku": "P", "name": "板", "w": 1.0, "d": 0.8, "h": 0.3, "weight": 8, "quantity": 6,
                  "cargoProfile": {"orientationPolicy": {"rules": [
                      {"orientation": "FLAT", "allowedRegions": ["TOP_FILL"]}]}}}

    def test_flat_rejected_in_main_wall(self):
        solver, _ = _solver([self.RULE_CARGO])
        assert solver._check_placement_constraints(_cand("MAIN_WALL"), []) is False
        assert solver._current_rejection_counts.get("ORIENTATION_NOT_ALLOWED_IN_CONTEXT", 0) >= 1

    def test_flat_allowed_in_top_fill(self):
        solver, _ = _solver([self.RULE_CARGO])
        assert solver._check_placement_constraints(_cand("TOP_FILL"), []) is True

    def test_orientation_filter_follows_rules(self):
        """存在显式规则时，允许朝向集合按规则家族推导（FLAT only）。"""
        solver, t = _solver([self.RULE_CARGO])
        oris = solver._get_permitted_orientations(t)
        assert oris and all(o.is_flat for o in oris), [(o.name, o.is_upright) for o in oris]


class TestTopFillSwitch:
    def _cargo(self, enabled):
        return {"sku": "Q", "name": "箱", "w": 0.5, "d": 0.5, "h": 0.5, "weight": 10, "quantity": 4,
                "cargoProfile": {"topFillPolicy": {"enabled": enabled}}}

    def test_explicit_disable_blocks_top_fill(self):
        solver, _ = _solver([self._cargo(False)])
        cand = {"sku_id": "Q", "x": 0.5, "y": 0.5, "z": 0.5, "dx": 0.5, "dy": 0.5, "dz": 0.5,
                "weight_kg": 10.0, "orientation": "UPRIGHT_NORMAL", "context": "TOP_FILL"}
        assert solver._check_placement_constraints(cand, []) is False
        assert solver._current_rejection_counts.get("TOP_FILL_DISABLED", 0) >= 1

    def test_absent_policy_keeps_auto(self):
        """未提供 topFillPolicy 时保持默认（不拦截），避免误禁核心算法。"""
        solver, _ = _solver([{"sku": "Q", "name": "箱", "w": 0.5, "d": 0.5, "h": 0.5,
                              "weight": 10, "quantity": 4}])
        cand = {"sku_id": "Q", "x": 0.5, "y": 0.5, "z": 0.5, "dx": 0.5, "dy": 0.5, "dz": 0.5,
                "weight_kg": 10.0, "orientation": "UPRIGHT_NORMAL", "context": "TOP_FILL"}
        assert solver._check_placement_constraints(cand, []) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
