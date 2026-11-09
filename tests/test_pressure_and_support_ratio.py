"""表面压强与每 SKU 最小支撑比约束回归测试。

背景（约束接线审计）：maxPressureKgM2 与 minSupportRatio 此前只被适配器解析，
求解器完全未使用——用户设置了却不生效。本测试钉住两项接线。
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in (__import__("sys").path):
    __import__("sys").path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.solver.unified_solver import UnifiedSolver

CONTAINER = {"usable": {"L": 3.0, "W": 3.0, "H": 3.0}}


def _solver(cargo_raw):
    container = InputAdapter.parse_container(CONTAINER)
    cargo = InputAdapter.parse_cargo_list(cargo_raw)
    solver = UnifiedSolver(container)
    tensors = solver._convert_cargo_skus_to_tensors(cargo)
    solver._sku_tensor_map = {t.sku_id: t for t in tensors}
    solver._current_rejection_counts = {}
    solver._has_any_bearing_constraints = False
    solver._has_door_skus = False
    solver._has_flat_cover_skus = False
    solver._zone_enforcement = "soft"
    return solver, {t.sku_id: t for t in tensors}


def _box(sku, x, y, z, dx, dy, dz, w=10.0):
    return {"sku_id": sku, "x": x, "y": y, "z": z, "dx": dx, "dy": dy, "dz": dz,
            "weight_kg": w, "orientation": "UPRIGHT_NORMAL"}


class TestPressureLimit:
    def test_pressure_limit_enforced(self):
        """小底面积重件压在大底面低压强板上 → 拒绝（载荷/接触面积 换算压强）。"""
        solver, tensors = _solver([
            {"sku": "WEAK", "name": "低压强板", "w": 1.0, "d": 1.0, "h": 0.4, "weight": 10,
             "quantity": 2, "maxPressureKgM2": 50},
            {"sku": "HEAVY", "name": "重小件", "w": 0.3, "d": 0.3, "h": 0.3, "weight": 20, "quantity": 2},
        ])
        placements = [_box("WEAK", 0.0, 0.0, 0.0, 1.0, 1.0, 0.4)]
        # 20kg / 0.09m² = 222 kg/m² > 50 → 应拒绝
        cand = _box("HEAVY", 0.3, 0.3, 0.4, 0.3, 0.3, 0.3, w=20.0)
        assert solver._check_placement_constraints(cand, placements) is False
        assert solver._current_rejection_counts.get("PRESSURE_LIMIT_EXCEEDED", 0) >= 1

    def test_pressure_within_limit_allowed(self):
        """同底板放轻件（10kg/0.09=111>50 仍超）→ 改用大底面轻件应通过。"""
        solver, _ = _solver([
            {"sku": "WEAK", "name": "低压强板", "w": 1.0, "d": 1.0, "h": 0.4, "weight": 10,
             "quantity": 2, "maxPressureKgM2": 50},
            {"sku": "LIGHT", "name": "大底轻件", "w": 0.5, "d": 0.5, "h": 0.3, "weight": 10, "quantity": 2},
        ])
        placements = [_box("WEAK", 0.0, 0.0, 0.0, 1.0, 1.0, 0.4)]
        cand = _box("LIGHT", 0.2, 0.2, 0.4, 0.5, 0.5, 0.3, w=10.0)  # 10/0.25 = 40 < 50
        assert solver._check_placement_constraints(cand, placements) is True


class TestMinSupportRatio:
    def test_support_ratio_wiring(self):
        """张量必须携带 sku.stacking_policy.min_support_ratio。"""
        _, tensors = _solver([{"sku": "P", "name": "板", "w": 1.0, "d": 0.8, "h": 0.3,
                               "weight": 5, "quantity": 5, "minSupportRatio": 0.95}])
        assert abs(getattr(tensors["P"], "min_support_ratio", 0) - 0.95) < 1e-9

    def test_ratio_095_rejects_075_support(self):
        """支撑率 0.75 的候选：默认 0.70 放行，声明 0.95 时拒绝。"""
        # 0.70（默认）
        solver_lo, _ = _solver([{"sku": "P", "name": "板", "w": 1.0, "d": 1.0, "h": 0.5,
                                 "weight": 5, "quantity": 2}])
        solver_lo._check_cog_projection = lambda cand, pls: True  # 隔离 CoG 投影，聚焦面积比
        placements = [_box("BASE", 0.0, 0.0, 0.0, 1.0, 1.0, 0.5)]
        cand = _box("P", 0.25, 0.0, 0.5, 1.0, 1.0, 0.5)  # 支撑 0.75
        assert solver_lo._has_sufficient_support(cand, placements) is True

        # 0.95 要求
        solver_hi, _ = _solver([{"sku": "P", "name": "板", "w": 1.0, "d": 1.0, "h": 0.5,
                                 "weight": 5, "quantity": 2, "minSupportRatio": 0.95}])
        solver_hi._check_cog_projection = lambda cand, pls: True
        assert solver_hi._has_sufficient_support(cand, placements) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
