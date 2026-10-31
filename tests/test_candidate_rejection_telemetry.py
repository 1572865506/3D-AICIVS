import unittest
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.domain.models import (
    ContainerSpec, BoxDim, CargoSKU, StackingPolicy, QuantityPlan
)
from backend.solver_v2.solver.unified_solver import UnifiedSolver


class TestCandidateRejectionTelemetry(unittest.TestCase):
    """
    Test suite for Candidate Rejection Telemetry & Geometric Diagnostics.
    Verifies that rejections across the entire lifecycle are categorized and tracked,
    placement geometry diagnostics are exported, and empty cavities are classified.
    """

    def setUp(self):
        self.container = ContainerSpec(
            code="TestContainer",
            inner_dim=BoxDim(x=2.0, y=1.0, z=1.0),
            max_payload_kg=5000.0
        )
        self.solver = UnifiedSolver(self.container)

    def test_rejection_tracking_in_support_and_constraints(self):
        """Test that rejections accurately record the specific root cause."""
        rejection_counts = {}
        
        # 1. Out of container boundary
        out_cand = {
            "sku_id": "SKU_OUT",
            "x": 1.5, "y": 0.0, "z": 0.0,
            "dx": 1.0, "dy": 1.0, "dz": 1.0,
            "weight_kg": 10.0
        }
        valid = self.solver._check_candidate_validity_with_reason(out_cand, [], rejection_counts)
        self.assertFalse(valid)
        self.assertIn("OUT_OF_CONTAINER", rejection_counts)
        self.assertGreaterEqual(rejection_counts["OUT_OF_CONTAINER"], 1)

        # 2. Collision rejection
        base = {
            "sku_id": "BASE",
            "x": 0.0, "y": 0.0, "z": 0.0,
            "dx": 1.0, "dy": 1.0, "dz": 1.0,
            "weight_kg": 10.0
        }
        colliding_cand = {
            "sku_id": "COLLIDE",
            "x": 0.5, "y": 0.0, "z": 0.0,
            "dx": 1.0, "dy": 1.0, "dz": 1.0,
            "weight_kg": 10.0
        }
        valid = self.solver._check_candidate_validity_with_reason(colliding_cand, [base], rejection_counts)
        self.assertFalse(valid)
        self.assertIn("COLLISION", rejection_counts)

        # 3. Floating / Insufficient support
        floating_cand = {
            "sku_id": "FLOAT",
            "x": 1.0, "y": 0.0, "z": 0.5,
            "dx": 1.0, "dy": 1.0, "dz": 0.5,
            "weight_kg": 10.0
        }
        valid = self.solver._check_candidate_validity_with_reason(floating_cand, [base], rejection_counts)
        self.assertFalse(valid)
        self.assertTrue(
            "INSUFFICIENT_SUPPORT" in rejection_counts or 
            "UNCONNECTED_SUPPORT_TOPOLOGY" in rejection_counts
        )

    def test_solver_telemetry_exports_diagnostics(self):
        """Test that full solve() produces non-empty telemetry diagnostics."""
        skus = [
            CargoSKU(
                sku_id="SKU_HEAVY",
                name="Heavy Base",
                box=BoxDim(1.0, 1.0, 0.5),
                weight_kg=100.0,
                quantity=QuantityPlan(required=1),
                stacking_policy=StackingPolicy(max_stack_layers=2)
            ),
            CargoSKU(
                sku_id="SKU_TOP",
                name="Top Light",
                box=BoxDim(1.0, 1.0, 0.5),
                weight_kg=20.0,
                quantity=QuantityPlan(required=1),
                stacking_policy=StackingPolicy(max_stack_layers=2)
            )
        ]
        solution = self.solver.solve(skus)
        self.assertIsNotNone(solution.telemetry)
        
        # Telemetry candidate metrics
        self.assertIsInstance(solution.telemetry.candidates_rejected_by_reason, dict)
        
        # Placement diagnostics
        plc_diag = getattr(solution.telemetry, "placement_diagnostics", {})
        self.assertIsInstance(plc_diag, dict)
        self.assertGreater(len(plc_diag), 0)
        for pid, diag in plc_diag.items():
            self.assertIn("support_ratio", diag)
            self.assertIn("is_connected", diag)
            self.assertIn("contact_count", diag)
            self.assertIn("bearing_margin_kg", diag)
            self.assertIn("stacking_layer", diag)

        # Cavity diagnostics
        cav_diag = getattr(solution.telemetry, "cavity_diagnostics", [])
        self.assertIsInstance(cav_diag, list)


if __name__ == "__main__":
    unittest.main()
