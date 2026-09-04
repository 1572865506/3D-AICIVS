"""
Tests for TIP-02: Lateral stability and slenderness ratio check in UnifiedSolver.
"""
import unittest

from backend.solver_v2.domain.models import (
    BoxDim,
    CargoSKU,
    ContainerSpec,
    QuantityPlan,
)
from backend.solver_v2.solver.unified_solver import UnifiedSolver


class TestTIP02LateralStability(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec(
            code="40HQ",
            inner_dim=BoxDim(12.024, 2.350, 2.690),
            max_payload_kg=26000.0,
        )
        self.solver = UnifiedSolver(self.container)

    def test_non_slender_box_passes_without_constraints(self):
        """A box with normal slenderness ratio (e.g. 0.5 x 0.5 x 0.5) always passes."""
        cand = {"x": 1.0, "y": 1.0, "z": 0.0, "dx": 0.5, "dy": 0.5, "dz": 0.5}
        self.assertTrue(self.solver._check_lateral_stability(cand, []))

    def test_ground_tall_box_isolated_rejected(self):
        """
        A tall box on ground: dx=0.5, dy=0.3, dz=1.2 (slenderness_y = 1.2 / 0.3 = 4.0 > 3.5).
        Placed in the middle (y=1.0) with no neighbors or walls. Must be rejected.
        """
        cand = {"x": 1.0, "y": 1.0, "z": 0.0, "dx": 0.5, "dy": 0.3, "dz": 1.2}
        self.assertFalse(self.solver._check_lateral_stability(cand, []))

    def test_ground_tall_box_near_wall_passes(self):
        """
        A tall box on ground: dx=0.5, dy=0.3, dz=0.9 (slenderness_y = 0.9 / 0.3 = 3.0 <= 3.5).
        Placed against wall (y=0.0). Passes due to wall relaxation on ground.
        """
        cand = {"x": 1.0, "y": 0.0, "z": 0.0, "dx": 0.5, "dy": 0.3, "dz": 0.9}
        self.assertTrue(self.solver._check_lateral_stability(cand, []))

    def test_upper_tall_box_without_side_support_rejected(self):
        """
        A tall box on upper layer (z=0.5): dx=0.5, dy=0.3, dz=0.7 (slenderness_y = 0.7 / 0.3 = 2.33 > 2.0).
        Placed at y=1.0 without lateral neighbor boxes. Must be rejected.
        """
        cand = {"x": 1.0, "y": 1.0, "z": 0.5, "dx": 0.5, "dy": 0.3, "dz": 0.7}
        self.assertFalse(self.solver._check_lateral_stability(cand, []))

    def test_upper_tall_box_with_side_neighbor_passes(self):
        """
        A tall box on upper layer (z=0.5): dx=0.5, dy=0.3, dz=0.7 (slenderness_y = 2.33).
        Supported laterally by a neighbor at y + dy = 1.3 -> neighbor [1.3, 1.6].
        Should pass.
        """
        neighbor = {"x": 1.0, "y": 1.3, "z": 0.5, "dx": 0.5, "dy": 0.3, "dz": 0.7}
        cand = {"x": 1.0, "y": 1.0, "z": 0.5, "dx": 0.5, "dy": 0.3, "dz": 0.7}
        self.assertTrue(self.solver._check_lateral_stability(cand, [neighbor]))

    def test_end_to_end_tall_boxes_packing(self):
        """Ensure solver handles mixed / tall items safely and produces valid solutions."""
        from backend.solver_v2.domain.models import OrientationPolicy, PlacementContext
        tall_sku = CargoSKU(
            sku_id="SKU_TALL",
            name="Tall Box (0.4x0.3x0.8)",
            box=BoxDim(0.40, 0.30, 0.80),
            weight_kg=12.0,
            quantity=QuantityPlan(required=40),
            orientation_policy=OrientationPolicy(
                allow_upright=True,
                allow_flat=True,
                allowed_contexts_for_flat=(PlacementContext.MAIN_WALL, PlacementContext.TOP_FILL, PlacementContext.GAP_FILL, PlacementContext.DOOR_SEAL),
            ),
        )
        solution = self.solver.solve([tall_sku])
        self.assertTrue(solution.validation_result.is_valid, f"Violations: {solution.validation_result.violations}")
        self.assertGreater(solution.placed_count, 0)


if __name__ == "__main__":
    unittest.main()
