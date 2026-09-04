"""
Tests for TIP-04: Door Zone Full Container Compaction & Rigid Thrust-Chain Tipping Moment Optimization.
"""
import unittest

from backend.solver_v2.domain.models import (
    BoxDim,
    Orientation3D,
    CargoSKU,
    ContainerSpec,
    Placement,
    PlacementContext,
    Point3D,
    QuantityPlan,
    UniversalCargoTensor,
)
from backend.solver_v2.door.closure_planner import DoorClosurePlanner
from backend.solver_v2.physics.contact_graph import ContactGraph


class TestTIP04DoorTippingThrustChain(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec(
            code="40HQ",
            inner_dim=BoxDim(12.024, 2.350, 2.690),
            max_payload_kg=26000.0,
            door_zone_length_m=1.8,
            rear_zone_length_m=0.3,
        )
        self.planner = DoorClosurePlanner(self.container)

    def test_door_front_group_safe_sf_passes_readiness(self):
        """
        Door front items that form a stable thrust chain (SF_group >= 1.5)
        or have rear support pass anti-toppling and door readiness.
        """
        # Create a sturdy wide block reaching into door zone (Lx = 12.024)
        # Position x = 11.0 to 11.9, dx = 0.9, dz = 0.5, dy = 2.0
        # CoG_x = 11.45, CoG_z = 0.25
        # M_stable = W * (12.024 - 11.45) = W * 0.574
        # M_tip = W * 0.5 * 0.25 = W * 0.125
        # SF = 0.574 / 0.125 = 4.59 >= 1.5
        p1 = Placement(
            placement_id="p1",
            instance_id="inst_1",
            sku_id="SKU_WIDE",
            position=Point3D(11.0, 0.1, 0.0),
            orientation=Orientation3D(name="UPRIGHT_NORMAL", dx=0.9, dy=2.0, dz=0.5),
            step_index=0,
            context=PlacementContext.DOOR_SEAL,
            weight_kg=100.0,
        )
        placements = [p1]

        report = self.planner.evaluate_door_readiness(
            placements,
            reserve_deployed=1,
            has_door_reserve_pool=False,
        )

        self.assertGreaterEqual(report.anti_toppling_stable_ratio, 0.8)
        self.assertTrue(report.reached_door_closure_zone)
        # Verify no tipping hazard rejection reason
        hazard_reasons = [r for r in report.rejection_reasons if "tipping hazard" in r or "anti-toppling risk" in r]
        self.assertEqual(len(hazard_reasons), 0)

    def test_door_front_slender_group_unsupported_fails_readiness(self):
        """
        Door front items that are high and narrow without rear support:
        Combined CoG close to door (x=11.9, dx=0.1, dz=2.0).
        CoG_x = 11.95, CoG_z = 1.0.
        M_stable = W * (12.024 - 11.95) = W * 0.074.
        M_tip = W * 0.5 * 1.0 = W * 0.50.
        SF = 0.074 / 0.50 = 0.148 < 1.5 -> Must be rejected.
        """
        p_tall = Placement(
            placement_id="p_tall",
            instance_id="inst_tall",
            sku_id="SKU_TALL",
            position=Point3D(11.9, 0.1, 0.0),
            orientation=Orientation3D(name="UPRIGHT_NORMAL", dx=0.1, dy=2.0, dz=2.0),
            step_index=0,
            context=PlacementContext.DOOR_SEAL,
            weight_kg=50.0,
        )
        placements = [p_tall]

        report = self.planner.evaluate_door_readiness(
            placements,
            reserve_deployed=1,
            has_door_reserve_pool=False,
        )

        # Must flag anti-toppling risk or tipping hazard
        self.assertFalse(report.is_door_ready)
        hazard_reasons = [r for r in report.rejection_reasons if "tipping hazard" in r or "anti-toppling risk" in r]
        self.assertGreater(len(hazard_reasons), 0)

    def test_rear_supported_door_group_infinite_sf(self):
        """
        Door front items that have rear contact chain connecting to cargo behind them
        are considered braced and have infinite safety factor.
        """
        # Behind box
        p_rear = Placement(
            placement_id="p_rear",
            instance_id="inst_rear",
            sku_id="SKU_REAR",
            position=Point3D(11.0, 0.1, 0.0),
            orientation=Orientation3D(name="UPRIGHT_NORMAL", dx=0.8, dy=2.0, dz=2.0),
            step_index=0,
            context=PlacementContext.MAIN_WALL,
            weight_kg=200.0,
        )
        # Front tall box touching rear box in +X
        p_front = Placement(
            placement_id="p_front",
            instance_id="inst_front",
            sku_id="SKU_FRONT",
            position=Point3D(11.8, 0.1, 0.0),
            orientation=Orientation3D(name="UPRIGHT_NORMAL", dx=0.2, dy=2.0, dz=2.0),
            step_index=1,
            context=PlacementContext.DOOR_SEAL,
            weight_kg=50.0,
        )
        placements = [p_rear, p_front]

        cg = ContactGraph(container=self.container)
        cg.add_placement(p_rear)
        cg.add_placement(p_front)

        report = self.planner.evaluate_door_readiness(
            placements,
            contact_graph=cg,
            reserve_deployed=1,
            has_door_reserve_pool=False,
        )

        hazard_reasons = [r for r in report.rejection_reasons if "tipping hazard" in r or "anti-toppling risk" in r]
        self.assertEqual(len(hazard_reasons), 0)


if __name__ == "__main__":
    unittest.main()
