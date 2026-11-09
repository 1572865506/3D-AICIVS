"""平放顶层策略（flat_only_on_top）回归测试。

业务规则（15-SKU 真实货单 SKU-14）：薄板允许平放，但
1) 仅允许作为顶层覆盖层（不得落地）；
2) 同款平放最多 2 层（maxFlatLayers）；
3) 平放覆盖层上方不得再压其他货物。

被谁调用：pytest 测试收集器（tests/ 目录）。
"""

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in (__import__("sys").path):
    __import__("sys").path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.diagnostics.geometry_qa import compute_geometry_qa
from backend.solver_v2.solver.unified_solver import UnifiedSolver

CONTAINER = {"usable": {"L": 3.0, "W": 2.0, "H": 3.0}}
# 薄板：立放高 0.336、平放高 0.08（与 SKU-14 同形）
PANEL = {"sku": "PANEL", "name": "薄板", "w": 0.5, "d": 0.08, "h": 0.336, "weight": 2.0,
         "quantity": 50, "allowFlat": True, "maxFlatLayers": 2, "flatOnlyOnTop": True}
BASE = {"sku": "BASE", "name": "底座箱", "w": 0.6, "d": 0.6, "h": 0.5, "weight": 20.0, "quantity": 10}


def _solver_and_tensors(cargo_raw):
    container = InputAdapter.parse_container(CONTAINER)
    cargo = InputAdapter.parse_cargo_list(cargo_raw)
    solver = UnifiedSolver(container)
    tensors = solver._convert_cargo_skus_to_tensors(cargo)
    solver._sku_tensor_map = {t.sku_id: t for t in tensors}
    solver._current_rejection_counts = {}
    # 第6条"覆盖层上方禁压"按货单是否含 flat_only_on_top SKU 启用
    solver._has_flat_cover_skus = any(getattr(t, "flat_only_on_top", False) for t in tensors)
    return container, solver, tensors


def _plc(sku, x, y, z, dx, dy, dz, orient):
    return {"sku_id": sku, "x": x, "y": y, "z": z, "dx": dx, "dy": dy, "dz": dz,
            "weight_kg": 2.0, "orientation": orient}


class TestFlatOnTopPolicy:
    def test_flat_rejected_on_floor(self):
        """平放不得落地：z=0 的平放候选必须被拒。"""
        _, solver, _ = _solver_and_tensors([PANEL])
        cand = _plc("PANEL", 0.0, 0.0, 0.0, 0.5, 0.336, 0.08, "FLAT_NORMAL")
        assert solver._check_placement_constraints(cand, []) is False
        assert solver._current_rejection_counts.get("FLAT_ON_TOP_REQUIRES_SUPPORT", 0) >= 1

    def test_flat_allowed_on_top_with_layer_limit(self):
        """顶层平放：第 1、2 层可行，第 3 层被拒。"""
        _, solver, _ = _solver_and_tensors([PANEL, BASE])
        base = _plc("BASE", 0.0, 0.0, 0.0, 0.6, 0.6, 0.5, "UPRIGHT_NORMAL")
        placements = [base]
        f1 = _plc("PANEL", 0.0, 0.0, 0.5, 0.5, 0.336, 0.08, "FLAT_NORMAL")
        assert solver._check_placement_constraints(f1, placements) is True
        placements.append(f1)
        f2 = _plc("PANEL", 0.0, 0.0, 0.58, 0.5, 0.336, 0.08, "FLAT_NORMAL")
        assert solver._check_placement_constraints(f2, placements) is True
        placements.append(f2)
        f3 = _plc("PANEL", 0.0, 0.0, 0.66, 0.5, 0.336, 0.08, "FLAT_NORMAL")
        assert solver._check_placement_constraints(f3, placements) is False
        assert solver._current_rejection_counts.get("FLAT_LAYERS_EXCEEDED", 0) >= 1

    def test_no_cargo_stacked_above_flat_cover(self):
        """平放覆盖层上方禁止再压其他 SKU。"""
        _, solver, _ = _solver_and_tensors([PANEL, BASE])
        placements = [
            _plc("BASE", 0.0, 0.0, 0.0, 0.6, 0.6, 0.5, "UPRIGHT_NORMAL"),
            _plc("PANEL", 0.0, 0.0, 0.5, 0.5, 0.336, 0.08, "FLAT_NORMAL"),
        ]
        other = _plc("BASE", 0.0, 0.0, 0.58, 0.6, 0.6, 0.5, "UPRIGHT_NORMAL")
        assert solver._check_placement_constraints(other, placements) is False
        assert solver._current_rejection_counts.get("COVER_LAYER_TOP_BLOCKED", 0) >= 1

    def test_cover_layer_not_counted_as_island(self):
        """平放覆盖层不计入孤立箱，但单独统计 flat_cover_count。"""
        container, _, _ = _solver_and_tensors([PANEL, BASE])
        placements = [
            _plc("BASE", 0.0, 0.0, 0.0, 0.6, 0.6, 0.5, "UPRIGHT_NORMAL"),
            _plc("PANEL", 0.0, 0.0, 0.5, 0.5, 0.336, 0.08, "FLAT_NORMAL"),
        ]
        qa = compute_geometry_qa(container, placements, cavity_diagnostics=[])
        assert qa["support"]["flat_cover_count"] == 1
        assert qa["islands"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
