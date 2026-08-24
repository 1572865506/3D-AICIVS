"""
Unit and Integration Tests for Solver V2 Domain Models & Constraint Compiler
Tests:
- CargoSKU, Container, QuantityPlan, OrientationPolicy, StackingPolicy
- Asymmetric dimension preservation and canonical axes
- Input Normalization & Chinese requirement parsing only in Adapter
- Constraint Compiler and problem hash determinism
"""
import unittest
import json
import os
import sys

# Ensure root in sys.path
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
    CargoClass,
    PackingRole,
    PlacementContext,
    PlacementRuleMode,
    ZoneType,
    Placement,
    compute_problem_hash,
)
from backend.solver_v2.constraints.rules import (
    ConstraintType,
    ZoneConstraint,
    DoorZoneConstraint,
    StackLimitConstraint,
    BearingConstraint,
    PressureConstraint,
    SupportRatioConstraint,
)
from backend.solver_v2.constraints.compiler import ConstraintCompiler
from backend.solver_v2.api.adapter import InputNormalizer, InputAdapter


class TestDomainModels(unittest.TestCase):
    def test_box_dim_and_volume(self):
        box = BoxDim(x=1.2, y=0.8, z=0.5)
        self.assertAlmostEqual(box.volume, 1.2 * 0.8 * 0.5)
        with self.assertRaises(ValueError):
            BoxDim(x=1.0, y=-0.5, z=0.2)

    def test_quantity_plan(self):
        qp = QuantityPlan(required=10, min_quantity=5, max_quantity=20, is_elastic=True)
        self.assertEqual(qp.required, 10)
        self.assertEqual(qp.min_quantity, 5)
        self.assertTrue(qp.is_elastic)
        with self.assertRaises(ValueError):
            QuantityPlan(required=-1)
        with self.assertRaises(ValueError):
            QuantityPlan(required=10, min_quantity=15)

    def test_orientation_policy_context_dependent(self):
        # Asymmetric box: x=1.0, y=0.5, z=0.3
        box = BoxDim(x=1.0, y=0.5, z=0.3)
        policy = OrientationPolicy(
            allow_upright=True,
            allow_flat=True,
            allow_side=False,
            allowed_contexts_for_flat=(PlacementContext.TOP_FILL,)
        )

        # In MAIN_WALL context: only upright orientations allowed
        oris_main = policy.get_legal_orientations(box, PlacementContext.MAIN_WALL)
        self.assertEqual(len(oris_main), 2)
        for o in oris_main:
            self.assertTrue(o.is_upright)
            self.assertAlmostEqual(o.dz, 0.3)  # height kept upright

        # In TOP_FILL context: flat orientations also unlocked
        oris_top = policy.get_legal_orientations(box, PlacementContext.TOP_FILL)
        self.assertEqual(len(oris_top), 4)  # 2 upright + 2 flat
        flat_oris = [o for o in oris_top if o.is_flat]
        self.assertEqual(len(flat_oris), 2)
        for o in flat_oris:
            self.assertAlmostEqual(o.dz, 0.5)  # y (0.5) placed along z (flat)

    def test_container_spec(self):
        spec = ContainerSpec(
            code="40HQ",
            inner_dim=BoxDim(x=12.032, y=2.352, z=2.698),
            max_payload_kg=26500.0,
            door_zone_length_m=1.2,
            rear_zone_length_m=1.0
        )
        self.assertAlmostEqual(spec.Lx, 12.032)
        self.assertAlmostEqual(spec.Ly, 2.352)
        self.assertAlmostEqual(spec.Lz, 2.698)
        self.assertAlmostEqual(spec.volume, 12.032 * 2.352 * 2.698)

    def test_placement_aabb(self):
        p = Placement(
            placement_id="p_1",
            instance_id="inst_1",
            sku_id="SKU-01",
            position=Point3D(x=1.0, y=2.0, z=0.5),
            orientation=Orientation3D(dx=0.5, dy=0.4, dz=0.3),
            weight_kg=10.0,
            context=PlacementContext.MAIN_WALL
        )
        self.assertEqual(p.aabb(), (1.0, 2.0, 0.5, 1.5, 2.4, 0.8))
        self.assertAlmostEqual(p.volume, 0.5 * 0.4 * 0.3)


class TestInputAdapterAndNormalizer(unittest.TestCase):
    def test_parse_requirements_to_zones_and_roles(self):
        # Rear requirement
        z_rear, r_rear = InputNormalizer.parse_zone_and_roles("放柜子最里面")
        self.assertEqual(z_rear, ZoneType.REAR)
        self.assertIn(PackingRole.FOUNDATION, r_rear)

        # Door seal requirement
        z_door, r_door = InputNormalizer.parse_zone_and_roles("封柜门; 可以减少点")
        self.assertEqual(z_door, ZoneType.DOOR)
        self.assertIn(PackingRole.DOOR_SEAL, r_door)

        # Middle requirement
        z_mid, r_mid = InputNormalizer.parse_zone_and_roles("放中间")
        self.assertEqual(z_mid, ZoneType.MIDDLE)
        self.assertIn(PackingRole.MAIN_WALL, r_mid)

        # Elasticity
        self.assertTrue(InputNormalizer.parse_elasticity("封柜门; 可以减少点"))
        self.assertTrue(InputNormalizer.parse_elasticity("按需装载"))
        self.assertFalse(InputNormalizer.parse_elasticity("放中间"))

    def test_adapter_14sku_benchmark_ingestion(self):
        benchmark_path = os.path.join(
            PROJECT_ROOT, "devkit", "cleanroom_solver_v2_devkit", "benchmarks", "40hq_cleanroom_case_001.json"
        )
        with open(benchmark_path, "r", encoding="utf-8") as f:
            case_data = json.load(f)

        container = InputAdapter.parse_container(case_data["containerSeed"])
        self.assertAlmostEqual(container.Lx, 12.032)
        self.assertAlmostEqual(container.Ly, 2.352)
        self.assertAlmostEqual(container.Lz, 2.698)

        cargo_list = InputAdapter.parse_cargo_list(case_data["cargo"])
        self.assertEqual(len(cargo_list), 14)

        # SKU-01 check (放柜子最里面)
        sku1 = next(c for c in cargo_list if c.sku_id == "SKU-01")
        self.assertEqual(sku1.target_zone, ZoneType.REAR)
        self.assertIn(PackingRole.FOUNDATION, sku1.packing_roles)
        self.assertFalse(sku1.quantity.is_elastic)

        # SKU-14 check (封柜门; 可以减少点)
        sku14 = next(c for c in cargo_list if c.sku_id == "SKU-14")
        self.assertEqual(sku14.target_zone, ZoneType.DOOR)
        self.assertIn(PackingRole.DOOR_SEAL, sku14.packing_roles)
        self.assertTrue(sku14.quantity.is_elastic)
        self.assertEqual(sku14.quantity.required, 674)

        # Check problem hash determinism
        hash1 = compute_problem_hash(container, cargo_list)
        hash2 = compute_problem_hash(container, cargo_list)
        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)


class TestConstraintCompiler(unittest.TestCase):
    def test_compile_constraints_for_benchmark(self):
        container = ContainerSpec(
            code="40HQ",
            inner_dim=BoxDim(x=12.032, y=2.352, z=2.698),
            max_payload_kg=26500.0,
            door_zone_length_m=1.2,
            rear_zone_length_m=1.0
        )
        cargo_items = [
            CargoSKU(
                sku_id="SKU-01",
                name="WIFI",
                box=BoxDim(x=0.5, y=0.5, z=0.5),
                weight_kg=5.0,
                quantity=QuantityPlan(required=1),
                target_zone=ZoneType.REAR,
                packing_roles=(PackingRole.FOUNDATION,)
            ),
            CargoSKU(
                sku_id="SKU-02",
                name="Display Door",
                box=BoxDim(x=0.553, y=0.08, z=0.355),
                weight_kg=8.4,
                quantity=QuantityPlan(required=500),
                target_zone=ZoneType.DOOR,
                packing_roles=(PackingRole.DOOR_SEAL,)
            ),
            CargoSKU(
                sku_id="SKU-05",
                name="Smart Display",
                box=BoxDim(x=0.833, y=0.53, z=0.23),
                weight_kg=20.8,
                quantity=QuantityPlan(required=100),
                target_zone=ZoneType.MIDDLE,
                stacking_policy=StackingPolicy(max_stack_layers=2, max_bearing_kg=100.0),
                packing_roles=(PackingRole.MAIN_WALL,)
            ),
        ]

        compiled = ConstraintCompiler.compile_all(container, cargo_items)

        # 1. Door zone check
        door_constraint: DoorZoneConstraint = compiled["door_zone"]
        self.assertIn("SKU-02", door_constraint.exempt_skus)
        self.assertNotIn("SKU-01", door_constraint.exempt_skus)
        self.assertNotIn("SKU-05", door_constraint.exempt_skus)

        # SKU-02 is allowed in door zone (x = 11.5m, dx = 0.5m -> 12.0m > 10.832m)
        self.assertTrue(door_constraint.is_allowed_in_door_zone("SKU-02", 11.5, 0.5, container.Lx))
        # SKU-05 is NOT allowed in door zone
        self.assertFalse(door_constraint.is_allowed_in_door_zone("SKU-05", 11.5, 0.5, container.Lx))
        # SKU-05 is allowed in middle (x = 5.0m, dx = 0.5m -> 5.5m <= 10.832m)
        self.assertTrue(door_constraint.is_allowed_in_door_zone("SKU-05", 5.0, 0.5, container.Lx))

        # 2. Stacking limits
        stack_limits = compiled["stack_limits"]
        self.assertIn("SKU-05", stack_limits)
        self.assertEqual(stack_limits["SKU-05"].max_layers, 2)

        # 3. Bearing limits
        bearing_limits = compiled["bearing_limits"]
        self.assertIn("SKU-05", bearing_limits)
        self.assertEqual(bearing_limits["SKU-05"].max_bearing_kg, 100.0)


if __name__ == "__main__":
    unittest.main()
