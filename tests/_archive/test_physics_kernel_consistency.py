# -*- coding: utf-8 -*-
"""
共享物理内核 (physics_kernel) 与独立验证器 (IndependentGlobalValidator) 100% 一致性单测套件

全面覆盖:
  1. 边界与越界检查同构性 (Bounds & Out of Bounds)
  2. 3D AABB 穿透与紧密贴合同构性 (Collision Overlap & Touching)
  3. 姿态合法性与上下文同构性 (Orientation & Context)
  4. 底部支撑率与空中悬空同构性 (Support Ratio & Floating)
  5. 禁顶叠与封顶件同构性 (No Top Stacking & Self Stacking)
  6. 地面专属与最大堆码层数同构性 (Floor Only & Stack Limits)
  7. 垂直传力承重与表面压强同构性 (Bearing Capacity & Surface Pressure DAG)
  8. 0.5g 纵向减速倾覆安全同构性 (Longitudinal Tipping Moment & Door Bracing)
  9. 门区隔离与禁入门禁同构性 (Door Zone Lockout)
 10. 全局端到端序列放置：内核预检放行 -> 独立验证器审计必为 0 违规 (0 Violations Guarantee)
"""
import unittest
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.domain.models import (
    BoxDim,
    Point3D,
    Orientation3D,
    OrientationPolicy,
    OrientationMode,
    StackingPolicy,
    QuantityPlan,
    ContainerSpec,
    CargoSKU,
    Placement,
    PlacementContext,
    ZoneType,
    PackingRole,
)
from backend.solver_v2.validation.types import ViolationType, ViolationSeverity
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from backend.solver_v2.physics_kernel import (
    check_no_collision,
    check_orientation,
    check_support,
    check_tipping_safety,
    check_bearing_capacity,
    check_business_constraints,
    check_placement_feasibility,
)


class TestPhysicsKernelConsistency(unittest.TestCase):
    """验证 physics_kernel 纯函数与 IndependentGlobalValidator 的同构判定一致性。"""

    def setUp(self):
        self.container = ContainerSpec(
            code="40HQ_TEST",
            inner_dim=BoxDim(x=12.0, y=2.4, z=2.6),
            max_payload_kg=25000.0,
            door_zone_length_m=1.2,
            rear_zone_length_m=1.0,
        )
        self.container_dims = (12.0, 2.4, 2.6)

        # 标准立方体 SKU: 1.0 x 1.0 x 1.0, 100 kg
        self.sku_cube = CargoSKU(
            sku_id="SKU_CUBE",
            name="Standard Cube",
            box=BoxDim(x=1.0, y=1.0, z=1.0),
            weight_kg=100.0,
            quantity=QuantityPlan(required=20),
            orientation_policy=OrientationPolicy(allow_upright=True, allow_flat=True, allow_side=True),
            stacking_policy=StackingPolicy(
                max_bearing_kg=1000.0,
                max_pressure_kg_m2=2000.0,
                min_support_ratio=0.70,
                allow_stacking_on_top=True,
                must_be_on_floor=False,
            ),
        )

        # 落地专属且限叠 2 层 SKU: 1.0 x 1.0 x 1.0, 150 kg
        self.sku_floor_only = CargoSKU(
            sku_id="SKU_FLOOR",
            name="Floor Only Item",
            box=BoxDim(x=1.0, y=1.0, z=1.0),
            weight_kg=150.0,
            quantity=QuantityPlan(required=10),
            orientation_policy=OrientationPolicy(allow_upright=True, allow_flat=False, allow_side=False),
            stacking_policy=StackingPolicy(
                max_bearing_kg=800.0,
                max_stack_layers=2,
                allow_stacking_on_top=True,
                must_be_on_floor=True,
                stack_on_self=True,
            ),
        )

        # 绝对封顶件 SKU: 1.0 x 1.0 x 1.0, 50 kg
        self.sku_no_top = CargoSKU(
            sku_id="SKU_NO_TOP",
            name="No Top Stacking Item",
            box=BoxDim(x=1.0, y=1.0, z=1.0),
            weight_kg=50.0,
            quantity=QuantityPlan(required=5),
            stacking_policy=StackingPolicy(
                allow_stacking_on_top=False,
                stack_on_self=False,
            ),
        )

        # 脆弱承重受限件: max_bearing_kg = 80kg
        self.sku_fragile = CargoSKU(
            sku_id="SKU_FRAGILE",
            name="Fragile Bearing Item",
            box=BoxDim(x=1.0, y=1.0, z=1.0),
            weight_kg=50.0,
            quantity=QuantityPlan(required=5),
            stacking_policy=StackingPolicy(
                max_bearing_kg=80.0,
                max_pressure_kg_m2=100.0,
                allow_stacking_on_top=True,
            ),
        )

        # 高瘦倾覆敏感件: 0.3 x 1.0 x 1.0 (SF = 2 * 0.3 / 1.0 = 0.60 < 1.50)
        self.sku_slender = CargoSKU(
            sku_id="SKU_SLENDER",
            name="Slender Tall Item",
            box=BoxDim(x=0.3, y=1.0, z=1.0),
            weight_kg=80.0,
            quantity=QuantityPlan(required=10),
            orientation_policy=OrientationPolicy(allow_upright=True, allow_flat=False, allow_side=False),
        )

        # 门区专用件
        self.sku_door_seal = CargoSKU(
            sku_id="SKU_DOOR_SEAL",
            name="Door Seal Bag",
            box=BoxDim(x=0.5, y=1.0, z=1.0),
            weight_kg=30.0,
            quantity=QuantityPlan(required=10),
            packing_roles=(PackingRole.DOOR_SEAL,),
            target_zone=ZoneType.DOOR,
        )

        self.sku_map = {
            self.sku_cube.sku_id: self.sku_cube,
            self.sku_floor_only.sku_id: self.sku_floor_only,
            self.sku_no_top.sku_id: self.sku_no_top,
            self.sku_fragile.sku_id: self.sku_fragile,
            self.sku_slender.sku_id: self.sku_slender,
            self.sku_door_seal.sku_id: self.sku_door_seal,
        }

        self.validator = IndependentGlobalValidator()

    # -------------------------------------------------------------------------
    # 1. 边界与越界检查同构性
    # -------------------------------------------------------------------------
    def test_bounds_consistency(self):
        """测试边界检查：合法放行，负坐标及超界拦截与验证器完全同构"""
        cand_legal = {"x": 0.0, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE"}
        ok, reason = check_no_collision(cand_legal, [], self.container_dims)
        self.assertTrue(ok)
        val_res = self.validator.validate(self.container, [cand_legal], self.sku_map)
        self.assertTrue(val_res.is_valid)

        # 负坐标
        cand_neg = {"x": -0.1, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE"}
        ok, reason = check_no_collision(cand_neg, [], self.container_dims)
        self.assertFalse(ok)
        val_res = self.validator.validate(self.container, [cand_neg], self.sku_map)
        self.assertFalse(val_res.is_valid)
        self.assertIn("CONTAINER_BOUNDS_EXCEEDED", val_res.rejection_reasons)

        # X 轴超界 (12.0m 容器)
        cand_over_x = {"x": 11.5, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE"}
        ok, reason = check_no_collision(cand_over_x, [], self.container_dims)
        self.assertFalse(ok)
        val_res = self.validator.validate(self.container, [cand_over_x], self.sku_map)
        self.assertFalse(val_res.is_valid)
        self.assertIn("CONTAINER_BOUNDS_EXCEEDED", val_res.rejection_reasons)

    # -------------------------------------------------------------------------
    # 2. 3D AABB 穿透与紧密贴合同构性
    # -------------------------------------------------------------------------
    def test_collision_overlap_and_touching_consistency(self):
        """测试碰撞穿透拦截与紧密贴合放行同构性"""
        p1 = {"x": 0.0, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE", "weight_kg": 100.0}

        # 完美贴合 (x=1.0): 双方都不应报重叠
        cand_touch = {"x": 1.0, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE", "weight_kg": 100.0}
        ok, _ = check_no_collision(cand_touch, [p1], self.container_dims)
        self.assertTrue(ok)
        val_res = self.validator.validate(self.container, [p1, cand_touch], self.sku_map)
        self.assertTrue(val_res.is_valid)

        # 穿透碰撞 (x=0.8): 均报 COLLISION_OVERLAP
        cand_overlap = {"x": 0.8, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE", "weight_kg": 100.0}
        ok, _ = check_no_collision(cand_overlap, [p1], self.container_dims)
        self.assertFalse(ok)
        val_res = self.validator.validate(self.container, [p1, cand_overlap], self.sku_map)
        self.assertFalse(val_res.is_valid)
        self.assertIn("COLLISION_OVERLAP_DETECTED", val_res.rejection_reasons)

    # -------------------------------------------------------------------------
    # 3. 姿态合法性与上下文同构性
    # -------------------------------------------------------------------------
    def test_orientation_consistency(self):
        """测试姿态合法性：UPRIGHT/FLAT/SIDE 判定与上下文匹配完全同构"""
        # sku_floor_only 仅允许 UPRIGHT (allow_flat=False, allow_side=False)
        cand_upright = {"x": 0.0, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_FLOOR"}
        ok, _ = check_orientation(cand_upright, self.sku_floor_only)
        self.assertTrue(ok)

        # 构造一个不允许 FLAT 的非对称 SKU
        sku_rect = CargoSKU(
            sku_id="SKU_RECT",
            name="Rectangular Item",
            box=BoxDim(x=0.5, y=0.8, z=1.2),
            weight_kg=50.0,
            quantity=QuantityPlan(required=5),
            orientation_policy=OrientationPolicy(allow_upright=True, allow_flat=False, allow_side=False),
        )
        cand_flat = {"x": 0.0, "y": 0.0, "z": 0.0, "dx": 0.5, "dy": 1.2, "dz": 0.8, "sku_id": "SKU_RECT"}
        ok, _ = check_orientation(cand_flat, sku_rect)
        self.assertFalse(ok)
        val_res = self.validator.validate(self.container, [cand_flat], {sku_rect.sku_id: sku_rect})
        self.assertFalse(val_res.is_valid)
        self.assertIn("FORBIDDEN_ORIENTATION_DETECTED", val_res.rejection_reasons)

    # -------------------------------------------------------------------------
    # 4. 底部支撑率与空中悬空同构性
    # -------------------------------------------------------------------------
    def test_support_consistency(self):
        """测试支撑率：地面层免检，空中悬空拦截，部分支撑临界同构"""
        # 地面层 (z=0.0): 必须 100% 支撑通过
        cand_ground = {"x": 0.0, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE"}
        ok, ratio, _ = check_support(cand_ground, [])
        self.assertTrue(ok)
        self.assertEqual(ratio, 1.0)

        # 空中纯悬空 (z=1.0, 无下层箱体): 拦截
        cand_float = {"x": 0.0, "y": 0.0, "z": 1.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE", "weight_kg": 100.0}
        ok, ratio, _ = check_support(cand_float, [])
        self.assertFalse(ok)
        val_res = self.validator.validate(self.container, [cand_float], self.sku_map)
        self.assertFalse(val_res.is_valid)
        self.assertTrue(any(v.violation_type == ViolationType.INSUFFICIENT_SUPPORT for v in val_res.violations))

        # 下层支撑箱体 (x=0, y=0, z=0, 1x1x1)
        p_base = {"x": 0.0, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE", "weight_kg": 100.0}

        # 上层箱体重叠 50% (x=0.5 -> 接触 dx=0.5, dy=1.0 -> 面积 0.50 < 0.70): 均应拦截
        cand_insufficient = {"x": 0.5, "y": 0.0, "z": 1.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE", "weight_kg": 100.0}
        ok, ratio, _ = check_support(cand_insufficient, [p_base], min_support_ratio=0.70)
        self.assertFalse(ok)
        val_res = self.validator.validate(self.container, [p_base, cand_insufficient], self.sku_map)
        self.assertFalse(val_res.is_valid)
        self.assertTrue(any(v.violation_type == ViolationType.INSUFFICIENT_SUPPORT for v in val_res.violations))

        # 上层箱体重叠 80% (x=0.2 -> 接触 dx=0.8, dy=1.0 -> 面积 0.80 >= 0.70): 均应放行
        cand_sufficient = {"x": 0.2, "y": 0.0, "z": 1.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE", "weight_kg": 100.0}
        ok, ratio, _ = check_support(cand_sufficient, [p_base], min_support_ratio=0.70)
        self.assertTrue(ok)
        val_res = self.validator.validate(self.container, [p_base, cand_sufficient], self.sku_map, options={"tipping_moment_constraint": False})
        self.assertTrue(val_res.is_valid)

    # -------------------------------------------------------------------------
    # 5. 禁顶叠与封顶件同构性
    # -------------------------------------------------------------------------
    def test_no_top_stacking_consistency(self):
        """测试禁顶叠：下层绝对封顶件禁止任何堆叠，异类杂货禁止顶叠"""
        p_no_top = {"x": 0.0, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_NO_TOP", "weight_kg": 50.0}

        # 尝试在上层放置任意箱体
        cand_above = {"x": 0.0, "y": 0.0, "z": 1.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE", "weight_kg": 100.0}
        ok, _, reason = check_support(cand_above, [p_no_top], cargo_specs=self.sku_map)
        self.assertFalse(ok)
        self.assertIn("封顶", reason or "")

        val_res = self.validator.validate(self.container, [p_no_top, cand_above], self.sku_map)
        self.assertFalse(val_res.is_valid)
        self.assertTrue(any(v.violation_type == ViolationType.NO_TOP_STACK_VIOLATION for v in val_res.violations))

    # -------------------------------------------------------------------------
    # 6. 地面专属与最大堆码层数同构性
    # -------------------------------------------------------------------------
    def test_floor_only_and_stack_limits_consistency(self):
        """测试地面专属规则：空中放置拦截，层数限制内同品类自叠放行，超出层数拦截"""
        # SKU_FLOOR 设定 must_be_on_floor=True, max_stack_layers=2
        p1 = {"x": 0.0, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_FLOOR", "weight_kg": 150.0}
        p2 = {"x": 0.0, "y": 0.0, "z": 1.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_FLOOR", "weight_kg": 150.0}

        # 第 2 层为同 SKU 自叠：合法放行
        ok, _ = check_business_constraints(p2, [p1], self.sku_floor_only, self.container)
        self.assertTrue(ok)
        val_res = self.validator.validate(self.container, [p1, p2], self.sku_map)
        self.assertTrue(val_res.is_valid)

        # 尝试叠放第 3 层 (超出 max_stack_layers=2): 均应拦截
        p3 = {"x": 0.0, "y": 0.0, "z": 2.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_FLOOR", "weight_kg": 150.0}
        ok, reason = check_business_constraints(p3, [p1, p2], self.sku_floor_only, self.container)
        self.assertFalse(ok)
        val_res = self.validator.validate(self.container, [p1, p2, p3], self.sku_map)
        self.assertFalse(val_res.is_valid)
        self.assertTrue(
            any(v.violation_type in (ViolationType.FLOOR_ONLY_VIOLATION, ViolationType.STACK_LIMIT_VIOLATION) for v in val_res.violations)
        )

    # -------------------------------------------------------------------------
    # 7. 垂直传力承重与表面压强同构性
    # -------------------------------------------------------------------------
    def test_bearing_capacity_and_pressure_consistency(self):
        """测试多层级联受力传导与承重/压强超限拦截同构性"""
        # p_fragile: 承重上限 80kg
        p_fragile = {"x": 0.0, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_FRAGILE", "weight_kg": 50.0}

        # 放置 100kg 箱体在上层 (100kg > 80kg): 均应拦截 BEARING_EXCEEDED
        cand_heavy = {"x": 0.0, "y": 0.0, "z": 1.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE", "weight_kg": 100.0}
        ok, reason = check_bearing_capacity(cand_heavy, [p_fragile], self.sku_map)
        self.assertFalse(ok)
        self.assertIn("承重超限", reason or "")

        val_res = self.validator.validate(self.container, [p_fragile, cand_heavy], self.sku_map)
        self.assertFalse(val_res.is_valid)
        self.assertTrue(any(v.violation_type == ViolationType.BEARING_EXCEEDED for v in val_res.violations))

    # -------------------------------------------------------------------------
    # 8. 0.5g 纵向减速倾覆安全同构性
    # -------------------------------------------------------------------------
    def test_tipping_safety_consistency(self):
        """测试高瘦件防倾覆：无前向支撑拦截，贴门或有前向贴靠放行同构性"""
        # sku_slender: dx=0.3, dy=1.0, dz=1.0 -> SF = 2 * 0.3 / 1.0 = 0.60 < 1.50
        # 1. 孤立摆放在 x=2.0 (远离门区，无前向货物): 拦截 UNSTABLE_PLACEMENT
        cand_lone = {"x": 2.0, "y": 0.0, "z": 0.0, "dx": 0.3, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_SLENDER", "weight_kg": 80.0}
        ok, sf, _ = check_tipping_safety(cand_lone, [], container_length=12.0)
        self.assertFalse(ok)
        self.assertAlmostEqual(sf, 0.60, places=2)

        val_res = self.validator.validate(self.container, [cand_lone], self.sku_map)
        self.assertFalse(val_res.is_valid)
        self.assertTrue(any(v.violation_type == ViolationType.UNSTABLE_PLACEMENT for v in val_res.violations))

        # 2. 前方 (+X 方向) 有箱体贴靠阻挡 (x=2.3): 放行
        blocker = {"x": 2.3, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE", "weight_kg": 100.0}
        ok, sf, _ = check_tipping_safety(cand_lone, [blocker], container_length=12.0)
        self.assertTrue(ok)

        # 3. 摆在门边 (x = 12.0 - 0.3 = 11.7m): 门结构阻挡，放行
        cand_door = {"x": 11.7, "y": 0.0, "z": 0.0, "dx": 0.3, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_SLENDER", "weight_kg": 80.0}
        ok, sf, _ = check_tipping_safety(cand_door, [], container_length=12.0)
        self.assertTrue(ok)

    # -------------------------------------------------------------------------
    # 9. 门区隔离与禁入门禁同构性
    # -------------------------------------------------------------------------
    def test_door_zone_lockout_consistency(self):
        """测试门区隔离门禁：普通货物禁止进入门区，门区专属件放行"""
        # door_zone_length_m = 1.2m, cL = 12.0m -> 门区起始 x = 10.8m
        # 普通箱体放置在 x=11.0 (越界进入门区): 拦截
        cand_invader = {"x": 11.0, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE", "weight_kg": 100.0}
        ok, _ = check_business_constraints(
            cand_invader, [], self.sku_cube, self.container,
            door_zone_length=1.2, has_door_skus=True
        )
        self.assertFalse(ok)

        val_res = self.validator.validate(self.container, [cand_invader], self.sku_map)
        self.assertFalse(val_res.is_valid)
        self.assertTrue(any(v.violation_type == ViolationType.DOOR_LOCKOUT_VIOLATION for v in val_res.violations))

        # 门区专属件放置在 x=11.5: 放行
        cand_seal = {"x": 11.5, "y": 0.0, "z": 0.0, "dx": 0.5, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_DOOR_SEAL", "weight_kg": 30.0}
        ok, _ = check_business_constraints(
            cand_seal, [], self.sku_door_seal, self.container,
            door_zone_length=1.2, has_door_skus=True
        )
        self.assertTrue(ok)

    # -------------------------------------------------------------------------
    # 10. 全局端到端：内核聚合预检放行方案 -> 独立验证器必为 0 违规保证
    # -------------------------------------------------------------------------
    def test_end_to_end_feasibility_zero_violation_guarantee(self):
        """测试端到端连续放置：内核逐箱预检放行的完整装柜方案，验证器必须 100% 审计通过 (0 违规保证)"""
        current_placements = []
        current_payload_w = 0.0

        candidates_sequence = [
            # 基础地面层
            {"x": 0.0, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE", "weight_kg": 100.0, "placement_id": "p1"},
            {"x": 1.0, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE", "weight_kg": 100.0, "placement_id": "p2"},
            {"x": 0.0, "y": 1.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE", "weight_kg": 100.0, "placement_id": "p3"},
            {"x": 1.0, "y": 1.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE", "weight_kg": 100.0, "placement_id": "p4"},
            # 地面落地专属件 (第 1 层)
            {"x": 2.0, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_FLOOR", "weight_kg": 150.0, "placement_id": "p5"},
            # 地面落地专属件 (第 2 层自叠)
            {"x": 2.0, "y": 0.0, "z": 1.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_FLOOR", "weight_kg": 150.0, "placement_id": "p6"},
            # 支撑层上的立方体 (第 2 层)
            {"x": 0.0, "y": 0.0, "z": 1.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE", "weight_kg": 100.0, "placement_id": "p7"},
            {"x": 1.0, "y": 0.0, "z": 1.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_CUBE", "weight_kg": 100.0, "placement_id": "p8"},
            # 紧贴门区的封门件 (SF = 2 * 0.5 / 1.0 = 1.0 < 1.5, 但 x + dx = 12.0 贴门阻挡)
            {"x": 11.5, "y": 0.0, "z": 0.0, "dx": 0.5, "dy": 1.0, "dz": 1.0, "sku_id": "SKU_DOOR_SEAL", "weight_kg": 30.0, "placement_id": "p9"},
        ]

        # 逐个通过物理内核进行前置校验
        for cand in candidates_sequence:
            is_feasible, viol_type, reason = check_placement_feasibility(
                candidate=cand,
                placements=current_placements,
                container_spec=self.container,
                cargo_specs=self.sku_map,
                current_payload_weight=current_payload_w,
                door_zone_length=1.2,
                has_door_skus=True,
                check_tipping=True,
            )
            self.assertTrue(is_feasible, f"Candidate {cand['placement_id']} 被内核误拦截: {viol_type} - {reason}")
            current_placements.append(cand)
            current_payload_w += cand["weight_kg"]

        # 将内核放行的全量结果提交给独立验证器执行终审
        val_result = self.validator.validate(
            container=self.container,
            placements=current_placements,
            cargo_list=self.sku_map,
        )

        # 必须 100% 审计通过，违规数必须严格为 0
        self.assertTrue(val_result.is_valid, f"验证器检出违规: {[v.message for v in val_result.violations]}")
        self.assertEqual(len(val_result.violations), 0)


if __name__ == "__main__":
    unittest.main()
