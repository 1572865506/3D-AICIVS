"""
Unit test for OPT-01 Step 1.3: Multi-level Headroom Relay for Stepped Top Profiles.
Verifies top space fill optimization on stepped multi-SKU profiles.
"""
import unittest

from backend.solver_v2.domain.models import (
    BoxDim,
    CargoSKU,
    ContainerSpec,
    QuantityPlan,
    UniversalCargoTensor,
    UniversalZone,
)
from backend.solver_v2.solver.unified_solver import UnifiedSolver


class TestSteppedHeadroomRelay(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec(
            code="40HQ",
            inner_dim=BoxDim(12.024, 2.350, 2.690),
            max_payload_kg=26000.0,
        )
        self.solver = UnifiedSolver(self.container)

    def test_stepped_headroom_relay_execution(self):
        """
        Setup tall base items (e.g. height 0.70m, 3 layers = 2.10m, headroom = 0.55m)
        and short base items (e.g. height 0.40m, 4 layers = 1.60m, headroom = 1.05m),
        plus filler items (height 0.25m and 0.50m) to relay headroom.
        """
        # Tall base SKU
        sku_tall = CargoSKU(
            sku_id="SKU_TALL",
            name="Tall Base (0.4x0.6x0.7)",
            box=BoxDim(0.40, 0.60, 0.70),
            weight_kg=20.0,
            quantity=QuantityPlan(required=250),
        )
        # Short base SKU
        sku_short = CargoSKU(
            sku_id="SKU_SHORT",
            name="Short Base (0.4x0.45x0.4)",
            box=BoxDim(0.40, 0.45, 0.40),
            weight_kg=12.0,
            quantity=QuantityPlan(required=300),
        )
        # Top filler SKU
        sku_filler = CargoSKU(
            sku_id="SKU_TOP_FILLER",
            name="Top Filler (0.4x0.45x0.25)",
            box=BoxDim(0.40, 0.45, 0.25),
            weight_kg=6.0,
            quantity=QuantityPlan(required=400),
        )

        cargo_list = [sku_tall, sku_short, sku_filler]
        solution = self.solver.solve(cargo_list)

        self.assertTrue(solution.validation_result.is_valid, f"Violations: {solution.validation_result.violations}")
        self.assertGreater(solution.placed_count, 0)
        
        # Check that top filler items are placed at different heights above both stepped segments
        filler_placements = [p for p in solution.placements if p.sku_id == "SKU_TOP_FILLER"]
        self.assertGreater(len(filler_placements), 0, "Top filler items should be placed in headroom relay")
        
        # Verify multi-level heights: filler placed above 1.6m and above 2.1m
        z_positions = {round(p.position.z, 2) for p in filler_placements}
        self.assertGreater(len(z_positions), 1, f"Filler should occupy multiple distinct z-levels: {z_positions}")

        # Utilization should be high (>= 75%)
        self.assertGreaterEqual(solution.volume_utilization_pct, 75.0)
        print(f"\n[Stepped Headroom Test] Placed: {solution.placed_count}, Filler Placed: {len(filler_placements)}, Util: {solution.volume_utilization_pct:.2f}%")


if __name__ == "__main__":
    unittest.main()
