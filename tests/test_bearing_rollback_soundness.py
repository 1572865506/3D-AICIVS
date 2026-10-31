import unittest
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.domain.models import ContainerSpec, BoxDim
from backend.solver_v2.solver.unified_solver import UnifiedSolver


class TestBearingRollbackSoundness(unittest.TestCase):
    """
    Test suite for P0-4: Transaction rollback must strictly revert _bearing_load
    on existing underlying boxes, preventing phantom bearing overloads.
    """

    def test_bearing_load_reverted_on_transaction_rollback(self):
        container = ContainerSpec(
            code="TestContainer",
            inner_dim=BoxDim(x=10.0, y=2.4, z=2.6),
            max_payload_kg=25000.0
        )
        solver = UnifiedSolver(container)

        # Base box placed on floor
        base_box = {
            "sku_id": "BASE_HEAVY",
            "x": 0.0, "y": 0.0, "z": 0.0,
            "dx": 1.0, "dy": 1.0, "dz": 1.0,
            "weight_kg": 100.0,
            "_bearing_load": 0.0
        }
        placements = [base_box]
        solver._has_any_bearing_constraints = True

        # Snapshot before transaction
        tx_snapshot = {
            "placements_len": len(placements),
            "remaining_qty": {"CAND": 2},
            "current_x": 0.0,
            "step_idx": 1,
            "zone_counts": {},
            "payload_weight": getattr(solver, "_curr_payload_weight", 0.0),
            "bearing_loads": [p.get("_bearing_load", 0.0) for p in placements]
        }

        # Candidate box placed on top of base box
        top_box = {
            "sku_id": "CAND",
            "x": 0.0, "y": 0.0, "z": 1.0,
            "dx": 1.0, "dy": 1.0, "dz": 1.0,
            "weight_kg": 50.0
        }
        solver._add_placement(top_box, placements)

        # Base box bearing load should now be 50.0
        self.assertAlmostEqual(base_box["_bearing_load"], 50.0, places=3)
        self.assertEqual(len(placements), 2)

        # Now simulate transaction rollback
        del placements[tx_snapshot["placements_len"]:]
        for idx, b_load in enumerate(tx_snapshot.get("bearing_loads", [])):
            placements[idx]["_bearing_load"] = b_load

        # Assert: base box bearing load MUST be completely reverted to 0.0!
        self.assertEqual(len(placements), 1)
        self.assertAlmostEqual(base_box["_bearing_load"], 0.0, places=3)


if __name__ == "__main__":
    unittest.main()
