"""朝向策略执行回归测试（求解器与独立验证器语义一致）。

背景缺陷：_get_permitted_orientations 对 upright 朝向无条件放行，忽略
allow_upright=False；且"无合法朝向"时静默回退为全部朝向。结果：声明
"仅平放(flat_only)"的 SKU 被立放，独立验证器判 20 项 FORBIDDEN_ORIENTATION —
"能算出来但交付即违规"。本测试钉住修复。
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in (__import__("sys").path):
    __import__("sys").path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.solver.unified_solver import UnifiedSolver

CONTAINER = {"usable": {"L": 8.0, "W": 2.4, "H": 2.6}}


def _tensor(raw_sku):
    cargo = InputAdapter.parse_cargo_list([raw_sku])
    solver = UnifiedSolver(InputAdapter.parse_container(CONTAINER))
    return solver, solver._convert_cargo_skus_to_tensors(cargo)[0]


class TestOrientationPolicyEnforcement:
    def test_flat_only_excludes_upright(self):
        """flat_only：允许朝向集合中不得出现 upright。"""
        solver, t = _tensor({"sku": "F", "name": "仅平放", "w": 1.0, "d": 0.8, "h": 0.3,
                             "weight": 10, "quantity": 5, "allowedOrientation": "flat_only"})
        oris = solver._get_permitted_orientations(t)
        assert oris, "flat_only 应至少有一个平放朝向"
        assert all(not o.is_upright for o in oris), [(o.name, o.is_upright) for o in oris]

    def test_upright_only_excludes_flat(self):
        """默认立放：允许朝向集合中不得出现平放。"""
        solver, t = _tensor({"sku": "U", "name": "仅立放", "w": 1.0, "d": 0.8, "h": 0.3,
                             "weight": 10, "quantity": 5})
        oris = solver._get_permitted_orientations(t)
        assert oris and all(o.is_upright for o in oris), [(o.name, o.is_upright) for o in oris]

    def test_flat_only_solution_is_valid(self):
        """flat_only SKU 求解后独立验证器必须 0 违规（此前 20 项 FORBIDDEN_ORIENTATION）。"""
        container = InputAdapter.parse_container(CONTAINER)
        cargo = InputAdapter.parse_cargo_list([
            {"sku": "F", "name": "仅平放", "w": 1.0, "d": 0.8, "h": 0.3, "weight": 10,
             "quantity": 20, "allowedOrientation": "flat_only"},
        ])
        sol = UnifiedSolver(container).solve(cargo)
        assert sol.placed_count > 0
        assert not sol.validation_result.violations, [v.message for v in sol.validation_result.violations[:3]]
        h = min(p.orientation.dz for p in sol.placements)
        assert all(abs(p.orientation.dz - h) < 1e-6 for p in sol.placements), "存在非平放箱子"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
