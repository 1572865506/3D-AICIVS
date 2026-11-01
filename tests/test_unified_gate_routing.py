"""统一门禁收敛回归测试（审计表 A"实现不一致"修复：12 处复制粘贴检查元组）。

两个互补钉住：
1. 语义等价——统一门禁 `_check_candidate_validity_with_reason` 的布尔裁决必须与
   手工展开的四检查元组逐候选一致（收敛是纯数据流重构，不允许任何裁决漂移）。
2. 源码路由——全量元组站点必须全部改走统一门禁；仅允许两处豁免：
   PASS1 条带列实例化（倾覆捷径，待产品裁决）与 PASS4 基底早退（性能预筛，
   扩展单元仍全量复检）。

被谁调用：pytest 测试收集器（tests/ 目录）。
"""

import os
import re

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in (__import__("sys").path):
    __import__("sys").path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.solver.unified_solver import UnifiedSolver

SOLVER_PATH = os.path.join(PROJECT_ROOT, "backend", "solver_v2", "solver", "unified_solver.py")

CONTAINER_SPEC = {"usable": {"L": 12.032, "W": 2.352, "H": 2.698}}


def _make_solver_with_state():
    """构造带真实货池与少量已放置箱的求解器状态，供候选采样。"""
    container = InputAdapter.parse_container(CONTAINER_SPEC)
    cargo = InputAdapter.parse_cargo_list([
        {"sku": "S1", "name": "标准箱", "w": 1.0, "d": 0.8, "h": 1.2, "weight": 50.0, "quantity": 10},
        {"sku": "S2", "name": "重箱", "w": 1.2, "d": 1.0, "h": 0.8, "weight": 300.0, "quantity": 5,
         "maxBearingKg": 200.0},
    ])
    solver = UnifiedSolver(container)
    tensors = solver._convert_cargo_skus_to_tensors(cargo)
    solver._sku_tensor_map = {t.sku_id: t for t in tensors}
    solver._current_rejection_counts = {}
    solver._has_any_bearing_constraints = True
    solver._has_door_skus = False

    # 手工布置一个最小合法墙段（全部落地、无叠放），供候选采样参考
    placements = [
        {"sku_id": "S1", "x": 0.0, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 0.8, "dz": 1.2, "weight_kg": 50.0},
        {"sku_id": "S1", "x": 0.0, "y": 0.8, "z": 0.0, "dx": 1.0, "dy": 0.8, "dz": 1.2, "weight_kg": 50.0},
        {"sku_id": "S1", "x": 0.0, "y": 1.6, "z": 0.0, "dx": 1.0, "dy": 0.75, "dz": 1.2, "weight_kg": 50.0},
        {"sku_id": "S2", "x": 1.0, "y": 0.0, "z": 0.0, "dx": 1.2, "dy": 1.0, "dz": 0.8, "weight_kg": 300.0},
    ]
    return container, solver, placements


def _sample_candidates(container, solver):
    """采样覆盖出界/碰撞/悬空/合规/落地等多类候选（确定性网格 + 关键边界值）。"""
    oris = [
        (1.0, 0.8, 1.2), (0.8, 1.0, 1.2), (1.2, 1.0, 0.8),
        (1.0, 1.0, 1.0), (0.5, 0.5, 0.5),
    ]
    cands = []
    xs = [0.0, 0.5, 1.0, 1.6, 5.0, 11.0, 11.9, 12.0]
    ys = [0.0, 0.4, 0.8, 1.6, 2.3]
    zs = [0.0, 1.2, 2.0, 2.6]
    for dx, dy, dz in oris:
        for x in xs:
            for y in ys:
                for z in zs:
                    cands.append({
                        "sku_id": "S1" if dx != 1.2 else "S2",
                        "x": x, "y": y, "z": z, "dx": dx, "dy": dy, "dz": dz,
                        "weight_kg": 50.0 if dx != 1.2 else 300.0,
                    })
    return cands


class TestUnifiedGateRouting:
    def test_gate_semantically_equivalent_to_manual_tuple(self):
        """统一门禁与手工四检查元组在数百个采样候选上逐布尔一致。"""
        container, solver, placements = _make_solver_with_state()
        for cand in _sample_candidates(container, solver):
            via_gate = solver._check_candidate_validity_with_reason(cand, placements)
            manual = (
                not solver._has_collision(cand, placements)
                and solver._has_sufficient_support(cand, placements)
                and solver._check_placement_constraints(cand, placements)
                and solver._is_placement_tipping_safe(cand, placements)
            )
            assert via_gate == manual, (
                f"门禁裁决漂移 @ {cand}: gate={via_gate} manual={manual}"
            )

    def test_source_level_gate_convergence(self):
        """源码级：全量四检查元组站点必须收敛到统一门禁。

        允许的 `_is_placement_tipping_safe(` 裸调用恰为 2 处：
        - 统一门禁内部的调用
        - PASS1 条带列实例化的倾覆捷径站点（轮6已核验为门禁前向支承豁免的
          等价记忆化：列内行连续排布使 rx+1 行恰好满足门禁的前向搭接条件，
          且 P0-4 事务回滚保证依赖未来箱的捷径箱永不提交——非语义分歧，
          显式豁免并注释证明于 unified_solver.py 实例化循环处）
        统一门禁的调用点必须 >= 10（11 个全量元组站点）。
        """
        with open(SOLVER_PATH, "r", encoding="utf-8") as f:
            src = f.read()
        raw_tipping_calls = len(re.findall(r"self\._is_placement_tipping_safe\(", src))
        gate_calls = len(re.findall(r"self\._check_candidate_validity_with_reason\(", src))
        # 收敛后：门禁内部 1 处 + PASS1 捷径 1 处 = 2
        assert raw_tipping_calls <= 2, (
            f"仍有 {raw_tipping_calls} 处站点绕过统一门禁直接调用倾覆检查（收敛不完整）"
        )
        assert gate_calls >= 10, f"统一门禁仅 {gate_calls} 处调用点，站点收敛不完整"

    def test_no_unstable_boxes_in_committed_solutions(self):
        """端到端钉住：提交解中不得存在倾覆不安全箱。条带捷径依赖的未来箱若被
        回滚遗漏，将在此显形为 UNSTABLE_PLACEMENT（validator Gate 11 兜底的
        直接断言化，混合尺寸货单以触发条带列实例化路径）。"""
        container = InputAdapter.parse_container(CONTAINER_SPEC)
        cargo = InputAdapter.parse_cargo_list([
            {"sku": "A1", "name": "标准箱A", "w": 1.2, "d": 1.0, "h": 1.0, "weight": 80.0, "quantity": 24},
            {"sku": "B1", "name": "中箱B", "w": 0.8, "d": 0.6, "h": 0.6, "weight": 25.0, "quantity": 40},
            {"sku": "C1", "name": "扁平箱C", "w": 1.0, "d": 0.8, "h": 0.35, "weight": 15.0, "quantity": 30},
        ])
        solver = UnifiedSolver(container)
        sol = solver.solve(cargo)
        assert sol.placed_count > 0
        unstable = [v for v in sol.validation_result.violations
                    if getattr(v.violation_type, "name", "") == "UNSTABLE_PLACEMENT"]
        assert not unstable, f"提交解存在 {len(unstable)} 个倾覆不安全箱（捷径回滚可能遗漏）"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
