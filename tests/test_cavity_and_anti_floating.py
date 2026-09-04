"""
Tests for Cavity Prevention, Anti-Floating Box Guarantee, and Ground Support.
"""
import unittest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.domain.models import BoxDim, ContainerSpec
from backend.solver_v2.solver.unified_solver import UnifiedSolver
from scripts.diagnose_frontend_manifest import load_manifest


class TestCavityAndAntiFloating(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec(
            code="40HQ",
            inner_dim=BoxDim(12.032, 2.352, 2.698),
            max_payload_kg=26500.0,
            door_zone_length_m=1.2,
            rear_zone_length_m=1.0,
        )
        self.solver = UnifiedSolver(self.container)

    def test_ground_layer_support_accepted_immediately(self):
        """Ground layer boxes (z=0) must be accepted without false lateral instability rejection."""
        cand_ground = {
            "sku_id": "SKU-TALL",
            "x": 0.0, "y": 0.0, "z": 0.0,
            "dx": 0.20, "dy": 0.30, "dz": 1.20,
        }
        self.assertTrue(self.solver._has_sufficient_support(cand_ground, []))

    def test_cog_margin_3_percent_accepts_stable_stacks(self):
        """CoG projection with 3% margin safely accepts standard supporting columns."""
        lower_box = {
            "x": 1.0, "y": 0.0, "z": 0.0,
            "dx": 0.60, "dy": 0.40, "dz": 0.50,
        }
        upper_box = {
            "x": 1.0, "y": 0.0, "z": 0.50,
            "dx": 0.60, "dy": 0.40, "dz": 0.50,
        }
        self.assertTrue(self.solver._check_cog_projection(upper_box, [lower_box]))

    def test_production_manifest_has_zero_floating_boxes_and_high_utilization(self):
        """
        Production 15-SKU manifest must solve cleanly:
        - 0 floating boxes (0 INSUFFICIENT_SUPPORT)
        - Volume utilization >= 85%
        - Valid solution
        """
        raw_manifest = load_manifest()
        cargo_list = InputAdapter.parse_cargo_list(raw_manifest)

        solution = self.solver.solve(cargo_list, mode="BALANCED", seed=42)

        self.assertGreater(solution.placed_count, 1800)
        self.assertGreaterEqual(solution.volume_utilization_pct, 85.0)
        self.assertTrue(solution.validation_result.is_valid, f"Validation failed: {solution.validation_result.violations}")


if __name__ == "__main__":
    unittest.main()
