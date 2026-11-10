"""方案质量评分卡（plan_quality）测试。

评分卡把"看得见但说不清"的观感问题量化：
墙体连续性 / 层平面度 / 同SKU聚集度 / 重心高度 / 门面平整度 / 碎片化指数。
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in (__import__("sys").path):
    __import__("sys").path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.diagnostics.geometry_qa import compute_geometry_qa


def _container():
    return InputAdapter.parse_container({"usable": {"L": 6.0, "W": 2.4, "H": 2.4}})


def _box(x, y, z, dx, dy, dz, sku="A"):
    return {"sku_id": sku, "x": x, "y": y, "z": z, "dx": dx, "dy": dy, "dz": dz,
            "weight_kg": 10.0, "orientation": "UPRIGHT_NORMAL", "placement_id": f"{sku}-{x}-{y}-{z}"}


class TestPlanQualityScorecard:
    def test_uniform_wall_scores_high_planarity(self):
        """同尺寸整齐码放（2 列 × 4 行 × 2 层）：层平面度与墙体连续性应高。"""
        pls = []
        for ix in range(2):
            for iy in range(4):
                for iz in range(2):
                    pls.append(_box(ix * 1.0, iy * 0.6, iz * 1.2, 1.0, 0.6, 1.2))
        qa = compute_geometry_qa(_container(), pls, cavity_diagnostics=[])
        pq = qa["plan_quality"]
        assert pq["components"]["layer_planarity_pct"] >= 90.0, pq["components"]
        assert pq["components"]["wall_continuity_pct"] >= 80.0, pq["components"]
        assert pq["grade"] in ("A", "B"), pq

    def test_scattered_heights_score_low_planarity(self):
        """顶面高度各自不同（无共享层平面）：层平面度应显著低于整齐码放。"""
        pls = []
        for i in range(8):
            # 每个箱体顶面都不相同（z 与 dz 同时递增）
            pls.append(_box(i * 0.7, 0.0, 0.10 * i, 0.6, 1.0, 0.25 + 0.03 * i))
        qa = compute_geometry_qa(_container(), pls, cavity_diagnostics=[])
        pq = qa["plan_quality"]
        # 8 个不同顶面 → 最集中的 3 个平面最多覆盖约 3/8 面积
        assert pq["components"]["layer_planarity_pct"] <= 45.0, pq["components"]

    def test_score_bounds_and_components_present(self):
        pls = [_box(0, 0, 0, 1.0, 1.0, 1.0)]
        qa = compute_geometry_qa(_container(), pls, cavity_diagnostics=[])
        pq = qa["plan_quality"]
        assert 0.0 <= pq["score"] <= 100.0
        for key in ("wall_continuity_pct", "layer_planarity_pct", "sku_clustering_pct",
                    "cog_height_pct", "door_flatness_cv_pct", "fragmentation_pct"):
            assert key in pq["components"]

    def test_gate_rule_dg016_flags_low_planarity(self):
        """门禁 DG-016：层平面度过低应告警（WARN，不阻断）。"""
        from backend.solver_v2.api.adapter import InputAdapter as IA
        from backend.solver_v2.solver.unified_solver import UnifiedSolver
        from backend.solver_v2.validation.delivery_gate import evaluate_delivery

        container = IA.parse_container({"usable": {"L": 6.0, "W": 2.4, "H": 2.4}})
        cargo = IA.parse_cargo_list([
            {"sku": "A", "name": "A", "w": 1.0, "d": 0.8, "h": 0.3, "weight": 10, "quantity": 12},
            {"sku": "B", "name": "B", "w": 0.6, "d": 0.6, "h": 0.9, "weight": 10, "quantity": 12},
        ])
        sol = UnifiedSolver(container).solve(cargo)
        gate = evaluate_delivery(sol, cargo, container)
        ids = {c["id"]: c for c in gate["checks"]}
        assert "DG-016" in ids, "门禁缺少 DG-016"
        assert ids["DG-016"]["severity"] == "WARN"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
