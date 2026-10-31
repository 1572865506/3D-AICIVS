import unittest
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.domain.models import ContainerSpec, BoxDim
from backend.solver_v2.solver.unified_solver import UnifiedSolver


class TestDiagonalAntiBridge(unittest.TestCase):
    """
    Test suite for P0-2: Geometric support verification must reject
    diagonal two-point contact and hollow-span bridge placements even if
    nominal support area reaches >= 70%.
    """

    def setUp(self):
        self.container = ContainerSpec(
            code="TestContainer",
            inner_dim=BoxDim(x=10.0, y=2.4, z=2.6),
            max_payload_kg=25000.0
        )
        self.solver = UnifiedSolver(self.container)

    def test_floor_layer_always_supported(self):
        """Rule 1.1: z < 1e-3 must always return True unconditionally."""
        cand = {
            "sku_id": "SKU_FLOOR",
            "x": 0.0, "y": 0.0, "z": 0.0,
            "dx": 1.0, "dy": 1.0, "dz": 1.0,
            "weight_kg": 10.0
        }
        self.assertTrue(self.solver._has_sufficient_support(cand, []))

    def test_full_column_support_accepted(self):
        """Standard direct stacking must pass."""
        base = {
            "sku_id": "BASE",
            "x": 0.0, "y": 0.0, "z": 0.0,
            "dx": 1.0, "dy": 1.0, "dz": 1.0,
            "weight_kg": 10.0
        }
        cand = {
            "sku_id": "TOP",
            "x": 0.0, "y": 0.0, "z": 1.0,
            "dx": 1.0, "dy": 1.0, "dz": 1.0,
            "weight_kg": 10.0
        }
        self.assertTrue(self.solver._has_sufficient_support(cand, [base]))

    def test_staggered_brick_support_accepted(self):
        """50% staggered brick layout must pass."""
        base1 = {
            "sku_id": "BASE1",
            "x": 0.0, "y": 0.0, "z": 0.0,
            "dx": 1.0, "dy": 1.0, "dz": 1.0,
            "weight_kg": 10.0
        }
        base2 = {
            "sku_id": "BASE2",
            "x": 1.0, "y": 0.0, "z": 0.0,
            "dx": 1.0, "dy": 1.0, "dz": 1.0,
            "weight_kg": 10.0
        }
        cand = {
            "sku_id": "TOP",
            "x": 0.5, "y": 0.0, "z": 1.0,
            "dx": 1.0, "dy": 1.0, "dz": 1.0,
            "weight_kg": 10.0
        }
        self.assertTrue(self.solver._has_sufficient_support(cand, [base1, base2]))

    def test_hollow_bridge_with_80pct_area_rejected(self):
        """
        Two pillars supporting outer edges:
        Left pillar: [0.0, 0.40] x [0.0, 1.0] (area 0.40)
        Right pillar: [0.60, 1.0] x [0.0, 1.0] (area 0.40)
        Total nominal support area = 0.80 (80% >= 70% threshold!)
        Center core [0.40, 0.60] is completely hollow (20cm span gap).
        Must be REJECTED by core support verification!
        """
        pillar1 = {
            "sku_id": "PIL1",
            "x": 0.0, "y": 0.0, "z": 0.0,
            "dx": 0.40, "dy": 1.0, "dz": 1.0,
            "weight_kg": 10.0
        }
        pillar2 = {
            "sku_id": "PIL2",
            "x": 0.60, "y": 0.0, "z": 0.0,
            "dx": 0.40, "dy": 1.0, "dz": 1.0,
            "weight_kg": 10.0
        }
        cand = {
            "sku_id": "BRIDGE",
            "x": 0.0, "y": 0.0, "z": 1.0,
            "dx": 1.0, "dy": 1.0, "dz": 1.0,
            "weight_kg": 10.0
        }
        self.assertFalse(self.solver._has_sufficient_support(cand, [pillar1, pillar2]))


if __name__ == "__main__":
    unittest.main()
