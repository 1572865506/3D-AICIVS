"""
Tests for TIP-01: Center of Gravity (CoG) projection safety check in UnifiedSolver.
"""
import unittest

from backend.solver_v2.domain.models import (
    BoxDim,
    CargoSKU,
    ContainerSpec,
    QuantityPlan,
)
from backend.solver_v2.solver.unified_solver import UnifiedSolver


class TestTIP01CoGProjection(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec(
            code="40HQ",
            inner_dim=BoxDim(12.024, 2.350, 2.690),
            max_payload_kg=26000.0,
        )
        self.solver = UnifiedSolver(self.container)

    def test_cog_projection_ground_placement(self):
        """Ground placements (z=0) always pass CoG projection check."""
        cand = {"x": 0.0, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0}
        self.assertTrue(self.solver._check_cog_projection(cand, []))
        self.assertTrue(self.solver._has_sufficient_support(cand, []))

    def test_cog_projection_fully_supported(self):
        """A box directly on top of an identical box has CoG right in center and passes."""
        base = {"x": 0.0, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0}
        top = {"x": 0.0, "y": 0.0, "z": 1.0, "dx": 1.0, "dy": 1.0, "dz": 1.0}
        self.assertTrue(self.solver._check_cog_projection(top, [base]))
        self.assertTrue(self.solver._has_sufficient_support(top, [base]))

    def test_cog_projection_cantilever_rejected(self):
        """
        A box (dx=1.0, dy=1.0) placed on a support base spanning [0.0, 0.4] in x.
        Support is only on the left 40%, CoG is at x=0.5 (outside support area [0.0, 0.4]).
        Must be rejected.
        """
        base = {"x": 0.0, "y": 0.0, "z": 0.0, "dx": 0.4, "dy": 1.0, "dz": 1.0}
        top = {"x": 0.0, "y": 0.0, "z": 1.0, "dx": 1.0, "dy": 1.0, "dz": 1.0}
        self.assertFalse(self.solver._check_cog_projection(top, [base]))
        self.assertFalse(self.solver._has_sufficient_support(top, [base]))

    def test_cog_projection_margin_boundary_rejected(self):
        """
        Support base spans [0.0, 0.52] in x.
        Box spans [0.0, 1.0] in x.
        CoG is at x=0.50. The distance to support boundary x=0.52 is only 0.02.
        Required margin is min(dx, dy) * 0.10 = 0.10.
        Therefore, even if CoG is inside [0.0, 0.52], it violates safety margin and must be rejected.
        """
        base = {"x": 0.0, "y": 0.0, "z": 0.0, "dx": 0.52, "dy": 1.0, "dz": 1.0}
        top = {"x": 0.0, "y": 0.0, "z": 1.0, "dx": 1.0, "dy": 1.0, "dz": 1.0}
        self.assertFalse(self.solver._check_cog_projection(top, [base]))
        self.assertFalse(self.solver._has_sufficient_support(top, [base]))

    def test_cog_projection_spanning_two_supports(self):
        """
        A top box (dx=2.0, dy=1.0) placed across two columns:
        Support 1: [0.0, 0.5], Support 2: [1.5, 2.0].
        The convex hull spans [0.0, 2.0] in x, CoG is at x=1.0 (inside hull with large margin to outer hull boundaries).
        CoG projection check passes.
        """
        base1 = {"x": 0.0, "y": 0.0, "z": 0.0, "dx": 0.5, "dy": 1.0, "dz": 1.0}
        base2 = {"x": 1.5, "y": 0.0, "z": 0.0, "dx": 0.5, "dy": 1.0, "dz": 1.0}
        top = {"x": 0.0, "y": 0.0, "z": 1.0, "dx": 2.0, "dy": 1.0, "dz": 1.0}
        self.assertTrue(self.solver._check_cog_projection(top, [base1, base2]))

    def test_end_to_end_solving_validity(self):
        """Ensure full solving pipeline runs without validation violations."""
        sku = CargoSKU(
            sku_id="SKU_TEST",
            name="Test Box",
            box=BoxDim(0.40, 0.40, 0.40),
            weight_kg=10.0,
            quantity=QuantityPlan(required=50),
        )
        solution = self.solver.solve([sku])
        self.assertTrue(solution.validation_result.is_valid, f"Violations: {solution.validation_result.violations}")
        self.assertGreater(solution.placed_count, 0)


if __name__ == "__main__":
    unittest.main()
