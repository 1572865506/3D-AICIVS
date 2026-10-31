# -*- coding: utf-8 -*-
"""
Tests for Placement Immutability and Post-Placement Stability (P0-1 Guard).
Ensures that post-placement routines (such as _compact_placements) NEVER mutate
box coordinates in ways that break support, cause overlaps, or create floating items.
"""
import unittest
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.domain.models import ContainerSpec, BoxDim
from backend.solver_v2.solver.unified_solver import UnifiedSolver


class TestCompactImmutability(unittest.TestCase):
    """Guards against destructive post-placement coordinate shifting."""

    def setUp(self):
        self.container = ContainerSpec(
            code="40HQ_TEST",
            inner_dim=BoxDim(x=12.032, y=2.352, z=2.698),
            max_payload_kg=26500.0,
            door_zone_length_m=1.2,
            rear_zone_length_m=1.0,
        )
        self.solver = UnifiedSolver(self.container)

    def test_snug_door_shift_shearing_rejection(self):
        """
        Verify that General Snug Door Alignment does not shear a stack where
        the top box has a larger dx touching max_front_x while the bottom box does not.
        target_front = 12.032 - 0.04 = 11.992.
        Top box reaches 11.96 (gap = 0.032m <= 0.05m).
        Bottom box reaches 11.86.
        Shifting the top box alone causes it to slide off the bottom support.
        """
        # Box 1 on the floor: x=11.16, y=0.0, z=0.0, dx=0.7, dy=0.5, dz=0.5 -> x+dx=11.86
        box1 = {
            "sku_id": "BASE_BOX",
            "x": 11.16, "y": 0.0, "z": 0.0,
            "dx": 0.7, "dy": 0.5, "dz": 0.5,
            "weight_kg": 20.0,
            "step": 1,
        }
        # Box 2 stacked on Box 1: x=11.16, y=0.0, z=0.5, dx=0.8, dy=0.5, dz=0.5 -> x+dx=11.96
        box2 = {
            "sku_id": "TOP_BOX",
            "x": 11.16, "y": 0.0, "z": 0.5,
            "dx": 0.8, "dy": 0.5, "dz": 0.5,
            "weight_kg": 10.0,
            "step": 2,
        }
        placements = [box1, box2]
        orig_box2_x = box2["x"]

        self.solver._compact_placements(placements)

        # In buggy implementation, box2 was shifted to 11.16 + 0.032 = 11.192,
        # but box1 was NOT shifted, destroying placement immutability!
        self.assertEqual(
            box2["x"], orig_box2_x,
            f"Box 2 was sheared/shifted by _compact_placements from {orig_box2_x} to {box2['x']}!"
        )

    def test_door_p_forward_shift_shearing_rejection(self):
        """
        Verify that door_p forward shifting does not shift door boxes away from
        boxes stacked on them or supporting them.
        """
        # Box 1: door seal box on floor at x=11.0, dx=0.6 -> x+dx=11.6
        box1 = {
            "sku_id": "DOOR_01",
            "x": 11.0, "y": 0.0, "z": 0.0,
            "dx": 0.6, "dy": 0.5, "dz": 0.5,
            "weight_kg": 20.0,
            "context": "DOOR_SEAL",
            "step": 1,
        }
        # Other box behind it at x=10.0, dx=0.8 -> x+dx=10.8 < min_door_x (11.0)
        box2 = {
            "sku_id": "MID_01",
            "x": 10.0, "y": 0.0, "z": 0.0,
            "dx": 0.8, "dy": 0.5, "dz": 0.5,
            "weight_kg": 20.0,
            "context": "MAIN_WALL",
            "step": 2,
        }
        placements = [box1, box2]
        orig_box1_x = box1["x"]

        self.solver._compact_placements(placements)

        # In buggy code, box1 was shifted forward by shift_dx = 11.992 - 11.6 = 0.392m,
        # leaving an uninspected gap or crashing into unmodeled obstacles.
        self.assertEqual(
            box1["x"], orig_box1_x,
            f"Door box was shifted by _compact_placements from {orig_box1_x} to {box1['x']}!"
        )


if __name__ == "__main__":
    unittest.main()
