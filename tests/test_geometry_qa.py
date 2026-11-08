"""几何观感体检（Geometry QA）回归测试。

钉住三件事：
1. 隐蔽空洞/天窗口径：已知几何下与手算一致（柱顶以下的洞 vs 顶面不齐）；
2. 支撑充分度：半悬空箱被正确识别；
3. 空腔体积守恒：诊断合计不得超过物理自由空间（防跨切片重复计数回归）。

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


def _dict(x, y, z, dx, dy, dz):
    return {"x": x, "y": y, "z": z, "dx": dx, "dy": dy, "dz": dz}


class TestGeometryQA:
    def test_hidden_vs_skyline_void(self):
        """相邻两列 2.0m / 1.0m：天窗洞 = 1.0m 高差部分，隐蔽洞 = 0。"""
        container = InputAdapter.parse_container({"usable": {"L": 2.0, "W": 1.0, "H": 2.0}})
        placements = [
            _dict(0.0, 0.0, 0.0, 1.0, 1.0, 2.0),  # 满高柱
            _dict(1.0, 0.0, 0.0, 1.0, 1.0, 1.0),  # 半高柱
        ]
        qa = compute_geometry_qa(container, placements, cavity_diagnostics=[])
        cav = qa["cavities"]
        # 半高柱上方 1.0×1.0×1.0 = 1.0 m³ 天窗洞；无隐蔽洞
        assert abs(cav["skyline_void_volume_m3"] - 1.0) < 0.11, cav
        assert cav["hidden_void_volume_m3"] < 0.11, cav
        # 实心块内部相邻列高差为 0，只有交界处存在 1.0m 落差
        assert qa["top_surface"]["adjacent_diff_median_m"] == 0.0, qa["top_surface"]
        assert qa["top_surface"]["adjacent_diff_max_m"] == pytest.approx(1.0, abs=0.01), qa["top_surface"]
        assert qa["top_surface"]["steep_step_ratio_pct"] > 0, qa["top_surface"]

    def test_partial_support_detected(self):
        """下半被支撑 50% 的箱：支撑比 0.5，计入低支撑与半悬空。"""
        container = InputAdapter.parse_container({"usable": {"L": 2.0, "W": 2.0, "H": 3.0}})
        placements = [
            _dict(0.0, 0.0, 0.0, 1.0, 1.0, 1.0),
            _dict(0.0, 0.0, 1.0, 2.0, 1.0, 1.0),  # 只有一半压在第一个箱上
        ]
        qa = compute_geometry_qa(container, placements, cavity_diagnostics=[])
        assert qa["support"]["low_support_count"] == 1, qa["support"]
        assert qa["support"]["partial_support_ratio_pct"] == 50.0, qa["support"]

    def test_cavity_volume_conserved_across_slices(self):
        """多切片场景：空腔诊断合计 <= 物理自由空间（防体积放大回归）。"""
        container = InputAdapter.parse_container({"usable": {"L": 4.0, "W": 2.0, "H": 2.0}})
        cargo = InputAdapter.parse_cargo_list([
            {"sku": "A", "name": "A", "w": 0.5, "d": 0.5, "h": 0.5, "weight": 5, "quantity": 8},
        ])
        solver = UnifiedSolver(container)
        tensors = solver._convert_cargo_skus_to_tensors(cargo)
        # 沿 x 方向间隔放置 4 个箱 → 多切片
        pls = [
            {"sku_id": "A", "x": 0.0, "y": 0.0, "z": 0.0, "dx": 0.5, "dy": 0.5, "dz": 0.5, "weight_kg": 5},
            {"sku_id": "A", "x": 1.0, "y": 0.0, "z": 0.0, "dx": 0.5, "dy": 0.5, "dz": 0.5, "weight_kg": 5},
            {"sku_id": "A", "x": 2.0, "y": 0.0, "z": 0.0, "dx": 0.5, "dy": 0.5, "dz": 0.5, "weight_kg": 5},
            {"sku_id": "A", "x": 3.0, "y": 0.0, "z": 0.0, "dx": 0.5, "dy": 0.5, "dz": 0.5, "weight_kg": 5},
        ]
        cavs = solver._compute_cavity_diagnostics(pls, tensors)
        total = sum(c["volume"] for c in cavs if c.get("box"))
        free = container.volume - 4 * (0.5 ** 3)
        assert total <= free * 1.02, f"空腔合计 {total:.2f} 超过物理自由 {free:.2f}（跨切片重复计数）"

    def test_solution_carries_geometry_qa(self):
        """求解结果必须携带 geometry_qa（供 API/前端消费），字段齐全。"""
        container = InputAdapter.parse_container({"usable": {"L": 6.0, "W": 2.352, "H": 2.5}})
        cargo = InputAdapter.parse_cargo_list([
            {"sku": "A", "name": "A", "w": 1.0, "d": 1.0, "h": 1.0, "weight": 20, "quantity": 20},
            {"sku": "B", "name": "B", "w": 0.6, "d": 0.5, "h": 0.4, "weight": 8, "quantity": 40},
        ])
        sol = UnifiedSolver(container).solve(cargo)
        qa = sol.telemetry.geometry_qa
        assert qa is not None and qa["verdict"] in ("GOOD", "FAIR", "POOR", "EMPTY")
        for key in ("bbox_void_ratio_pct", "top_surface", "support", "cavities", "islands"):
            assert key in qa
        assert "hidden_void_volume_m3" in qa["cavities"]
        assert "steep_step_ratio_pct" in qa["top_surface"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
