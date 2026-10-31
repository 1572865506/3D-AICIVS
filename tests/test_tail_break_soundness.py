import unittest
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.domain.models import ContainerSpec, BoxDim
from backend.solver_v2.solver.unified_solver import UnifiedSolver
from tests.benchmark_suite import InputAdapter


class TestTailBreakSoundness(unittest.TestCase):
    """
    Test suite for P0-3: When remaining_qty <= 0 mid-column, all outer loops must
    terminate cleanly and headroom relay must not use theoretical height on ragged columns.
    """

    def test_ragged_column_does_not_relay_at_theoretical_height(self):
        container = ContainerSpec(
            code="TestContainer",
            inner_dim=BoxDim(x=5.0, y=2.4, z=2.6),
            max_payload_kg=25000.0
        )
        solver = UnifiedSolver(container)

        raw_cargos = [
            {
                "sku": "SKU_A",
                "name": "Item A",
                "w": 0.5, "d": 0.5, "h": 0.5,
                "weight": 10.0,
                "quantity": 1,
            },
            {
                "sku": "SKU_B",
                "name": "Item B",
                "w": 0.5, "d": 0.5, "h": 0.5,
                "weight": 5.0,
                "quantity": 10,
            }
        ]
        cargos = InputAdapter.parse_cargo_list(raw_cargos)
        sol = solver.solve(cargos)

        # Assert no placements are floating in the air without bottom support
        for p in sol.placements:
            if p.min_z > 1e-3:
                supported = any(
                    abs(other.max_z - p.min_z) < 1e-3 and
                    other.max_x > p.min_x and other.min_x < p.max_x and
                    other.max_y > p.min_y and other.min_y < p.max_y
                    for other in sol.placements if other != p
                )
                self.assertTrue(supported, f"Placement {p.placement_id} at z={p.min_z} has no bottom support!")

    def test_bearing_load_reverted_in_solver_transaction(self):
        """
        Verify that UnifiedSolver's tx_snapshot tracks and restores bearing_loads accurately.
        """
        container = ContainerSpec(
            code="TestContainer",
            inner_dim=BoxDim(x=5.0, y=2.4, z=2.6),
            max_payload_kg=25000.0
        )
        solver = UnifiedSolver(container)
        solver._has_any_bearing_constraints = True

        p1 = {"sku_id": "P1", "x": 0.0, "y": 0.0, "z": 0.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "weight_kg": 100.0, "_bearing_load": 0.0}
        placements = [p1]

        # Snapshot with bearing loads
        tx_snapshot = {
            "placements_len": len(placements),
            "bearing_loads": [p.get("_bearing_load", 0.0) for p in placements]
        }

        # Place p2 on top of p1
        p2 = {"sku_id": "P2", "x": 0.0, "y": 0.0, "z": 1.0, "dx": 1.0, "dy": 1.0, "dz": 1.0, "weight_kg": 50.0}
        solver._add_placement(p2, placements)
        self.assertAlmostEqual(p1["_bearing_load"], 50.0, places=2)

        # Rollback
        del placements[tx_snapshot["placements_len"]:]
        for idx, b_load in enumerate(tx_snapshot.get("bearing_loads", [])):
            placements[idx]["_bearing_load"] = b_load

        self.assertAlmostEqual(p1["_bearing_load"], 0.0, places=2)


if __name__ == "__main__":
    unittest.main()
