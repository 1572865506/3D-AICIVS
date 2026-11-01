"""层数语义收敛回归测试（审计表 A 不一致项：三套层数语义分裂）。

三套语义：
1. PASS4 锚点预筛 _check_stacking_limit（5cm 精确列对齐，锚点级近似）
2. 门禁第 4 项链式走查（15% 接触重叠，逐候选权威）
3. must_be_on_floor 分支的 z/dz 算术计层（假设每层 dz 一致）

本文件钉住两件事：
- 预筛安全方向（性质）：预筛在锚点处绝不拒绝权威门禁会接受的候选
  （5cm 列计数 ⊆ 15% 链计数），防止未来编辑反转；
- 算术计层消除：must_be_on_floor 分支不得用 z/dz 算术重复门禁第 4 项的
  职责——混合 dz 同款堆叠时算术会多计层数、错误拒绝合法放置
  （链式计数为唯一权威，双重门禁以较严者否决）。

被谁调用：pytest 测试收集器（tests/ 目录）。
"""

import os
import random

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
    solver._current_rejection_counts = {}
    solver._has_door_skus = False
    return container, solver, tensors


class TestLayerSemanticsConvergence:
    def test_prefilter_reject_implies_gate_reject_at_anchor(self):
        """性质钉住（安全方向）：预筛在锚点拒绝 ⟺ 门禁链式计数在锚点同样拒绝。
        两处必须共用同一链深实现——旧 5cm 列+z 宽域计数与 15% 链互不包含
        （夹心层场景预筛更严、大偏移场景门禁更严），唯一正确收敛是单一实现。"""
        container, solver, tensors = _make_solver([
            {"sku": "STK", "name": "堆叠件", "w": 1.0, "d": 0.8, "h": 0.6, "weight": 20.0,
             "quantity": 20, "max_stack_layers": 3},
        ])
        rng = random.Random(42)
        placements = []
        z = 0.0
        for k in range(3):
            off = rng.choice([(0.0, 0.0), (0.04, 0.0), (0.0, 0.03), (0.06, 0.05)])
            placements.append(_plc("STK", off[0], off[1], round(z, 4), 1.0, 0.8, 0.6))
            z += 0.6
        checked = 0
        for trial in range(60):
            ax = rng.uniform(0.0, 0.3)
            ay = rng.uniform(0.0, 0.3)
            az = round(z + rng.choice([0.0, 0.6, 1.2]), 4)
            tensor = tensors[0]
            prefilter_ok = solver._check_stacking_limit(tensor, ax, ay, az, placements)
            cand = _plc("STK", ax, ay, az, 1.0, 0.8, 0.6)
            gate_ok = solver._check_placement_constraints(cand, placements)
            checked += 1
            assert prefilter_ok == gate_ok or (prefilter_ok and not gate_ok), (
                f"预筛拒绝但门禁放行（预筛更严，会丢放置）@ ({ax:.2f},{ay:.2f},{az:.2f})"
            )
        assert checked > 0

    def test_mixed_dz_floor_stack_no_arithmetic_overcount(self):
        """混合 dz 同款落地堆叠：链深 4 ≤ max_stack_layers=4 的合法候选不得被
        z/dz 算术（1+round(2.2/0.6)=5>4）错误拒绝。"""
        container, solver, tensors = _make_solver([
            {"sku": "MIXF", "name": "混层件", "w": 1.0, "d": 0.8, "h": 0.6, "weight": 20.0,
             "quantity": 10, "max_stack_layers": 4},
        ])
        for t in tensors:
            t.must_be_on_floor = True
        # 同款 3 层混合 dz 柱：0.8 + 0.6 + 0.8 = 2.2，候选（dz=0.6）落在柱顶 → 链深 4
        placements = [
            _plc("MIXF", 0.0, 0.0, 0.0, 1.0, 0.8, 0.8),
            _plc("MIXF", 0.0, 0.0, 0.8, 1.0, 0.8, 0.6),
            _plc("MIXF", 0.02, 0.0, 1.4, 1.0, 0.8, 0.8),
        ]
        cand = _plc("MIXF", 0.0, 0.0, 2.2, 1.0, 0.8, 0.6)
        # 修复前：算术计层 1+round(2.2/0.6)=5 > 4 → 误拒（红）
        assert solver._check_placement_constraints(cand, placements), (
            "链深 4 的合法混合 dz 候选被 z/dz 算术计层错误拒绝"
        )

    def test_floor_stack_overdepth_still_rejected(self):
        """守护：链深超限的落地堆叠仍必须被拒绝（防止消除算术后放松）。"""
        container, solver, tensors = _make_solver([
            {"sku": "MIXF", "name": "混层件", "w": 1.0, "d": 0.8, "h": 0.6, "weight": 20.0,
             "quantity": 10, "max_stack_layers": 2},
        ])
        for t in tensors:
            t.must_be_on_floor = True
        placements = [
            _plc("MIXF", 0.0, 0.0, 0.0, 1.0, 0.8, 0.6),
            _plc("MIXF", 0.0, 0.0, 0.6, 1.0, 0.8, 0.6),
        ]
        cand = _plc("MIXF", 0.0, 0.0, 1.2, 1.0, 0.8, 0.6)  # 链深 3 > 2
        assert not solver._check_placement_constraints(cand, placements), (
            "链深 3 > max_stack_layers=2 的候选必须被拒绝"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
