"""
Unit Tests for Solver V2 P0 BLK-001:
Candidate Anchor Sampling, Scheduling, Budgeting, and Early Termination Disambiguation.
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
from backend.solver_v2.spaces.types import AnchorCategory, ClassifiedAnchor
from backend.solver_v2.spaces.engine import FreeSpaceEngine
from backend.solver_v2.world.state import WorldState
from backend.solver_v2.orientation.manager import OrientationEngine
from backend.solver_v2.zones.manager import AdaptiveZoneManager
from backend.solver_v2.quantity.manager import QuantityManager, SpatialReservationManager
from backend.solver_v2.candidates.generator import CandidateGenerator, CandidateBudget, CandidatePlacement
from backend.solver_v2.search.config import SearchConfig, SearchProfile
from backend.solver_v2.search.beam import BoundedBeamSearchEngine
from backend.solver_v2.solver.baseline_solver import BaselineGreedySolver
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator


class TestP0BLK001Anchors(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec(
            code="40HQ_TEST",
            inner_dim=BoxDim(x=12.032, y=2.352, z=2.698),
            max_payload_kg=26500.0,
            door_zone_length_m=1.2,
            rear_zone_length_m=1.0,
        )

        self.sku_heavy = CargoSKU(
            sku_id="SKU_BASE",
            name="Base Box",
            box=BoxDim(x=0.8, y=0.5, z=0.4),
            weight_kg=30.0,
            quantity=QuantityPlan(required=20),
            orientation_policy=OrientationPolicy(allow_upright=True, allow_flat=False),
            stacking_policy=StackingPolicy(max_stack_layers=5),
            packing_roles=(PackingRole.MAIN_WALL, PackingRole.FOUNDATION),
        )

        self.sku_upper = CargoSKU(
            sku_id="SKU_UPPER",
            name="Upper Box",
            box=BoxDim(x=0.4, y=0.5, z=0.3),
            weight_kg=10.0,
            quantity=QuantityPlan(required=40),
            orientation_policy=OrientationPolicy(allow_upright=True, allow_flat=False),
            stacking_policy=StackingPolicy(max_stack_layers=5),
            packing_roles=(PackingRole.MAIN_WALL,),
        )

        self.cargo_list = [self.sku_heavy, self.sku_upper]

    def test_classified_anchors_generation(self):
        """Tests that FreeSpaceEngine correctly partitions anchors into geometric categories."""
        space_engine = FreeSpaceEngine(container=self.container)
        world_state = WorldState(container=self.container, cargo_catalog=self.cargo_list)

        # Empty container should have origin as FLOOR_FRONTIER
        classified = space_engine.get_classified_anchors(world_state)
        floor_anchors = classified[AnchorCategory.FLOOR_FRONTIER]
        self.assertTrue(len(floor_anchors) > 0)
        self.assertAlmostEqual(floor_anchors[0].z, 0.0)

        # Commit a base placement
        p1 = Placement(
            placement_id="p1",
            instance_id="inst1",
            sku_id="SKU_BASE",
            position=Point3D(0, 0, 0),
            orientation=Orientation3D(0.8, 0.5, 0.4),
            context=PlacementContext.FOUNDATION,
            weight_kg=30.0,
        )
        world_state.commit(p1)
        space_engine.on_placement_committed(p1)

        classified_after = space_engine.get_classified_anchors(world_state)
        floor_after = classified_after[AnchorCategory.FLOOR_FRONTIER]
        supported_after = classified_after[AnchorCategory.SUPPORTED_FRONTIER]

        # Floor frontier should have points advancing in X and Y at z=0
        self.assertTrue(any(a.x >= 0.8 and a.z <= 0.001 for a in floor_after))
        self.assertTrue(any(a.y >= 0.5 and a.z <= 0.001 for a in floor_after))

        # Supported frontier should contain points on top of p1 (z = 0.4)
        self.assertTrue(any(abs(a.z - 0.4) <= 0.001 for a in supported_after))

    def test_cheap_support_prefilter(self):
        """Tests CandidateGenerator.has_possible_support pre-filter."""
        world_state = WorldState(container=self.container, cargo_catalog=self.cargo_list)
        gen = CandidateGenerator()

        # Floor point is always supported
        self.assertTrue(gen.has_possible_support(world_state, Point3D(0, 0, 0), Orientation3D(0.8, 0.5, 0.4)))

        # Mid-air point with no placements is NOT supported
        self.assertFalse(gen.has_possible_support(world_state, Point3D(0, 0, 1.0), Orientation3D(0.8, 0.5, 0.4)))

        # Commit base placement
        p1 = Placement(
            placement_id="p1",
            instance_id="inst1",
            sku_id="SKU_BASE",
            position=Point3D(0, 0, 0),
            orientation=Orientation3D(0.8, 0.5, 0.4),
            context=PlacementContext.FOUNDATION,
            weight_kg=30.0,
        )
        world_state.commit(p1)

        # Point directly on top of p1 (0, 0, 0.4) is supported
        self.assertTrue(gen.has_possible_support(world_state, Point3D(0, 0, 0.4), Orientation3D(0.4, 0.5, 0.3)))

        # Point in mid-air far from p1 is NOT supported
        self.assertFalse(gen.has_possible_support(world_state, Point3D(5.0, 0, 1.0), Orientation3D(0.4, 0.5, 0.3)))

    def test_candidate_budget_quota_allocation(self):
        """Tests that CandidateBudget enforces quotas per category."""
        budget = CandidateBudget.from_total(300)
        self.assertGreaterEqual(budget.floor, 40)
        self.assertGreaterEqual(budget.supported, 40)
        self.assertGreaterEqual(budget.wall, 20)
        self.assertGreaterEqual(budget.ems, 15)
        self.assertGreaterEqual(budget.ep, 15)

    def test_baseline_solver_telemetry_and_validity(self):
        """Tests that BaselineGreedySolver captures anchor telemetry and maintains 0 collisions."""
        solver = BaselineGreedySolver(seed=42)
        solution = solver.solve(self.container, self.cargo_list)

        self.assertTrue(solution.validation_result.is_valid)
        self.assertGreater(solution.placed_count, 0)
        telem = solution.telemetry
        self.assertIn("FLOOR_FRONTIER", telem.anchors_generated_by_type)
        self.assertGreater(telem.candidates_generated, 0)
        self.assertGreaterEqual(len(telem.phase_termination_reason), 1)

    def test_beam_search_with_category_aware_aggregate(self):
        """Tests BoundedBeamSearchEngine with category-aware candidate generation."""
        cfg = SearchConfig(profile=SearchProfile.FAST, beam_width=2, time_budget_sec=5.0, seed=42)
        beam_engine = BoundedBeamSearchEngine(
            container=self.container,
            cargo_list=self.cargo_list,
            config=cfg,
        )
        placements = beam_engine.search()
        self.assertGreater(len(placements), 0)

        val_res = IndependentGlobalValidator.validate(
            container=self.container,
            placements=placements,
            cargo_list=self.cargo_list,
        )
        self.assertTrue(val_res.is_valid)
        self.assertEqual(len(val_res.overlap_violations), 0)
        self.assertEqual(len(val_res.bounds_violations), 0)


if __name__ == "__main__":
    unittest.main()
