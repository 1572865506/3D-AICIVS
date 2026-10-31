import unittest
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.domain.models import ContainerSpec, BoxDim
from backend.solver_v2.solver.unified_solver import UnifiedSolver
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator


class TestDoorTippingThresholdSoundness(unittest.TestCase):
    """
    Test suite for unifying door tipping thresholds between solver pathways and validator.
    Ensures that slender exposed cartons at cL - 45mm (within the 40mm~50mm discrepancy gap)
    are strictly rejected by both the solver and the validator, eliminating oscillation.
    """

    def setUp(self):
        self.cL = 12.024
        self.cW = 2.350
        self.cH = 2.690
        self.container = ContainerSpec(
            code="40HQ",
            inner_dim=BoxDim(self.cL, self.cW, self.cH),
            max_payload_kg=26000.0
        )
        self.solver = UnifiedSolver(self.container)

    def test_slender_box_in_discrepancy_gap_rejected(self):
        """
        Slender carton (dx=0.3, dz=1.0 -> SF = 2.0 * 0.3 / 1.0 = 0.6 < 1.5)
        placed at x + dx = cL - 0.045 (45mm gap from door).
        Must be rejected by _is_placement_tipping_safe to prevent validator tipping violation.
        """
        dx, dy, dz = 0.3, 0.4, 1.0
        x = round(self.cL - 0.045 - dx, 4)
        cand = {
            "sku_id": "SKU_SLENDER",
            "x": x,
            "y": 0.0,
            "z": 0.0,
            "dx": dx,
            "dy": dy,
            "dz": dz,
            "weight_kg": 20.0
        }
        # 1. Authoritative tipping gate must reject this placement (gap > 40mm)
        is_safe = self.solver._is_placement_tipping_safe(cand, [])
        self.assertFalse(is_safe, "Carton 45mm from door must be rejected by _is_placement_tipping_safe")

    def test_slender_box_close_to_door_accepted(self):
        """
        Slender carton placed at x + dx = cL - 0.035 (35mm gap from door, <= 40mm).
        The container door provides rigid forward support, so it must be accepted.
        """
        dx, dy, dz = 0.3, 0.4, 1.0
        x = round(self.cL - 0.035 - dx, 4)
        cand = {
            "sku_id": "SKU_SLENDER",
            "x": x,
            "y": 0.0,
            "z": 0.0,
            "dx": dx,
            "dy": dy,
            "dz": dz,
            "weight_kg": 20.0
        }
        is_safe = self.solver._is_placement_tipping_safe(cand, [])
        self.assertTrue(is_safe, "Carton 35mm from door must be accepted as rigid door support")


if __name__ == "__main__":
    unittest.main()
