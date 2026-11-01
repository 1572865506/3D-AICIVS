"""禁后区（zone_policy.forbidden=REAR）门禁缺失回归测试。

审计表 A 缺失项修复 1：cargo_profile.zone_policy.forbidden 声明的禁区
在活跃路径 12 个放置站点上均无独立门禁（仅孤立 compaction.py Step2 有
此检查）。本测试先于修复编写，修复前应失败（红），修复后通过（绿）。

被谁调用：pytest 测试收集器（tests/ 目录）。
"""

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.solver.unified_solver import UnifiedSolver


CONTAINER_SPEC = {"usable": {"L": 12.032, "W": 2.352, "H": 2.698}}


def _make_solver_with_no_rear_sku(quantity=4):
    container = InputAdapter.parse_container(CONTAINER_SPEC)
    cargo = InputAdapter.parse_cargo_list([
        {
            "sku": "NO-REAR",
            "name": "禁后区货箱",
            "w": 1.0, "d": 1.0, "h": 1.0,
            "weight": 100.0,
            "quantity": quantity,
            "cargoProfile": {"zonePolicy": {"forbidden": ["REAR"]}},
        }
    ])
    solver = UnifiedSolver(container)
    return container, cargo, solver


def _placement_x(p) -> float:
    return p["x"] if isinstance(p, dict) else p.position.x


class TestForbiddenZoneGate:
    def test_gate_rejects_rear_zone_candidate(self):
        """单元级：_check_placement_constraints 必须拒绝落入禁后区的候选。"""
        container, cargo, solver = _make_solver_with_no_rear_sku()
        tensors = solver._convert_cargo_skus_to_tensors(cargo)
        solver._sku_tensor_map = {t.sku_id: t for t in tensors}

        cand = {
            "sku_id": "NO-REAR",
            "x": 0.0, "y": 0.0, "z": 0.0,
            "dx": 1.0, "dy": 1.0, "dz": 1.0,
            "weight_kg": 100.0,
        }
        # 修复前：禁后区候选被放行（返回 True）→ 本断言失败（红）
        assert solver._check_placement_constraints(cand, []) is False, (
            "禁后区候选（x=0 <= rear_zone_length_m）未被门禁拒绝"
        )

    def test_end_to_end_no_box_in_rear_zone(self):
        """端到端：求解终态不允许任何禁后区 SKU 位于 x <= rear_zone_length_m。"""
        container, cargo, solver = _make_solver_with_no_rear_sku()
        sol = solver.solve(cargo)
        assert sol.placed_count > 0, "求解器应至少放置一件货物以构成有效断言"

        rear_len = container.rear_zone_length_m
        violators = [p for p in sol.placements if _placement_x(p) <= rear_len + 1e-4]
        # 修复前：首批箱子落在 x≈0 的后区 → 本断言失败（红）
        assert not violators, (
            f"{len(violators)} 件禁后区 SKU 被放入 x<={rear_len}m 的后区，无任何门禁拦截"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
