"""CompactionPass 缺失约束门禁回归测试（审计表 A 缺失项修复 2）。

背景：孤立 compaction.py 相对活跃路径门禁缺失以下单元格——
  Step1/Step2: max_stack_layers 复查、支撑连通性（跨空桥）、单箱倾覆安全
  Step2:       承重复查（Step1 已有，RootCause-3 只修了 Step1）
本测试先于修复编写：修复前因"最终 validator 回滚"吞掉全部合法移动
（all-or-nothing），或因 validator 不审计倾覆而静默产出倾覆不安全布局。

被谁调用：pytest 测试收集器（tests/ 目录）。
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.domain.models import (
    ContainerSpec, BoxDim, CargoSKU, StackingPolicy, QuantityPlan,
    Placement, Point3D, Orientation3D, PlacementContext,
)
from backend.solver_v2.solver.compaction import CompactionPass
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator


def _container(l=6.0, w=2.0, h=3.5):
    return ContainerSpec(code="TestContainer", inner_dim=BoxDim(l, w, h), max_payload_kg=10000.0)


def _plc(pid, sku, x, y, z, dx, dy, dz, weight=10.0):
    return Placement(
        placement_id=pid, instance_id=f"inst_{pid}", sku_id=sku,
        position=Point3D(x, y, z), orientation=Orientation3D(dx, dy, dz),
        weight_kg=weight, context=PlacementContext.MAIN_WALL,
    )


def _sku(sku_id, dx=1.0, dy=1.0, dz=1.0, weight=10.0, **policy):
    return CargoSKU(
        sku_id=sku_id, name=sku_id,
        box=BoxDim(dx, dy, dz), weight_kg=weight,
        quantity=QuantityPlan(required=1),
        stacking_policy=StackingPolicy(**policy),
    )


class TestCompactionMissingGates:
    def test_step2_max_stack_layer_precheck_preserves_other_moves(self):
        """Step2 内滑：同款 SKU 滑到已达 max_stack_layers 的同款柱顶必须被预检拒绝，
        且不触发最终 validator 整体回滚（其他合法移动必须保留）。"""
        container = _container()
        catalog = [
            _sku("STACKED", max_stack_layers=2),
            _sku("PAD"),
            _sku("MOVER"),
        ]
        # 构造输入时保证全部数量约束满足（STACKED×3 / PAD×2 / MOVER×1）
        catalog[0].quantity = catalog[0].quantity.__class__(required=3)
        catalog[1].quantity = catalog[1].quantity.__class__(required=2)
        placements = [
            _plc("A", "STACKED", 1.0, 0.0, 0.0, 1.0, 1.0, 1.0),    # 同款 2 层柱：第 1 层
            _plc("B", "STACKED", 1.0, 0.0, 1.0, 1.0, 1.0, 1.0),    # 第 2 层（已满）
            _plc("Q1", "PAD", 2.0, 0.0, 0.0, 1.0, 1.0, 1.0),       # 垫高柱（立方块，SF 安全）
            _plc("Q2", "PAD", 2.0, 0.0, 1.0, 1.0, 1.0, 1.0),
            _plc("C", "STACKED", 2.0, 0.0, 2.0, 1.0, 1.0, 1.0),    # 悬于柱顶，内滑 x=1 将落上 B → 第 3 层违规
            _plc("M", "MOVER", 4.0, 1.0, 0.0, 1.0, 1.0, 1.0),      # 独立 y 车道的合法内滑移动（必须被保留）
        ]
        res = CompactionPass(container=container).compact(list(placements), cargo_catalog=catalog)

        by_id = {p.placement_id: p for p in res.placements}
        # 修复前：C 内滑落上 B（同款第 3 层）→ validator 判层数违规 → 整体回滚 → M 的合法移动被吞掉
        assert res.boxes_moved_count >= 1, "层数预检缺失导致 all-or-nothing 回滚，合法移动 M 被连带丢弃"
        assert abs(by_id["C"].position.x - 1.0) > 1e-6, "STACKED 不得内滑到已满 2 层的同款柱顶（第 3 层违规）"
        assert abs(by_id["M"].position.x - 0.0) < 1e-6, "MOVER 应成功内滑至内壁"

        val = IndependentGlobalValidator.validate(container, res.placements, catalog)
        assert val.is_valid, f"终态必须零违规: {val.violations}"

    def test_step2_bearing_precheck_preserves_other_moves(self):
        """Step2 内滑：重箱滑到低承重垫箱上方必须被预检拒绝（与 Step1 既有语义对齐），
        且不触发整体回滚。"""
        container = _container()
        catalog = [
            _sku("WEAK", max_bearing_kg=30.0),
            _sku("PAD"),
            _sku("HEAVY", weight=80.0),
            _sku("MOVER"),
        ]
        placements = [
            _plc("W", "WEAK", 0.0, 0.0, 0.0, 1.0, 1.0, 1.0),       # 承重仅 30kg 的垫箱
            _plc("P", "PAD", 2.0, 0.0, 0.0, 1.0, 1.0, 1.0),
            _plc("H", "HEAVY", 2.0, 0.0, 1.0, 1.0, 1.0, 1.0, weight=80.0),  # 80kg 悬于 P 上，内滑将压上 W
            _plc("M", "MOVER", 4.0, 1.0, 0.0, 1.0, 1.0, 1.0),      # 独立 y 车道的合法内滑移动（必须被保留）
        ]
        res = CompactionPass(container=container).compact(list(placements), cargo_catalog=catalog)

        by_id = {p.placement_id: p for p in res.placements}
        # 修复前：H 内滑压上 W（80>30）→ validator 判承重违规 → 整体回滚 → M 的合法移动被吞掉
        assert res.boxes_moved_count >= 1, "Step2 缺承重预检导致整体回滚，合法移动 M 被连带丢弃"
        assert abs(by_id["H"].position.x - 2.0) < 1e-6, "HEAVY 不得内滑压上 30kg 承重垫箱"
        assert abs(by_id["M"].position.x - 0.0) < 1e-6, "MOVER 应成功内滑至内壁"

        val = IndependentGlobalValidator.validate(container, res.placements, catalog)
        assert val.is_valid, f"终态必须零违规: {val.violations}"

    def test_forward_support_stripping_helper(self):
        """单元级：前向支承剥夺判定（依赖箱固有不稳且不可迁移时，移动必须被拦截；
        若移动后本箱新位置仍提供前向支承，则放行）。

        说明：e2e 场景中依赖箱可与移动箱合法联合迁移（终态仍合规），故本检查
        以单元级验证语义；其生产价值在于依赖箱因其他约束不可迁移的布局。
        """
        container = _container(l=6.0)
        cp = CompactionPass(container=container)
        tall = _sku("TALL", dx=0.5, dz=2.0)
        block = _sku("BLOCK")
        mover = _sku("MOVER")
        placements = [
            _plc("T", "TALL", 1.0, 0.0, 0.0, 0.5, 1.0, 2.0),   # SF=0.5<1.5，前向支承来自 N（旧位 x=1.5）
            _plc("N", "BLOCK", 1.5, 0.0, 0.0, 1.0, 1.0, 1.0),
            _plc("M", "MOVER", 4.0, 1.0, 0.0, 1.0, 1.0, 1.0),
        ]
        # N 内滑到 x=0（脱离 T 的前向搭接，且无人补位）→ 必须判定为剥夺
        assert cp._move_strips_forward_support(container, placements, "N",
                                               1.5, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0) is True, \
            "N 移到 x=0 剥离 T 的唯一前向支承，应判定剥夺"
        # N 平移到 x=0.5（新箱体前沿用 0.5+1.0=1.5 仍贴 T 的目标面）→ 不构成剥夺
        assert cp._move_strips_forward_support(container, placements, "N",
                                               1.5, 0.0, 0.0, 0.5, 0.0, 1.0, 1.0, 1.0) is False, \
            "N 新位置仍为 T 提供前向支承，不应误判剥夺"
        # 与 T 无前向搭接关系的 M 移动 → 不构成剥夺
        assert cp._move_strips_forward_support(container, placements, "M",
                                               4.0, 1.0, 0.0, 0.0, 1.0, 0.0, 1.0, 1.0) is False, \
            "与固有不稳箱无搭接关系的移动不应被拦截"

    def test_support_span_connectivity_helper(self):
        """单元级：支撑连通性（跨空桥）判定与活跃路径 P0-2 语义一致。"""
        from backend.solver_v2.solver.compaction import CompactionPass as CP
        cp = CP(container=_container())
        # 两块接触各 0.4m、中间 0.2m 空隙（> 8cm 上限）→ 必须判为断连
        assert cp._support_span_disconnected([(0.3, 0.7), (0.9, 1.3)], dx=1.0, dy=1.0) is True, \
            "两接触块间隙 0.2m > 8cm 上限，应判定跨空桥断连"
        assert cp._support_span_disconnected([(0.3, 0.7), (0.7, 1.1)], dx=1.0, dy=1.0) is False, \
            "贴接接触不应误判断连"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
