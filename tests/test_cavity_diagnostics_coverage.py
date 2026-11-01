"""空腔诊断覆盖回归测试（审计表 A 诊断盲区修复：分类器只看尾部/顶部两类）。

审计确认的盲区：侧向（Y）间隙、墙间（X）凹陷、悬浮层的落地禁入分类
均不在 `_compute_cavity_diagnostics` 输出内——导致"不可解释空洞数"棘轮
（R3 不变量 2）无法诚实计量。本测试先于修复编写：修复前应失败（红）。

被谁调用：pytest 测试收集器（tests/ 目录）。
"""

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in (__import__("sys").path):
    __import__("sys").path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.solver.unified_solver import UnifiedSolver

CONTAINER_SPEC = {"usable": {"L": 12.032, "W": 2.352, "H": 2.698}}


def _plc(sku, x, y, z, dx, dy, dz, weight=10.0):
    return {"sku_id": sku, "x": x, "y": y, "z": z, "dx": dx, "dy": dy, "dz": dz, "weight_kg": weight}


def _make_solver(cargo_entries):
    container = InputAdapter.parse_container(CONTAINER_SPEC)
    cargo = InputAdapter.parse_cargo_list(cargo_entries)
    solver = UnifiedSolver(container)
    tensors = solver._convert_cargo_skus_to_tensors(cargo)
    solver._sku_tensor_map = {t.sku_id: t for t in tensors}
    return container, solver, tensors


def _cavity_boxes(cavs):
    return [tuple(c["box"]) for c in cavs]


class TestCavityDiagnosticsCoverage:
    def test_side_y_gap_detected_as_strategy_abandoned(self):
        """侧向 Y 间隙（0.5m 宽通缝）必须被检出，且有可放入 SKU 时分类为策略放弃。"""
        container, solver, tensors = _make_solver([
            {"sku": "SMALL", "name": "小箱", "w": 0.4, "d": 0.4, "h": 0.4, "weight": 10.0, "quantity": 5},
        ])
        # 两列墙块之间留出 y∈[0.9,1.4] 的通缝（跨 x[0,3]、z[0,1]）
        placements = []
        for x0 in (0.0, 1.0, 2.0):
            placements.append(_plc("WALL", x0, 0.0, 0.0, 1.0, 0.9, 1.0))
            placements.append(_plc("WALL", x0, 1.4, 0.0, 1.0, 0.9, 1.0))
        cavs = solver._compute_cavity_diagnostics(placements, tensors)

        gap_cavs = [c for c in cavs
                    if c["box"][1] <= 0.9 + 1e-6 and c["box"][4] >= 1.4 - 1e-6
                    and c["box"][0] < 3.0]
        # 修复前：无任何侧向间隙输出 → 红
        assert gap_cavs, f"侧向 Y 间隙未被检出，现有输出: {_cavity_boxes(cavs)}"
        assert any(c["exclusion_category"] == "STRATEGY_ABANDONED" for c in gap_cavs), \
            f"可放入 SMALL 箱的间隙应分类为 STRATEGY_ABANDONED: {gap_cavs}"

    def test_inter_wall_x_gap_detected(self):
        """墙间 X 凹陷（x∈[2,3] 的全断面空段）必须被检出（现有代码只看尾部）。"""
        container, solver, tensors = _make_solver([
            {"sku": "SMALL", "name": "小箱", "w": 0.4, "d": 0.4, "h": 0.4, "weight": 10.0, "quantity": 5},
        ])
        placements = [
            _plc("WALL", 0.0, 0.0, 0.0, 2.0, 2.352, 1.0),   # 后段墙 x[0,2]
            _plc("WALL", 3.0, 0.0, 0.0, 2.0, 2.352, 1.0),   # 前段墙 x[3,5]
        ]
        cavs = solver._compute_cavity_diagnostics(placements, tensors)

        mid_cavs = [c for c in cavs if c["box"][0] >= 2.0 - 1e-6 and c["box"][3] <= 3.0 + 1e-6]
        # 修复前：x[2,3] 凹陷不可见（只有尾部 x[5,12] 残余）→ 红
        assert mid_cavs, f"墙间 X 凹陷未被检出，现有输出: {_cavity_boxes(cavs)}"

    def test_floating_gap_with_floor_only_skus_classified(self):
        """封闭悬浮空腔（z>0，四周有围护）+ 仅剩落地件时必须分类为 MUST_BE_ON_FLOOR 约束排除。"""
        container, solver, tensors = _make_solver([
            {"sku": "FLOOR-ONLY", "name": "落地重件", "w": 0.4, "d": 0.4, "h": 0.4, "weight": 50.0, "quantity": 3},
        ])
        for t in tensors:
            if t.sku_id == "FLOOR-ONLY":
                t.must_be_on_floor = True
        # 底层满铺 + 上层留 y 缝 + 端封 + 顶盖 → 构成 x[0,2]×y[0.9,1.4]×z[1,2] 封闭腔
        placements = [
            _plc("BASE", 0.0, 0.0, 0.0, 2.0, 1.176, 1.0),
            _plc("BASE", 0.0, 1.176, 0.0, 2.0, 1.176, 1.0),
            _plc("TOP", 0.0, 0.0, 1.0, 2.0, 0.9, 1.0),
            _plc("TOP", 0.0, 1.4, 1.0, 2.0, 0.9, 1.0),
            _plc("CAP", 2.0, 0.9, 0.0, 1.0, 0.5, 2.0),   # 端封：堵住缝隙前端
            _plc("LID", 0.0, 0.9, 2.0, 2.0, 0.5, 0.2),   # 顶盖：封住腔体上方
        ]
        cavs = solver._compute_cavity_diagnostics(placements, tensors)

        pocket = [c for c in cavs
                  if c["box"][0] < 2.0 - 1e-6 and abs(c["box"][1] - 0.9) < 0.11
                  and abs(c["box"][2] - 1.0) < 0.11]
        # 修复前：封闭悬浮腔不可见 → 红
        assert pocket, f"封闭悬浮空腔未被检出，现有输出: {_cavity_boxes(cavs)}"
        assert any(c["exclusion_category"] == "CONSTRAINT_EXCLUDED"
                   and c.get("excluded_by_constraint") == "MUST_BE_ON_FLOOR" for c in pocket), \
            f"仅剩落地件时的封闭悬浮腔应分类为 MUST_BE_ON_FLOOR 排除: {pocket}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
