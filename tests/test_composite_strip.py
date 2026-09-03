"""
Unit tests for CompositeStripBuilder (OPT-01).
Tests multi-SKU wall strip generation, Y-axis coverage improvement (>=92%),
stepped top profiles, and headroom relay calculation.
"""
import unittest

from backend.solver_v2.domain.models import (
    BoxDim,
    CargoSKU,
    ContainerSpec,
    Orientation3D,
    PlacementContext,
    Point3D,
    QuantityPlan,
    StackingPolicy,
    UniversalCargoTensor,
)
from backend.solver_v2.solver.composite_strip import (
    CompositeStripBuilder,
    CompositeStripResult,
    SubColumnConfig,
)


class TestCompositeStripBuilder(unittest.TestCase):
    def setUp(self):
        self.builder = CompositeStripBuilder()
        self.cW = 2.35  # standard 40HQ container internal width
        self.cH = 2.65  # available height after margin

    def test_composite_strip_coverage_improvement(self):
        """
        Scenario with heterogeneous SKU sizes:
        SKU_A: width 0.60m, depth 0.40m, height 0.50m (3 * 0.60 = 1.80m -> 76.6% coverage alone)
        SKU_B: width 0.45m, depth 0.40m, height 0.60m (5 * 0.45 = 2.25m -> 95.7% alone)
        SKU_C: width 0.35m, depth 0.40m, height 0.40m (6 * 0.35 = 2.10m -> 89.3% alone)
        
        Composite combination:
        e.g., 2 * 0.60 + 1 * 0.45 + 2 * 0.35 = 1.20 + 0.45 + 0.70 = 2.35m -> 100.0% coverage!
        """
        sku_a = CargoSKU(
            sku_id="SKU_A",
            name="Box A (0.4x0.6x0.5)",
            box=BoxDim(0.40, 0.60, 0.50),
            weight_kg=15.0,
            quantity=QuantityPlan(required=20),
        )
        sku_b = CargoSKU(
            sku_id="SKU_B",
            name="Box B (0.4x0.45x0.6)",
            box=BoxDim(0.40, 0.45, 0.60),
            weight_kg=12.0,
            quantity=QuantityPlan(required=20),
        )
        sku_c = CargoSKU(
            sku_id="SKU_C",
            name="Box C (0.4x0.35x0.4)",
            box=BoxDim(0.40, 0.35, 0.40),
            weight_kg=8.0,
            quantity=QuantityPlan(required=20),
        )

        cargo_pool = [sku_a, sku_b, sku_c]
        delta_x = 0.40

        result = self.builder.build_strip(
            delta_x=delta_x,
            target_width=self.cW,
            available_height=self.cH,
            cargo_pool=cargo_pool,
            allow_mixed_skus=True,
        )

        self.assertTrue(result.is_valid)
        self.assertGreaterEqual(result.y_coverage_ratio, 0.92)  # Acceptance criteria >= 92%
        self.assertLessEqual(result.total_width, self.cW + 1e-4)
        self.assertGreater(len(result.columns), 1)  # Mixed multi-SKU columns

        # Check that total coverage is near-perfect (e.g. >= 2.30m)
        self.assertGreaterEqual(result.total_width, 2.30)

    def test_single_sku_fallback(self):
        """When only one SKU is available or allow_mixed_skus is False."""
        sku = CargoSKU(
            sku_id="SKU_SINGLE",
            name="Single Box",
            box=BoxDim(0.50, 0.45, 0.50),
            weight_kg=10.0,
            quantity=QuantityPlan(required=50),
        )

        result = self.builder.build_strip(
            delta_x=0.50,
            target_width=self.cW,
            available_height=self.cH,
            cargo_pool=[sku],
            allow_mixed_skus=False,
        )

        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.columns), 1)
        # 5 * 0.45 = 2.25m
        self.assertAlmostEqual(result.total_width, 2.25, places=3)
        self.assertEqual(result.columns[0].ny, 5)

    def test_stepped_heights_and_headroom_profiles(self):
        """Verify stepped top profile and headroom relay calculations."""
        sku_tall = CargoSKU(
            sku_id="SKU_TALL",
            name="Tall Box",
            box=BoxDim(0.40, 0.70, 0.80),
            weight_kg=20.0,
            quantity=QuantityPlan(required=10),
        )
        sku_short = CargoSKU(
            sku_id="SKU_SHORT",
            name="Short Box",
            box=BoxDim(0.40, 0.50, 0.40),
            weight_kg=10.0,
            quantity=QuantityPlan(required=20),
        )

        result = self.builder.build_strip(
            delta_x=0.40,
            target_width=self.cW,
            available_height=self.cH,
            cargo_pool=[sku_tall, sku_short],
            allow_mixed_skus=True,
        )

        self.assertTrue(result.is_valid)
        self.assertGreater(len(result.stepped_heights), 0)
        self.assertEqual(len(result.stepped_heights), len(result.columns))
        self.assertEqual(len(result.headroom_profiles), len(result.columns))

        # Ensure stepped heights + headroom = available_height
        for (y0, y1, h), (hy0, hy1, hr) in zip(result.stepped_heights, result.headroom_profiles):
            self.assertAlmostEqual(y0, hy0, places=4)
            self.assertAlmostEqual(y1, hy1, places=4)
            self.assertAlmostEqual(h + hr, self.cH, places=4)

    def test_instantiate_placements_and_no_internal_overlap(self):
        """Instantiated placements must not overlap each other and fit within bounds."""
        sku_a = CargoSKU(
            sku_id="SKU_A",
            name="Box A",
            box=BoxDim(0.40, 0.50, 0.50),
            weight_kg=10.0,
            quantity=QuantityPlan(required=20),
        )
        sku_b = CargoSKU(
            sku_id="SKU_B",
            name="Box B",
            box=BoxDim(0.40, 0.40, 0.40),
            weight_kg=8.0,
            quantity=QuantityPlan(required=20),
        )

        result = self.builder.build_strip(
            delta_x=0.40,
            target_width=self.cW,
            available_height=self.cH,
            cargo_pool=[sku_a, sku_b],
        )

        placements = result.instantiate_placements(start_x=1.0, start_y=0.0, start_z=0.0)
        self.assertEqual(len(placements), result.total_cartons)

        # Check internal non-overlap
        for i in range(len(placements)):
            p1 = placements[i]
            # Must be within bounds
            self.assertGreaterEqual(p1.min_x, 1.0 - 1e-4)
            self.assertLessEqual(p1.max_x, 1.40 + 1e-4)
            self.assertLessEqual(p1.max_y, self.cW + 1e-4)
            self.assertLessEqual(p1.max_z, self.cH + 1e-4)

            for j in range(i + 1, len(placements)):
                p2 = placements[j]
                overlap_x = max(0.0, min(p1.max_x, p2.max_x) - max(p1.min_x, p2.min_x))
                overlap_y = max(0.0, min(p1.max_y, p2.max_y) - max(p1.min_y, p2.min_y))
                overlap_z = max(0.0, min(p1.max_z, p2.max_z) - max(p1.min_z, p2.min_z))
                is_overlap = (overlap_x > 1e-4 and overlap_y > 1e-4 and overlap_z > 1e-4)
                self.assertFalse(is_overlap, f"Overlap between {p1.placement_id} and {p2.placement_id}")

    def test_respects_inventory_limits(self):
        """Builder must never allocate more cartons than remaining inventory."""
        sku_limited = CargoSKU(
            sku_id="SKU_LIMITED",
            name="Limited Stock",
            box=BoxDim(0.40, 0.50, 0.50),
            weight_kg=10.0,
            quantity=QuantityPlan(required=3),  # Only 3 boxes!
        )

        result = self.builder.build_strip(
            delta_x=0.40,
            target_width=self.cW,
            available_height=self.cH,
            cargo_pool=[sku_limited],
            remaining_qty={"SKU_LIMITED": 3},
        )

        self.assertLessEqual(result.total_cartons, 3)
        self.assertLessEqual(result.sku_counts.get("SKU_LIMITED", 0), 3)

    def test_universal_cargo_tensor_support(self):
        """Ensure builder works seamlessly with UniversalCargoTensor."""
        tensors = [
            UniversalCargoTensor(
                sku_id="T1",
                name="Tensor 1",
                length=0.40,
                width=0.60,
                height=0.50,
                weight_kg=15.0,
                quantity_required=15,
            ),
            UniversalCargoTensor(
                sku_id="T2",
                name="Tensor 2",
                length=0.40,
                width=0.40,
                height=0.40,
                weight_kg=10.0,
                quantity_required=20,
            ),
        ]

        result = self.builder.build_strip(
            delta_x=0.40,
            target_width=self.cW,
            available_height=self.cH,
            cargo_pool=tensors,
        )

        self.assertTrue(result.is_valid)
        self.assertGreater(result.total_cartons, 0)
        self.assertGreaterEqual(result.y_coverage_ratio, 0.90)


if __name__ == "__main__":
    unittest.main()
