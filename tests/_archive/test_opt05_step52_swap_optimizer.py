"""
Unit tests for OPT-05 Step 5.2: SwapOptimizer (SwapHeuristic & Local Search).
Verifies:
1. 1-for-N subdivision swaps: Replacing inefficient large boxes with clusters of unplaced smaller boxes.
2. 1-for-1 upgrade swaps: Replacing smaller boxes with unplaced larger boxes.
3. Strict feasibility validation via IndependentGlobalValidator (zero collisions, full support).
4. Acceptance criteria: Placed box count increases by >= 10 boxes after swap optimization.
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
from backend.solver_v2.solver.swap_optimizer import SwapOptimizer, SwapResult
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator


class TestSwapOptimizer(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec(
            code="40HQ",
            inner_dim=BoxDim(12.024, 2.350, 2.690),
            max_payload_kg=26000.0,
        )
        self.optimizer = SwapOptimizer(self.container)

    def test_swap_subdivision_increases_box_count_by_at_least_10(self):
        """
        Acceptance Criteria: Placed box count increases by >= 10 boxes.
        Scenario: A large container box (1.2m x 0.8m x 0.8m) was placed, but there are
        unplaced high-quantity small boxes (0.4m x 0.4m x 0.4m).
        1 large box can fit 3 x 2 x 2 = 12 small boxes, yielding a net delta of +11 boxes!
        """
        sku_large = CargoSKU(
            sku_id="SKU_LARGE",
            name="Large Box",
            box=BoxDim(1.20, 0.80, 0.80),
            weight_kg=60.0,
            quantity=QuantityPlan(required=2),
        )
        sku_small = CargoSKU(
            sku_id="SKU_SMALL",
            name="Small Box",
            box=BoxDim(0.40, 0.40, 0.40),
            weight_kg=8.0,
            quantity=QuantityPlan(required=50),
        )
        cargo_catalog = [sku_large, sku_small]

        # Initial placement: 1 large box on floor
        initial_placements = [
            Placement(
                placement_id="P_LARGE_1",
                instance_id="I_L1",
                sku_id="SKU_LARGE",
                position=Point3D(0.0, 0.0, 0.0),
                orientation=Orientation3D(dx=1.20, dy=0.80, dz=0.80),
                weight_kg=60.0,
                context=PlacementContext.FOUNDATION,
            )
        ]

        result: SwapResult = self.optimizer.optimize(
            placements=initial_placements,
            cargo_list=cargo_catalog,
        )

        print(f"\n[Swap Optimizer Test Results]")
        print(f"  Initial Placed Count: {result.initial_placed_count}")
        print(f"  Final Placed Count: {result.final_placed_count}")
        print(f"  Box Count Delta: {result.box_count_delta}")
        print(f"  Swaps Accepted: {result.swaps_accepted}")
        print(f"  Initial Volume: {result.initial_volume_m3:.4f} m3")
        print(f"  Final Volume: {result.final_volume_m3:.4f} m3")

        # Verify acceptance criteria: delta >= 10
        self.assertGreaterEqual(
            result.box_count_delta,
            10,
            f"Expected box count delta >= 10, got {result.box_count_delta}",
        )
        self.assertGreaterEqual(result.swaps_accepted, 1)

        # Validate with IndependentGlobalValidator
        val_res = IndependentGlobalValidator.validate(
            container=self.container,
            placements=result.placements,
            cargo_list=cargo_catalog,
        )
        self.assertTrue(val_res.is_valid, f"Validation failed: {val_res.rejection_reasons}")

    def test_swap_upgrade_improves_volume(self):
        """
        Tests 1-for-1 upgrade swap where unplaced larger box replaces smaller box.
        """
        sku_tiny = CargoSKU(
            sku_id="SKU_TINY",
            name="Tiny Box",
            box=BoxDim(0.40, 0.40, 0.40),
            weight_kg=5.0,
            quantity=QuantityPlan(required=2),
        )
        sku_med = CargoSKU(
            sku_id="SKU_MED",
            name="Medium Box",
            box=BoxDim(0.80, 0.80, 0.80),
            weight_kg=25.0,
            quantity=QuantityPlan(required=2),
        )
        cargo_catalog = [sku_tiny, sku_med]

        initial_placements = [
            Placement(
                placement_id="P_TINY_1",
                instance_id="I_T1",
                sku_id="SKU_TINY",
                position=Point3D(0.0, 0.0, 0.0),
                orientation=Orientation3D(dx=0.40, dy=0.40, dz=0.40),
                weight_kg=5.0,
                context=PlacementContext.FOUNDATION,
            )
        ]

        result = self.optimizer.optimize(
            placements=initial_placements,
            cargo_list=cargo_catalog,
        )

        self.assertGreaterEqual(result.volume_delta_m3, 0.0)
        self.assertEqual(len(result.placements), 1)
        self.assertEqual(result.placements[0].sku_id, "SKU_MED")

        val_res = IndependentGlobalValidator.validate(
            container=self.container,
            placements=result.placements,
            cargo_list=cargo_catalog,
        )
        self.assertTrue(val_res.is_valid, f"Validation failed: {val_res.rejection_reasons}")


if __name__ == "__main__":
    unittest.main()
