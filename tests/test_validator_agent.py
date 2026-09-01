"""
Comprehensive Unit Tests for Independent Global Validator (Solver V2 - Agent 06).
Validates:
- Container bounds violations (all 6 directions)
- Pairwise collision overlaps & exact penetration volume calculations
- Max payload weight enforcement
- Orientation legality & context constraints (Upright, Flat, Side)
- Zone restrictions & Door zone lockouts
- Must-be-on-floor & No-top-stacking constraints
- Support ratio calculations & floating box detection
- Bearing weight & pressure limits
- Stack layer depth limits
- Quantity plans & unknown SKU checks
- Independent topological enclosed cavity & dead-space analysis
- Absolute rejection of invalid solver outputs claiming success
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
    StackingPolicy,
    QuantityPlan,
    ContainerSpec,
    CargoSKU,
    Placement,
    PlacementContext,
    ZoneType,
    PackingRole,
)
from backend.solver_v2.validation.types import (
    ViolationType,
    ViolationSeverity,
    ValidationResult,
)
from backend.solver_v2.validation.independent_validator import (
    IndependentGlobalValidator,
)


class TestIndependentGlobalValidator(unittest.TestCase):
    def setUp(self):
        # Canonical container 10.0m (L) x 2.4m (W) x 2.6m (H)
        self.container = ContainerSpec(
            code="40HQ_TEST",
            inner_dim=BoxDim(x=10.0, y=2.4, z=2.6),
            max_payload_kg=20000.0,
            door_zone_length_m=1.2,
            rear_zone_length_m=1.5,
        )

        # Standard SKU: 1.0 x 1.2 x 1.3, 100 kg
        self.sku_std = CargoSKU(
            sku_id="SKU_STD",
            name="Standard Box",
            box=BoxDim(x=1.0, y=1.2, z=1.3),
            weight_kg=100.0,
            quantity=QuantityPlan(required=10, max_quantity=20),
            orientation_policy=OrientationPolicy(
                allow_upright=True,
                allow_flat=True,
                allow_side=False,
                allowed_contexts_for_flat=(PlacementContext.TOP_FILL,),
            ),
            stacking_policy=StackingPolicy(
                max_stack_layers=3,
                max_bearing_kg=500.0,
                max_pressure_kg_m2=1000.0,
                min_support_ratio=0.70,
                allow_stacking_on_top=True,
                must_be_on_floor=False,
            ),
            packing_roles=(PackingRole.MAIN_WALL,),
        )

        # Fragile SKU: Must be on floor, no stacking on top, upright only
        self.sku_fragile = CargoSKU(
            sku_id="SKU_FRAGILE",
            name="Fragile Equipment",
            box=BoxDim(x=1.5, y=1.0, z=1.0),
            weight_kg=300.0,
            quantity=QuantityPlan(required=2),
            orientation_policy=OrientationPolicy(allow_upright=True, allow_flat=False, allow_side=False),
            stacking_policy=StackingPolicy(
                max_bearing_kg=0.0,
                allow_stacking_on_top=False,
                must_be_on_floor=True,
            ),
            packing_roles=(PackingRole.FOUNDATION,),
        )

        # Door Seal SKU: allowed in door zone
        self.sku_door_seal = CargoSKU(
            sku_id="SKU_DOOR_SEAL",
            name="Door Seal Bag",
            box=BoxDim(x=0.5, y=1.2, z=1.3),
            weight_kg=20.0,
            quantity=QuantityPlan(required=5),
            packing_roles=(PackingRole.DOOR_SEAL,),
            target_zone=ZoneType.DOOR,
        )

        self.validator = IndependentGlobalValidator(grid_resolution=0.2)

    def test_valid_solution_passes(self):
        """测试完全合法的方案：无重叠、无越界、支撑充足、规则满足"""
        p1 = Placement(
            placement_id="p1",
            instance_id="i1",
            sku_id="SKU_STD",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.2, dz=1.3, is_upright=True),
            weight_kg=100.0,
            context=PlacementContext.FOUNDATION,
        )
        p2 = Placement(
            placement_id="p2",
            instance_id="i2",
            sku_id="SKU_STD",
            position=Point3D(0.0, 0.0, 1.3),
            orientation=Orientation3D(dx=1.0, dy=1.2, dz=1.3, is_upright=True),
            weight_kg=100.0,
            context=PlacementContext.MAIN_WALL,
        )
        res = self.validator.validate(
            container=self.container,
            placements=[p1, p2],
            cargo_list=[self.sku_std],
        )
        self.assertTrue(res.is_valid)
        self.assertEqual(len(res.violations), 0)
        self.assertEqual(len(res.rejection_reasons), 0)
        self.assertEqual(res.metrics["overlap_pair_count"], 0)
        self.assertEqual(res.metrics["penetration_volume"], 0.0)
        self.assertGreater(res.metrics["volume_utilization_pct"], 0.0)

    def test_out_of_bounds_rejection(self):
        """测试边界越界检测（包含 min < 0 和 max > L 两个方向）"""
        # Exceeds max_x (10.5 > 10.0)
        p_oob_x = Placement(
            placement_id="p_oob",
            instance_id="i1",
            sku_id="SKU_STD",
            position=Point3D(9.5, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.2, dz=1.3),
            weight_kg=100.0,
            context=PlacementContext.GENERAL,
        )
        res = self.validator.validate(
            container=self.container,
            placements=[p_oob_x],
            cargo_list=[self.sku_std],
        )
        self.assertFalse(res.is_valid)
        self.assertIn("CONTAINER_BOUNDS_EXCEEDED", res.rejection_reasons)
        self.assertEqual(len(res.bounds_violations), 1)

        # Exceeds min_y (< 0)
        p_oob_y = Placement(
            placement_id="p_oob_y",
            instance_id="i2",
            sku_id="SKU_STD",
            position=Point3D(0.0, -0.5, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.2, dz=1.3),
            weight_kg=100.0,
            context=PlacementContext.GENERAL,
        )
        res_y = self.validator.validate(
            container=self.container,
            placements=[p_oob_y],
            cargo_list=[self.sku_std],
        )
        self.assertFalse(res_y.is_valid)
        self.assertIn("CONTAINER_BOUNDS_EXCEEDED", res_y.rejection_reasons)

    def test_pairwise_collision_and_exact_penetration_volume(self):
        """测试碰撞重叠检测与精确穿透体积计算"""
        # Box 1: [0, 1.0] x [0, 1.2] x [0, 1.3]
        p1 = Placement(
            placement_id="p1",
            instance_id="i1",
            sku_id="SKU_STD",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.2, dz=1.3),
            weight_kg=100.0,
            context=PlacementContext.FOUNDATION,
        )
        # Box 2: [0.5, 1.5] x [0.6, 1.8] x [0.3, 1.6]
        # Overlap region: [0.5, 1.0] (0.5) x [0.6, 1.2] (0.6) x [0.3, 1.3] (1.0)
        # Expected penetration vol = 0.5 * 0.6 * 1.0 = 0.30 m³
        p2 = Placement(
            placement_id="p2",
            instance_id="i2",
            sku_id="SKU_STD",
            position=Point3D(0.5, 0.6, 0.3),
            orientation=Orientation3D(dx=1.0, dy=1.2, dz=1.3),
            weight_kg=100.0,
            context=PlacementContext.FOUNDATION,
        )
        res = self.validator.validate(
            container=self.container,
            placements=[p1, p2],
            cargo_list=[self.sku_std],
        )
        self.assertFalse(res.is_valid)
        self.assertIn("COLLISION_OVERLAP_DETECTED", res.rejection_reasons)
        self.assertEqual(res.metrics["overlap_pair_count"], 1)
        self.assertAlmostEqual(res.metrics["penetration_volume"], 0.30, places=4)

    def test_max_payload_exceeded(self):
        """测试载重超限驳回"""
        # Container payload = 20000.0 kg. Place 21 boxes of 1000kg
        heavy_sku = CargoSKU(
            sku_id="SKU_HEAVY",
            name="Heavy Machine",
            box=BoxDim(x=0.5, y=0.5, z=0.5),
            weight_kg=1000.0,
            quantity=QuantityPlan(required=25),
        )
        placements = [
            Placement(
                placement_id=f"p_{i}",
                instance_id=f"i_{i}",
                sku_id="SKU_HEAVY",
                position=Point3D(i * 0.4, 0.0, 0.0),
                orientation=Orientation3D(dx=0.4, dy=0.4, dz=0.4),
                weight_kg=1000.0,
                context=PlacementContext.FOUNDATION,
            )
            for i in range(21)
        ]
        res = self.validator.validate(
            container=self.container,
            placements=placements,
            cargo_list=[heavy_sku],
        )
        self.assertFalse(res.is_valid)
        self.assertIn("MAX_PAYLOAD_EXCEEDED", res.rejection_reasons)
        self.assertGreater(res.metrics["total_cargo_weight_kg"], 20000.0)

    def test_forbidden_orientation_rejection(self):
        """测试非法旋转驳回：SKU_FRAGILE 禁止平放/侧放，只允许立放 (dz=1.0)"""
        # Attempt to place fragile box flat (dz=1.5 or dz=1.0 rotated)
        p_flat = Placement(
            placement_id="p_flat",
            instance_id="i1",
            sku_id="SKU_FRAGILE",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.5, dz=1.0, is_upright=False, is_flat=True),
            weight_kg=300.0,
            context=PlacementContext.FOUNDATION,
        )
        # Note: box is 1.5 x 1.0 x 1.0. If dx=1.0, dy=1.0, dz=1.5 (dz is 1.5, side/flat)
        p_side = Placement(
            placement_id="p_side",
            instance_id="i1",
            sku_id="SKU_FRAGILE",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.0, dz=1.5),
            weight_kg=300.0,
            context=PlacementContext.FOUNDATION,
        )
        res = self.validator.validate(
            container=self.container,
            placements=[p_side],
            cargo_list=[self.sku_fragile],
        )
        self.assertFalse(res.is_valid)
        self.assertIn("FORBIDDEN_ORIENTATION_DETECTED", res.rejection_reasons)
        self.assertEqual(len(res.orientation_violations), 1)

    def test_orientation_context_restriction(self):
        """测试旋转场景限制：SKU_STD 允许平躺但仅限 TOP_FILL 上层填充，主墙区 FOUNDATION 时平躺应被驳回"""
        # SKU_STD base is (1.0, 1.2, 1.3). Flat orientation has dz=1.2
        p_flat_wrong_ctx = Placement(
            placement_id="p_flat",
            instance_id="i1",
            sku_id="SKU_STD",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.3, dz=1.2),
            weight_kg=100.0,
            context=PlacementContext.FOUNDATION,  # Forbidden context for flat
        )
        res = self.validator.validate(
            container=self.container,
            placements=[p_flat_wrong_ctx],
            cargo_list=[self.sku_std],
        )
        self.assertFalse(res.is_valid)
        self.assertIn("FORBIDDEN_ORIENTATION_DETECTED", res.rejection_reasons)

        # Placed in TOP_FILL context: should be permitted
        p_flat_topfill = Placement(
            placement_id="p_flat2",
            instance_id="i2",
            sku_id="SKU_STD",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.3, dz=1.2),
            weight_kg=100.0,
            context=PlacementContext.TOP_FILL,  # Allowed context
        )
        res2 = self.validator.validate(
            container=self.container,
            placements=[p_flat_topfill],
            cargo_list=[self.sku_std],
        )
        self.assertTrue(res2.is_valid)

    def test_door_lockout_violation(self):
        """测试门区封锁（Door Lockout）：非 DOOR_SEAL 货物侵入门区 [Lx - door_zone_len, Lx] 必须被驳回"""
        # Door start = 10.0 - 1.2 = 8.8m. Placement at x = 9.0 penetrates door zone
        p_std_at_door = Placement(
            placement_id="p_door_fail",
            instance_id="i1",
            sku_id="SKU_STD",
            position=Point3D(9.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.2, dz=1.3),
            weight_kg=100.0,
            context=PlacementContext.MAIN_WALL,
        )
        res = self.validator.validate(
            container=self.container,
            placements=[p_std_at_door],
            cargo_list=[self.sku_std, self.sku_door_seal],
        )
        self.assertFalse(res.is_valid)
        self.assertIn(ViolationType.DOOR_LOCKOUT_VIOLATION.value, res.rejection_reasons)

        # SKU_DOOR_SEAL placed at door zone: must succeed
        p_seal_at_door = Placement(
            placement_id="p_seal",
            instance_id="i2",
            sku_id="SKU_DOOR_SEAL",
            position=Point3D(9.0, 0.0, 0.0),
            orientation=Orientation3D(dx=0.5, dy=1.2, dz=1.3),
            weight_kg=20.0,
            context=PlacementContext.DOOR_SEAL,
        )
        res_seal = self.validator.validate(
            container=self.container,
            placements=[p_seal_at_door],
            cargo_list=[self.sku_door_seal],
        )
        self.assertTrue(res_seal.is_valid)

    def test_floating_box_and_insufficient_support(self):
        """测试悬空放置与支撑率不足判定"""
        # Case 1: Pure floating box at z = 1.3 with 0 support
        p_floating = Placement(
            placement_id="p_float",
            instance_id="i1",
            sku_id="SKU_STD",
            position=Point3D(0.0, 0.0, 1.3),
            orientation=Orientation3D(dx=1.0, dy=1.2, dz=1.3),
            weight_kg=100.0,
            context=PlacementContext.MAIN_WALL,
        )
        res_float = self.validator.validate(
            container=self.container,
            placements=[p_floating],
            cargo_list=[self.sku_std],
        )
        self.assertFalse(res_float.is_valid)
        self.assertIn(ViolationType.INSUFFICIENT_SUPPORT.value, res_float.rejection_reasons)

        # Case 2: Partial support below required 70% (e.g. only 20% overlap)
        # Base box at (0.0, 0.0, 0.0) with (1.0, 1.2, 1.3)
        # Upper box at (0.8, 0.0, 1.3) with (1.0, 1.2, 1.3) -> contact x in [0.8, 1.0] (0.2), area 0.2*1.2 = 0.24 (20%)
        p_base = Placement(
            placement_id="p_base",
            instance_id="i1",
            sku_id="SKU_STD",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.2, dz=1.3),
            weight_kg=100.0,
            context=PlacementContext.FOUNDATION,
        )
        p_partial = Placement(
            placement_id="p_partial",
            instance_id="i2",
            sku_id="SKU_STD",
            position=Point3D(0.8, 0.0, 1.3),
            orientation=Orientation3D(dx=1.0, dy=1.2, dz=1.3),
            weight_kg=100.0,
            context=PlacementContext.MAIN_WALL,
        )
        res_partial = self.validator.validate(
            container=self.container,
            placements=[p_base, p_partial],
            cargo_list=[self.sku_std],
        )
        self.assertFalse(res_partial.is_valid)
        self.assertIn(ViolationType.INSUFFICIENT_SUPPORT.value, res_partial.rejection_reasons)

    def test_floor_only_and_no_top_stacking(self):
        """测试必须落地与禁止顶部叠放约束"""
        # Case 1: Fragile SKU placed off-floor at z = 1.0
        p_base = Placement(
            placement_id="p_base",
            instance_id="i1",
            sku_id="SKU_STD",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.5, dy=1.0, dz=1.0),
            weight_kg=100.0,
            context=PlacementContext.FOUNDATION,
        )
        p_fragile_off_floor = Placement(
            placement_id="p_fr",
            instance_id="i2",
            sku_id="SKU_FRAGILE",
            position=Point3D(0.0, 0.0, 1.0),
            orientation=Orientation3D(dx=1.5, dy=1.0, dz=1.0),
            weight_kg=300.0,
            context=PlacementContext.MAIN_WALL,
        )
        res_floor = self.validator.validate(
            container=self.container,
            placements=[p_base, p_fragile_off_floor],
            cargo_list=[self.sku_std, self.sku_fragile],
        )
        self.assertFalse(res_floor.is_valid)
        self.assertIn(ViolationType.FLOOR_ONLY_VIOLATION.value, res_floor.rejection_reasons)

        # Case 2: Fragile SKU placed on floor, but another box stacked on top of it
        p_fragile_on_floor = Placement(
            placement_id="p_fr_floor",
            instance_id="i3",
            sku_id="SKU_FRAGILE",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.5, dy=1.0, dz=1.0),
            weight_kg=300.0,
            context=PlacementContext.FOUNDATION,
        )
        p_on_top = Placement(
            placement_id="p_top",
            instance_id="i4",
            sku_id="SKU_STD",
            position=Point3D(0.0, 0.0, 1.0),
            orientation=Orientation3D(dx=1.0, dy=1.0, dz=1.0),
            weight_kg=100.0,
            context=PlacementContext.MAIN_WALL,
        )
        res_notop = self.validator.validate(
            container=self.container,
            placements=[p_fragile_on_floor, p_on_top],
            cargo_list=[self.sku_std, self.sku_fragile],
        )
        self.assertFalse(res_notop.is_valid)
        self.assertIn(ViolationType.NO_TOP_STACK_VIOLATION.value, res_notop.rejection_reasons)

    def test_stack_depth_limit(self):
        """测试垂直堆叠层数超限判定"""
        # SKU_STD max_stack_layers = 3. Stack 4 boxes
        placements = [
            Placement(
                placement_id=f"p_{i}",
                instance_id=f"i_{i}",
                sku_id="SKU_STD",
                position=Point3D(0.0, 0.0, i * 0.6),
                orientation=Orientation3D(dx=1.0, dy=1.2, dz=0.6),
                weight_kg=50.0,
                context=PlacementContext.FOUNDATION if i == 0 else PlacementContext.MAIN_WALL,
            )
            for i in range(4)
        ]
        res = self.validator.validate(
            container=self.container,
            placements=placements,
            cargo_list=[self.sku_std],
        )
        self.assertFalse(res.is_valid)
        self.assertIn(ViolationType.STACK_LIMIT_VIOLATION.value, res.rejection_reasons)

    def test_stack_layer_limit_is_sku_self_limit_not_mixed_column_limit(self):
        """A lower SKU's self-layer cap must not forbid a legal different SKU above."""
        container = ContainerSpec("MIXED_STACK", BoxDim(1.0, 1.0, 2.0), 5000.0, door_zone_length_m=0.0)
        lower = CargoSKU(
            "LOWER", "Lower", BoxDim(1.0, 1.0, 0.5), 10.0, QuantityPlan(3),
            stacking_policy=StackingPolicy(max_stack_layers=3, max_bearing_kg=100.0),
        )
        upper = CargoSKU(
            "UPPER", "Upper", BoxDim(1.0, 1.0, 0.5), 5.0, QuantityPlan(1),
            stacking_policy=StackingPolicy(max_stack_layers=1),
        )
        orientation = Orientation3D(1.0, 1.0, 0.5, "UPRIGHT_NORMAL")
        placements = [
            Placement(f"lower_{i}", f"lower_i_{i}", "LOWER", Point3D(0, 0, i * .5),
                      orientation, 10.0, PlacementContext.MAIN_WALL, i)
            for i in range(3)
        ] + [Placement("upper_0", "upper_i_0", "UPPER", Point3D(0, 0, 1.5),
                       orientation, 5.0, PlacementContext.MAIN_WALL, 3)]
        result = self.validator.validate(container, placements, [lower, upper])
        self.assertTrue(result.is_valid, result.to_dict())

    def test_independent_cavity_detection(self):
        """测试独立 3D 拓扑泛洪封闭死腔检测"""
        # Container is 10.0 x 2.4 x 2.6. Door is at x = 10.0.
        # Construct a solid blocking wall at x in [3.0, 4.0] spanning entire Y and Z:
        # Leaves x in [0.0, 3.0] completely sealed behind the wall
        p_wall = Placement(
            placement_id="wall_block",
            instance_id="i_wall",
            sku_id="SKU_STD",
            position=Point3D(3.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=2.4, dz=2.6),
            weight_kg=500.0,
            context=PlacementContext.MAIN_WALL,
        )
        res = self.validator.validate(
            container=self.container,
            placements=[p_wall],
            cargo_list=[self.sku_std],
        )
        # Even if valid geometrically, metrics must detect the enclosed cavity
        self.assertGreater(res.metrics["enclosed_cavity_count"], 0)
        self.assertGreater(res.metrics["enclosed_cavity_volume"], 15.0)

    def test_reject_solver_false_success_claim(self):
        """
        必须能够果断驳回声称成功的错误求解器输出（如虚假利用率、微量穿透或悬空）。
        """
        # Mock a solver output claiming 90% utilization and "SUCCESS" status
        solver_output = {
            "status": "SUCCESS",
            "solver_claimed_utilization": 92.5,
            "container": (10.0, 2.4, 2.6),
            "placements": [
                # Placement 1
                {"x": 0.0, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.2, "dz": 1.3, "sku_id": "SKU_STD", "weight_kg": 100.0},
                # Placement 2 with subtle 2cm collision penetration: x=0.98 < 1.0
                {"x": 0.98, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.2, "dz": 1.3, "sku_id": "SKU_STD", "weight_kg": 100.0},
            ],
        }

        res = self.validator.validate(
            container=solver_output["container"],
            placements=solver_output["placements"],
            cargo_list=[self.sku_std],
        )

        self.assertFalse(res.is_valid)
        self.assertIn("COLLISION_OVERLAP_DETECTED", res.rejection_reasons)
        self.assertGreater(res.metrics["penetration_volume"], 0.0)

    def test_p0_1_cavity_volume_activation_unit_test(self):
        """
        P0-1 Guardrail: When max_allowed_cavity_volume is activated on IndependentGlobalValidator,
        3D voxel flood-fill must execute without crash and reject trapped cavities.
        """
        active_cavity_validator = IndependentGlobalValidator(max_allowed_cavity_volume=0.015)
        
        sku_wall = CargoSKU(
            sku_id="SKU_WALL",
            name="Wall Structure",
            box=BoxDim(1.0, 2.4, 2.6),
            weight_kg=500.0,
            quantity=QuantityPlan(required=1),
        )
        
        # Construct an enclosed hollow cavity behind a sealed cargo wall
        p_wall = Placement(
            placement_id="p_wall_seal",
            instance_id="inst_wall",
            sku_id="SKU_WALL",
            position=Point3D(3.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=2.4, dz=2.6),
            weight_kg=500.0,
            context=PlacementContext.MAIN_WALL,
        )
        
        res = active_cavity_validator.validate(
            container=self.container,
            placements=[p_wall],
            cargo_list=[sku_wall],
        )
        
        # Must execute without KeyError/NameError crash and reject due to trapped space
        self.assertFalse(res.is_valid)
        self.assertIn("ENCLOSED_CAVITY_LIMIT_EXCEEDED", res.rejection_reasons)
        self.assertGreater(res.metrics["enclosed_cavity_volume"], 10.0)

    def test_dag_stack_column_depth_multi_box_support(self):
        """
        P1-3 Guardrail: DAG DP must trace the longest support chain in multi-box support,
        not stopping greedily on shorter branches.
        """
        sku_stack_limited = CargoSKU(
            sku_id="SKU_STACK3",
            name="Stack Limited Box",
            box=BoxDim(0.5, 0.5, 0.3),
            weight_kg=10.0,
            quantity=QuantityPlan(required=10),
            stacking_policy=StackingPolicy(max_stack_layers=3),
        )
        
        # Pillar 1 (Left): 4 boxes tall (depth=4) -> z: 0.0, 0.3, 0.6, 0.9
        # Pillar 2 (Right): 1 box on platform -> at x=0.4, z=0.9
        # Top Box: at x=0.2, z=1.2 (spanning across both Pillar 1 and Pillar 2)
        placements = [
            Placement("p0", "i0", "SKU_STACK3", Point3D(0.0, 0.0, 0.0), Orientation3D(0.5, 0.5, 0.3), 10.0, PlacementContext.MAIN_WALL),
            Placement("p1", "i1", "SKU_STACK3", Point3D(0.0, 0.0, 0.3), Orientation3D(0.5, 0.5, 0.3), 10.0, PlacementContext.MAIN_WALL),
            Placement("p2", "i2", "SKU_STACK3", Point3D(0.0, 0.0, 0.6), Orientation3D(0.5, 0.5, 0.3), 10.0, PlacementContext.MAIN_WALL),
            Placement("p3", "i3", "SKU_STACK3", Point3D(0.0, 0.0, 0.9), Orientation3D(0.5, 0.5, 0.3), 10.0, PlacementContext.MAIN_WALL),
            Placement("p4", "i4", "SKU_STACK3", Point3D(0.4, 0.0, 0.9), Orientation3D(0.5, 0.5, 0.3), 10.0, PlacementContext.MAIN_WALL),
            Placement("p5", "i5", "SKU_STACK3", Point3D(0.2, 0.0, 1.2), Orientation3D(0.5, 0.5, 0.3), 10.0, PlacementContext.MAIN_WALL),
        ]
        
        res = self.validator.validate(
            container=self.container,
            placements=placements,
            cargo_list=[sku_stack_limited],
        )
        
        # Max stack depth is 5 layers (exceeding limit of 3)
        self.assertFalse(res.is_valid)
        self.assertIn(ViolationType.STACK_LIMIT_VIOLATION.value, res.rejection_reasons)

    def test_stepped_support_ratio_multi_box_contact(self):
        """
        P1-2 Guardrail: Upper box resting across two coplanar lower boxes must have
        combined support area aggregated correctly and capped at 1.0 (100%).
        """
        sku_cube = CargoSKU(
            sku_id="SKU_CUBE",
            name="Cube Unit",
            box=BoxDim(0.5, 0.5, 0.5),
            weight_kg=10.0,
            quantity=QuantityPlan(required=3),
        )
        p_lower1 = Placement("pl1", "i1", "SKU_CUBE", Point3D(0.0, 0.0, 0.0), Orientation3D(0.5, 0.5, 0.5), 10.0, PlacementContext.MAIN_WALL)
        p_lower2 = Placement("pl2", "i2", "SKU_CUBE", Point3D(0.5, 0.0, 0.0), Orientation3D(0.5, 0.5, 0.5), 10.0, PlacementContext.MAIN_WALL)
        # Upper box centered across both lower boxes
        p_upper = Placement("pu1", "i3", "SKU_CUBE", Point3D(0.25, 0.0, 0.5), Orientation3D(0.5, 0.5, 0.5), 10.0, PlacementContext.MAIN_WALL)
        
        res = self.validator.validate(
            container=self.container,
            placements=[p_lower1, p_lower2, p_upper],
            cargo_list=[sku_cube],
        )
        self.assertTrue(res.is_valid)

    def test_square_and_cube_symmetric_orientations(self):
        """
        P2-5 Guardrail: Square-base and cube cargo must resolve orientation checks
        without symmetric dimension collision or false rejections.
        """
        sku_square = CargoSKU(
            sku_id="SKU_SQUARE",
            name="Square Base Item",
            box=BoxDim(0.4, 0.4, 0.6),
            weight_kg=10.0,
            quantity=QuantityPlan(required=2),
        )
        p_sq1 = Placement("psq1", "i1", "SKU_SQUARE", Point3D(0.0, 0.0, 0.0), Orientation3D(0.4, 0.4, 0.6), 10.0, PlacementContext.MAIN_WALL)
        p_sq2 = Placement("psq2", "i2", "SKU_SQUARE", Point3D(0.4, 0.0, 0.0), Orientation3D(0.4, 0.4, 0.6), 10.0, PlacementContext.MAIN_WALL)
        
        res = self.validator.validate(
            container=self.container,
            placements=[p_sq1, p_sq2],
            cargo_list=[sku_square],
        )
        self.assertTrue(res.is_valid)


if __name__ == "__main__":
    unittest.main()
