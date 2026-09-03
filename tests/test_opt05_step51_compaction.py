"""
Unit tests for OPT-05 Step 5.1: CompactionPass (Stack Compaction & Space Release).
Verifies:
1. Downward sliding (reduce z) onto ground or supporting lower boxes.
2. Inward sliding (reduce x) towards inner container wall or inner boxes.
3. Strict re-verification of bottom support ratio, bearing limits, stacking rules, and collision.
4. Acceptance criteria: Released usable space >= 0.5 m3.
"""
import unittest

from backend.solver_v2.domain.models import (
    BoxDim,
    CargoSKU,
    ContainerSpec,
    Orientation3D,
    Placement,
    PlacementContext,
    Point3D,
    QuantityPlan,
    StackingPolicy,
)
from backend.solver_v2.solver.compaction import CompactionPass, CompactionResult
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator


class TestCompactionPass(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec(
            code="40HQ",
            inner_dim=BoxDim(12.024, 2.350, 2.690),
            max_payload_kg=26000.0,
        )
        self.compactor = CompactionPass(self.container)

    def test_compaction_releases_at_least_half_cubic_meter(self):
        """
        Acceptance Criteria: Compaction releases >= 0.5 m3 usable space.
        Creates a scenario where boxes are placed with elevated z and x gaps.
        """
        # Base SKU (0.8m x 1.0m x 0.5m)
        sku_base = CargoSKU(
            sku_id="SKU_BASE",
            name="Base Box",
            box=BoxDim(0.80, 1.00, 0.50),
            weight_kg=50.0,
            quantity=QuantityPlan(required=10),
        )
        # Upper SKU (0.8m x 1.0m x 0.4m)
        sku_upper = CargoSKU(
            sku_id="SKU_UPPER",
            name="Upper Box",
            box=BoxDim(0.80, 1.00, 0.40),
            weight_kg=30.0,
            quantity=QuantityPlan(required=10),
        )
        cargo_catalog = [sku_base, sku_upper]

        # 4 lower boxes on floor (z=0.0): 2 in x by 2 in y
        # occupies [0.0..1.6] in x, [0.0..2.0] in y, [0.0..0.5] in z
        placements = [
            Placement(
                placement_id="P_BASE_1",
                instance_id="I_B1",
                sku_id="SKU_BASE",
                position=Point3D(0.0, 0.0, 0.0),
                orientation=Orientation3D(dx=0.80, dy=1.00, dz=0.50),
                weight_kg=50.0,
                context=PlacementContext.FOUNDATION,
            ),
            Placement(
                placement_id="P_BASE_2",
                instance_id="I_B2",
                sku_id="SKU_BASE",
                position=Point3D(0.0, 1.0, 0.0),
                orientation=Orientation3D(dx=0.80, dy=1.00, dz=0.50),
                weight_kg=50.0,
                context=PlacementContext.FOUNDATION,
            ),
            Placement(
                placement_id="P_BASE_3",
                instance_id="I_B3",
                sku_id="SKU_BASE",
                position=Point3D(0.80, 0.0, 0.0),
                orientation=Orientation3D(dx=0.80, dy=1.00, dz=0.50),
                weight_kg=50.0,
                context=PlacementContext.FOUNDATION,
            ),
            Placement(
                placement_id="P_BASE_4",
                instance_id="I_B4",
                sku_id="SKU_BASE",
                position=Point3D(0.80, 1.0, 0.0),
                orientation=Orientation3D(dx=0.80, dy=1.00, dz=0.50),
                weight_kg=50.0,
                context=PlacementContext.FOUNDATION,
            ),
        ]

        # 2 floating boxes placed artificially high at z=1.2 (gap of 0.7m above base boxes at z=0.5)
        # and 2 boxes placed further out at x=3.0 with no obstruction between x=1.6 and x=3.0
        placements.extend([
            Placement(
                placement_id="P_UPPER_1",
                instance_id="I_U1",
                sku_id="SKU_UPPER",
                position=Point3D(0.0, 0.0, 1.20),
                orientation=Orientation3D(dx=0.80, dy=1.00, dz=0.40),
                weight_kg=30.0,
                context=PlacementContext.MAIN_WALL,
            ),
            Placement(
                placement_id="P_UPPER_2",
                instance_id="I_U2",
                sku_id="SKU_UPPER",
                position=Point3D(0.0, 1.0, 1.20),
                orientation=Orientation3D(dx=0.80, dy=1.00, dz=0.40),
                weight_kg=30.0,
                context=PlacementContext.MAIN_WALL,
            ),
            # Floor boxes placed with gap at x=3.0 on ground
            Placement(
                placement_id="P_OUTER_1",
                instance_id="I_O1",
                sku_id="SKU_BASE",
                position=Point3D(3.0, 0.0, 0.0),
                orientation=Orientation3D(dx=0.80, dy=1.00, dz=0.50),
                weight_kg=50.0,
                context=PlacementContext.FOUNDATION,
            ),
            Placement(
                placement_id="P_OUTER_2",
                instance_id="I_O2",
                sku_id="SKU_BASE",
                position=Point3D(3.0, 1.0, 0.0),
                orientation=Orientation3D(dx=0.80, dy=1.00, dz=0.50),
                weight_kg=50.0,
                context=PlacementContext.FOUNDATION,
            ),
        ])

        result: CompactionResult = self.compactor.compact(
            placements=placements,
            cargo_catalog=cargo_catalog,
        )

        print(f"\n[Compaction Test Results]")
        print(f"  Boxes moved: {result.boxes_moved_count}")
        print(f"  Z-reduction: {result.total_z_reduction_m:.3f} m")
        print(f"  X-reduction: {result.total_x_reduction_m:.3f} m")
        print(f"  Released volume: {result.released_volume_m3:.4f} m3")

        # Verify acceptance criteria: released volume >= 0.5 m3
        self.assertGreaterEqual(
            result.released_volume_m3,
            0.50,
            f"Expected released volume >= 0.5 m3, got {result.released_volume_m3:.4f} m3",
        )
        self.assertGreater(result.boxes_moved_count, 0)

        # Verify that upper boxes dropped from z=1.20 to z=0.50
        compacted_map = {p.placement_id: p for p in result.placements}
        self.assertAlmostEqual(compacted_map["P_UPPER_1"].position.z, 0.50, places=4)
        self.assertAlmostEqual(compacted_map["P_UPPER_2"].position.z, 0.50, places=4)

        # Verify that outer boxes slid from x=3.0 to x=1.60
        self.assertAlmostEqual(compacted_map["P_OUTER_1"].position.x, 1.60, places=4)
        self.assertAlmostEqual(compacted_map["P_OUTER_2"].position.x, 1.60, places=4)

        # Independent Validator must confirm entire packed solution is 100% valid
        val_res = IndependentGlobalValidator.validate(
            container=self.container,
            placements=result.placements,
            cargo_list=cargo_catalog,
        )
        self.assertTrue(val_res.is_valid, f"Validation failed: {val_res.rejection_reasons}")

    def test_compaction_preserves_support_and_no_top_stack_rules(self):
        """
        Verifies that boxes will NOT drop onto lower boxes that forbid stacking on top.
        """
        sku_fragile = CargoSKU(
            sku_id="SKU_FRAGILE",
            name="Fragile Box",
            box=BoxDim(1.0, 1.0, 0.6),
            weight_kg=10.0,
            quantity=QuantityPlan(required=1),
            stacking_policy=StackingPolicy(allow_stacking_on_top=False),
        )
        sku_heavy = CargoSKU(
            sku_id="SKU_HEAVY",
            name="Heavy Box",
            box=BoxDim(1.0, 1.0, 0.6),
            weight_kg=40.0,
            quantity=QuantityPlan(required=1),
        )
        cargo_catalog = [sku_fragile, sku_heavy]

        placements = [
            # Fragile box on floor [0..1] x [0..1] x [0..0.6]
            Placement(
                placement_id="P_FRAGILE",
                instance_id="I_F1",
                sku_id="SKU_FRAGILE",
                position=Point3D(0.0, 0.0, 0.0),
                orientation=Orientation3D(dx=1.0, dy=1.0, dz=0.6),
                weight_kg=10.0,
                context=PlacementContext.FOUNDATION,
            ),
            # Heavy box at z=1.5 directly above fragile box
            Placement(
                placement_id="P_HEAVY",
                instance_id="I_H1",
                sku_id="SKU_HEAVY",
                position=Point3D(0.0, 0.0, 1.5),
                orientation=Orientation3D(dx=1.0, dy=1.0, dz=0.6),
                weight_kg=40.0,
                context=PlacementContext.MAIN_WALL,
            ),
        ]

        result = self.compactor.compact(placements=placements, cargo_catalog=cargo_catalog)
        compacted_map = {p.placement_id: p for p in result.placements}

        # The heavy box must NOT drop onto the fragile box at z=0.6
        self.assertNotEqual(compacted_map["P_HEAVY"].position.z, 0.60)

    def test_inward_sliding_along_x(self):
        """
        Tests pure inward sliding along X axis toward x=0.0.
        """
        sku = CargoSKU(
            sku_id="SKU_STD",
            name="Std Box",
            box=BoxDim(1.0, 1.0, 1.0),
            weight_kg=20.0,
            quantity=QuantityPlan(required=3),
        )
        # Box placed on floor at x=4.0
        placements = [
            Placement(
                placement_id="P1",
                instance_id="I1",
                sku_id="SKU_STD",
                position=Point3D(4.0, 0.0, 0.0),
                orientation=Orientation3D(dx=1.0, dy=1.0, dz=1.0),
                weight_kg=20.0,
                context=PlacementContext.FOUNDATION,
            )
        ]

        result = self.compactor.compact(placements=placements, cargo_catalog=[sku])
        p1_compacted = result.placements[0]
        self.assertAlmostEqual(p1_compacted.position.x, 0.0, places=4)
        self.assertAlmostEqual(p1_compacted.position.z, 0.0, places=4)
        self.assertGreaterEqual(result.released_volume_m3, 0.50)


if __name__ == "__main__":
    unittest.main()
