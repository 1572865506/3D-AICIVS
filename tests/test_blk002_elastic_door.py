"""
Unit Tests for Solver V2 BLK-002:
Elastic Door Reservation, Dynamic Frontier Gating, Door Reserve Allocation, and Cooperative Door Closure.
"""
import unittest
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.domain.models import (
    BoxDim,
    Point3D,
    Orientation3D,
    OrientationPolicy,
    StackingPolicy,
    QuantityPlan,
    ContainerSpec,
    CargoSKU,
    Placement,
    PlacementContext,
    PackingRole,
    ZoneType,
)
from backend.solver_v2.door.elastic_frontier import (
    ElasticDoorFrontier,
    ProbeStatus,
    DoorReserveAllocation,
)
from backend.solver_v2.door.closure_planner import (
    DoorClosurePlanner,
    DoorReadinessReport,
)
from backend.solver_v2.quantity.manager import QuantityManager, SpatialReservationManager
from backend.solver_v2.zones.manager import AdaptiveZoneManager
from backend.solver_v2.feasibility.pipeline import HardValidationPipeline
from backend.solver_v2.world.state import WorldState
from backend.solver_v2.solver.baseline_solver import BaselineGreedySolver
from backend.solver_v2.search.config import SearchConfig, SearchProfile
from backend.solver_v2.search.engine import HierarchicalSearchSolver
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator


class TestBLK002ElasticDoor(unittest.TestCase):
    def setUp(self):
        # Canonical 40HQ container
        self.container = ContainerSpec(
            code="40HQ_TEST",
            inner_dim=BoxDim(x=12.032, y=2.352, z=2.698),
            max_payload_kg=26500.0,
            door_zone_length_m=1.2,
            rear_zone_length_m=1.0,
        )

        # SKU-02 (Door Seal Display)
        self.sku_02 = CargoSKU(
            sku_id="SKU-02",
            name="21.5 Display",
            box=BoxDim(x=0.553, y=0.080, z=0.355),
            weight_kg=8.4,
            quantity=QuantityPlan(required=10),
            packing_roles=(PackingRole.DOOR_SEAL,),
            target_zone=ZoneType.DOOR,
        )

        # SKU-03 (34 inch Display)
        self.sku_03 = CargoSKU(
            sku_id="SKU-03",
            name="34 Display",
            box=BoxDim(x=0.978, y=0.188, z=0.488),
            weight_kg=4.61,
            quantity=QuantityPlan(required=6),
            packing_roles=(PackingRole.DOOR_SEAL,),
            target_zone=ZoneType.DOOR,
        )

        # SKU-04 (27 inch Display)
        self.sku_04 = CargoSKU(
            sku_id="SKU-04",
            name="27 Display",
            box=BoxDim(x=0.680, y=0.122, z=0.440),
            weight_kg=6.7,
            quantity=QuantityPlan(required=6),
            packing_roles=(PackingRole.DOOR_SEAL,),
            target_zone=ZoneType.DOOR,
        )

        # SKU-14 (19 inch Display - Elastic)
        self.sku_14 = CargoSKU(
            sku_id="SKU-14",
            name="19 Display Elastic",
            box=BoxDim(x=0.488, y=0.080, z=0.336),
            weight_kg=2.15,
            quantity=QuantityPlan(required=10, is_elastic=True),
            packing_roles=(PackingRole.DOOR_SEAL,),
            target_zone=ZoneType.DOOR,
        )

        # SKU-05 (Main Wall Cargo)
        self.sku_05 = CargoSKU(
            sku_id="SKU-05",
            name="32 Display Main",
            box=BoxDim(x=0.833, y=0.530, z=0.230),
            weight_kg=20.8,
            quantity=QuantityPlan(required=10),
            packing_roles=(PackingRole.MAIN_WALL,),
            target_zone=ZoneType.MIDDLE,
        )

        self.door_skus = [self.sku_02, self.sku_03, self.sku_04, self.sku_14]
        self.all_cargo = [self.sku_05, self.sku_02, self.sku_03, self.sku_04, self.sku_14]

    def test_elastic_door_frontier_allocation(self):
        """Tests that ElasticDoorFrontier allocates a geometric reserve pool and leaves excess."""
        frontier = ElasticDoorFrontier(container=self.container, door_skus=self.door_skus)
        allocations = frontier.allocations

        self.assertEqual(len(allocations), 4)
        for sid, alloc in allocations.items():
            self.assertGreater(alloc.reserved_qty, 0)
            self.assertGreaterEqual(alloc.total_qty, alloc.reserved_qty)
            self.assertGreaterEqual(alloc.excess_qty, 0)
            self.assertEqual(alloc.reserved_qty + alloc.excess_qty, alloc.total_qty)

        metrics = frontier.get_metrics()
        # Latest safe main x should be significantly further forward than static 7.219m!
        self.assertGreater(metrics.latest_safe_main_x, 10.0)
        self.assertLessEqual(metrics.latest_safe_main_x, 12.032)

    def test_door_closure_feasibility_probe(self):
        """Tests ProbeStatus transitions across FEASIBLE, RISKY, and INFEASIBLE."""
        frontier = ElasticDoorFrontier(container=self.container, door_skus=self.door_skus)
        metrics = frontier.get_metrics()

        # Far behind door -> FEASIBLE
        probe_safe = frontier.evaluate_probe(
            candidate_max_x=5.0,
            current_max_x=4.0,
            is_door_sku=False,
        )
        self.assertEqual(probe_safe.status, ProbeStatus.FEASIBLE)
        self.assertEqual(probe_safe.penalty, 0.0)

        # Encroaching into minimum closure depth -> INFEASIBLE
        probe_encroach = frontier.evaluate_probe(
            candidate_max_x=metrics.latest_safe_main_x + 0.1,
            current_max_x=metrics.latest_safe_main_x - 0.2,
            is_door_sku=False,
        )
        self.assertEqual(probe_encroach.status, ProbeStatus.INFEASIBLE)
        self.assertGreater(probe_encroach.penalty, 0.0)

    def test_door_excess_participating_in_main(self):
        """Tests that Door Excess is allowed in MAIN_WALL phase while Reserve Pool is protected."""
        frontier = ElasticDoorFrontier(container=self.container, door_skus=self.door_skus)
        qty_mgr = QuantityManager(cargo_list=self.all_cargo)
        qty_mgr.set_door_reserve_allocations(frontier.allocations)

        alloc_02 = frontier.allocations["SKU-02"]
        # In MAIN_WALL phase, remaining SKU-02 should equal excess_qty
        rem_main = qty_mgr.get_remaining("SKU-02", context=PlacementContext.MAIN_WALL)
        self.assertEqual(rem_main, alloc_02.excess_qty)

        # In DOOR_SEAL phase, remaining SKU-02 should equal total remaining
        rem_door = qty_mgr.get_remaining("SKU-02", context=PlacementContext.DOOR_SEAL)
        self.assertEqual(rem_door, alloc_02.total_qty)

    def test_baseline_solver_elastic_door_packing_insufficient_reach(self):
        """Tests that when cargo does not reach door threshold, is_door_ready is correctly False (prevents false positive)."""
        solver = BaselineGreedySolver(seed=42, max_candidates_per_step=100)
        solution = solver.solve(self.container, self.all_cargo)

        self.assertTrue(solution.validation_result.is_valid)
        self.assertGreater(solution.placed_count, 0)
        self.assertIsNotNone(solution.telemetry.door_readiness)
        # 42 small boxes in a 12m container should NOT be door ready
        self.assertFalse(solution.telemetry.door_readiness["is_door_ready"])
        self.assertFalse(solution.telemetry.door_readiness["reached_door_closure_zone"])

    def test_baseline_solver_elastic_door_packing_full_reach(self):
        """Tests that when cargo fills container to door zone, is_door_ready is True."""
        small_container = ContainerSpec(
            code="COMPACT_TEST",
            inner_dim=BoxDim(x=1.8, y=2.352, z=2.698),
            max_payload_kg=26500.0,
            door_zone_length_m=0.4,
            rear_zone_length_m=0.3,
        )
        solver = BaselineGreedySolver(seed=42, max_candidates_per_step=100)
        solution = solver.solve(small_container, self.all_cargo)

        self.assertTrue(solution.validation_result.is_valid)
        self.assertGreater(solution.placed_count, 0)
        self.assertIsNotNone(solution.telemetry.door_readiness)
        self.assertTrue(solution.telemetry.door_readiness["reached_door_closure_zone"])
        self.assertTrue(solution.telemetry.door_readiness["is_door_ready"])


if __name__ == "__main__":
    unittest.main()
