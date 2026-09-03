"""
Test for OPT-01 Step 1.2: UnifiedSolver integration with CompositeStripBuilder.
Verifies volume utilization >= 70% in mixed heterogeneous dimension scenarios.
"""
import unittest

from backend.solver_v2.domain.models import (
    BoxDim,
    CargoSKU,
    ContainerSpec,
    QuantityPlan,
    StackingPolicy,
)
from backend.solver_v2.solver.unified_solver import UnifiedSolver


class TestUnifiedSolverCompositeStrip(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec(
            code="40HQ",
            inner_dim=BoxDim(12.024, 2.350, 2.690),
            max_payload_kg=26000.0,
        )
        self.solver = UnifiedSolver(self.container)

    def test_mixed_heterogeneous_skus_utilization(self):
        """
        Create a mixed heterogeneous SKU scenario where single-SKU columns leave significant lateral gaps,
        but composite strips allow close packing.
        """
        # Heterogeneous sizes: 0.60m, 0.45m, 0.35m
        sku_1 = CargoSKU(
            sku_id="SKU_W60",
            name="Wide Box (0.4x0.6x0.5)",
            box=BoxDim(0.40, 0.60, 0.50),
            weight_kg=15.0,
            quantity=QuantityPlan(required=250),
        )
        sku_2 = CargoSKU(
            sku_id="SKU_W45",
            name="Medium Box (0.4x0.45x0.6)",
            box=BoxDim(0.40, 0.45, 0.60),
            weight_kg=12.0,
            quantity=QuantityPlan(required=250),
        )
        sku_3 = CargoSKU(
            sku_id="SKU_W35",
            name="Narrow Box (0.4x0.35x0.4)",
            box=BoxDim(0.40, 0.35, 0.40),
            weight_kg=8.0,
            quantity=QuantityPlan(required=300),
        )

        cargo_list = [sku_1, sku_2, sku_3]

        solution = self.solver.solve(cargo_list)

        self.assertTrue(solution.validation_result.is_valid, f"Violations: {solution.validation_result.violations}")
        self.assertGreaterEqual(solution.volume_utilization_pct, 70.0, f"Utilization {solution.volume_utilization_pct}% is < 70%")
        self.assertGreater(solution.placed_count, 0)
        print(f"\n[Test Result] Placed: {solution.placed_count}, Volume Util: {solution.volume_utilization_pct:.2f}%, Status: {solution.status}")


if __name__ == "__main__":
    unittest.main()
