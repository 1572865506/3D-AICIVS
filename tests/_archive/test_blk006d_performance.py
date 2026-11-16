"""BLK-006D exact broad phase, frontier view, cache, and profile contracts."""
import unittest

from backend.solver_v2.candidates.generator import CandidatePlacement
from backend.solver_v2.domain.models import (
    BoxDim, CargoSKU, ContainerSpec, Orientation3D, Placement, PlacementContext,
    Point3D, QuantityPlan, StackingPolicy,
)
from backend.solver_v2.geometry.aabb import AABB
from backend.solver_v2.patterns.models import PatternType
from backend.solver_v2.quantity.manager import QuantityManager
from backend.solver_v2.search.aggregate import AggregateCandidate
from backend.solver_v2.search.config import SearchConfig, SearchProfile
from backend.solver_v2.search.diverse_wall_candidates import DiverseWallCandidateGenerator
from backend.solver_v2.spaces.engine import FreeSpaceEngine
from backend.solver_v2.spaces.types import AnchorCategory
from backend.solver_v2.world.state import WorldState


class TestBLK006DPerformance(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec("C", BoxDim(4, 2, 2), 10000)
        self.sku = CargoSKU(
            "S", "s", BoxDim(1, 1, 1), 10, QuantityPlan(20),
            stacking_policy=StackingPolicy(max_bearing_kg=100, min_support_ratio=.8),
        )

    def _placement(self, pid, x, y, z):
        return Placement(
            pid, pid, "S", Point3D(x, y, z),
            Orientation3D(1, 1, 1, "UPRIGHT_NORMAL", True), 10,
            PlacementContext.MAIN_WALL,
        )

    def test_spatial_broad_phase_preserves_exact_contact_and_support(self):
        world = WorldState(self.container, [self.sku])
        bottom = self._placement("bottom", 0, 0, 0)
        side = self._placement("side", 1, 0, 0)
        top = self._placement("top", 0, 0, 1)
        for placement in (bottom, side, top):
            world.commit(placement)
        bottom_contacts = {(edge.node_b, edge.direction.value) for edge in world.contact_graph.get_contacts("bottom")}
        self.assertIn(("side", "FRONT"), bottom_contacts)
        self.assertIn(("top", "TOP"), bottom_contacts)
        support = world.support_graph.get_support_edges("top")
        self.assertEqual([(edge.lower_id, round(edge.support_ratio, 6)) for edge in support], [("bottom", 1.0)])

    def test_lightweight_frontier_view_retains_placement_derived_anchors(self):
        placement = self._placement("p", 0, 0, 0)
        replay = FreeSpaceEngine(self.container)
        replay.on_placement_replayed(placement)
        light = FreeSpaceEngine(self.container)
        light.rebuild_frontier_view([placement])
        replay_anchors = replay.get_classified_anchors()
        light_anchors = light.get_classified_anchors()
        self.assertTrue(light_anchors[AnchorCategory.TOP_SURFACE])
        self.assertEqual(
            max(anchor.point.x for anchor in replay_anchors[AnchorCategory.WALL_FRONTIER]),
            max(anchor.point.x for anchor in light_anchors[AnchorCategory.WALL_FRONTIER]),
        )

    def test_candidate_geometry_cache_is_context_safe_and_hits(self):
        ori = Orientation3D(1, 1, 1, "UPRIGHT_NORMAL", True)
        item = CandidatePlacement("S", Point3D(0, 0, 0), ori, PlacementContext.MAIN_WALL, 10)
        aggregate = AggregateCandidate(
            "a", "S", PlacementContext.MAIN_WALL, Point3D(0, 0, 0), AABB(0, 0, 0, 1, 1, 1),
            [item], 1, 10, 1, PatternType.BLOCK,
        )
        generator = DiverseWallCandidateGenerator()
        self.assertEqual(generator.signature_for(aggregate), generator.signature_for(aggregate))
        self.assertEqual(generator.cache_misses, 1)
        self.assertEqual(generator.cache_hits, 1)

    def test_runtime_profiles_and_bounds_are_configured(self):
        self.assertEqual(SearchConfig.for_profile(SearchProfile.FAST).global_runtime_budget_sec, 15.0)
        self.assertEqual(SearchConfig.for_profile(SearchProfile.BALANCED).global_runtime_budget_sec, 45.0)
        self.assertEqual(SearchConfig.for_profile(SearchProfile.OPTIMIZE).global_runtime_budget_sec, 90.0)


if __name__ == "__main__":
    unittest.main()
