"""开门倾覆安全（door-open stability）回归测试。

背景：既有门禁把"柜门提供前向支承"作为豁免，门面 2.5m 高、8cm 厚的薄板墙
在开门后 SF=2·dx/H≈0.06，会整列前倾。本测试钉住：
1) 柜门关闭时豁免仍生效（不改变既有语义）；
2) door_open=True 时门面薄箱必须自身 SF≥1.5 或由前方货箱支承；
3) geometry_qa 的门面整列 SF 审计口径（SF=2·dx/H，H 为同列堆叠总高）。

被谁调用：pytest 测试收集器（tests/ 目录）。
"""

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in (__import__("sys").path):
    __import__("sys").path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.diagnostics.geometry_qa import compute_geometry_qa
from backend.solver_v2.validation.constraint_kernel import lateral_stable, tipping_safe


def _cand(x, dx=0.08, dy=0.553, dz=0.355, y=0.0, z=0.0):
    return {"sku_id": "P", "x": x, "y": y, "z": z, "dx": dx, "dy": dy, "dz": dz,
            "weight_kg": 8.0, "orientation": "UPRIGHT_ROTATED"}


class TestDoorOpenTipping:
    def test_door_face_exemption_only_when_door_closed(self):
        """同一门面薄箱：关门时靠柜门放行；开门时 SF=0.45 必须拒绝。"""
        cand = _cand(11.912)
        assert tipping_safe(cand, [], 12.032) is True
        assert tipping_safe(cand, [], 12.032, door_open=True) is False

    def test_intrinsic_stable_box_allowed_door_open(self):
        """自身 SF≥1.5 的箱（dx=0.488, dz=0.08）开门时仍可放门面。"""
        cand = _cand(11.504, dx=0.488, dy=0.336, dz=0.08)
        assert tipping_safe(cand, [], 12.032, door_open=True) is True

    def test_forward_support_allowed_door_open(self):
        """门面箱若被前方同层货箱顶住，开门状态也可放行。"""
        cand = _cand(1.0, dx=0.08, dz=0.5, y=0.0, z=0.0)
        front = _cand(1.08, dx=0.5, dz=0.5, y=0.0, z=0.0)
        assert tipping_safe(cand, [front], 2.0, door_open=True) is True

    def test_lateral_door_support_only_when_length_given(self):
        """运输状态（柜门关闭）门面提供 +X 侧支承；不传柜长则按无支承处理。"""
        cand = _cand(11.912, dx=0.08, dy=0.553, dz=0.355, z=0.5)
        back = _cand(11.832, dx=0.08, dy=0.553, dz=0.355, z=0.5)
        assert lateral_stable(cand, [back], 2.352, 12.032) is True
        assert lateral_stable(cand, [back], 2.352) is False


class TestDoorOpenAudit:
    def test_door_face_column_sf(self):
        """3 层 0.5m 高、0.2m 深的门面列：H=1.5, D=0.2 → SF=0.267。"""
        container = InputAdapter.parse_container({"usable": {"L": 2.0, "W": 1.0, "H": 2.0}})
        placements = [
            {"sku_id": "A", "x": 1.8, "y": 0.0, "z": 0.0, "dx": 0.2, "dy": 1.0, "dz": 0.5},
            {"sku_id": "A", "x": 1.8, "y": 0.0, "z": 0.5, "dx": 0.2, "dy": 1.0, "dz": 0.5},
            {"sku_id": "A", "x": 1.8, "y": 0.0, "z": 1.0, "dx": 0.2, "dy": 1.0, "dz": 0.5},
        ]
        qa = compute_geometry_qa(container, placements, cavity_diagnostics=[])
        door = qa["door_open"]
        assert door["column_count"] == 1
        assert door["unsafe_columns"] == 1
        assert door["min_sf"] == pytest.approx(2 * 0.2 / 1.5, abs=0.01)
        assert door["at_risk_volume_m3"] == pytest.approx(0.3, abs=0.01)

    def test_no_door_face_columns_when_load_short(self):
        """货堆未到门端（距离 >0.65m）时不做开门倾覆判定。"""
        container = InputAdapter.parse_container({"usable": {"L": 6.0, "W": 2.0, "H": 2.0}})
        placements = [
            {"sku_id": "A", "x": 2.0, "y": 0.0, "z": 0.0, "dx": 0.5, "dy": 1.0, "dz": 0.5},
        ]
        qa = compute_geometry_qa(container, placements, cavity_diagnostics=[])
        assert qa["door_open"]["column_count"] == 0
        assert qa["door_open"]["min_sf"] is None


class TestDoorStepMode:
    def test_door_step_rejects_tall_thin_face_column(self):
        """门端台阶模式：门面薄板列 SF<1.5 被拒；关闭时靠柜门豁免放行。"""
        from backend.solver_v2.solver.unified_solver import UnifiedSolver
        container = InputAdapter.parse_container(
            {"usable": {"L": 12.032, "W": 2.352, "H": 2.698}})
        solver = UnifiedSolver(container)
        cand = _cand(11.912, dx=0.08, dy=0.553, dz=0.355)
        solver._door_step_depth = 0.0
        assert solver._is_placement_tipping_safe(cand, []) is True
        solver._door_step_depth = 0.20
        assert solver._is_placement_tipping_safe(cand, []) is False

    def test_door_step_allows_intrinsically_stable_box(self):
        """门端台阶模式不误杀自身 SF≥1.5 的门面箱（如平放板 dx=0.488/dz=0.08）。"""
        from backend.solver_v2.solver.unified_solver import UnifiedSolver
        container = InputAdapter.parse_container(
            {"usable": {"L": 12.032, "W": 2.352, "H": 2.698}})
        solver = UnifiedSolver(container)
        solver._door_step_depth = 0.20
        cand = _cand(11.504, dx=0.488, dy=0.336, dz=0.08)
        assert solver._is_placement_tipping_safe(cand, []) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
