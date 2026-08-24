"""BLK-006A SearchState isolation, objective, replay, and legacy preservation."""
import unittest

from backend.solver_v2.domain.models import (
    BoxDim, CargoSKU, ContainerSpec, Orientation3D, Placement, PlacementContext,
    Point3D, QuantityPlan, StackingPolicy,
)
from backend.solver_v2.search.config import SearchConfig, SearchProfile
from backend.solver_v2.search.global_wall_search import (
    GLOBAL_SEARCH, LEGACY_GREEDY, FutureTopFillEstimator, GlobalWallObjective,
    WallCandidate, root_search_state,
)


class TestBLK006AGlobalWallSearch(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec("C", BoxDim(4, 2, 3), 10000)
        self.sku = CargoSKU(
            "SKU", "opaque", BoxDim(0.5, 0.4, 0.3), 2, QuantityPlan(20),
            stacking_policy=StackingPolicy(max_bearing_kg=100, min_support_ratio=0.7),
        )
        self.placement = Placement(
            "p", "i", "SKU", Point3D(0, 0, 0),
            Orientation3D(0.5, 0.4, 0.3, "UPRIGHT_NORMAL", True),
            2, PlacementContext.MAIN_WALL,
        )
        self.candidate = WallCandidate.from_placements("W", "SKU", [self.placement])

    def test_branch_clone_isolation(self):
        root = root_search_state([self.sku])
        child = root.clone("child")
        child.remaining_inventory["SKU"] = 1
        child.wall_sequence.append("W")
        child.placements.append(self.placement)
        child.support_state["ratios"] = [1.0]
        self.assertEqual(root.remaining_inventory["SKU"], 20)
        self.assertEqual(root.wall_sequence, [])
        self.assertEqual(root.placements, [])
        self.assertEqual(root.support_state, {})

    def test_objective_is_explainable_and_deterministic(self):
        root = root_search_state([self.sku])
        estimator = FutureTopFillEstimator(self.container, {"SKU": self.sku})
        potential = estimator.estimate(self.candidate, {"SKU": 19})
        objective = GlobalWallObjective(self.container)
        first = objective.evaluate(root, self.candidate, potential, 20, 3.5, 1.0)
        second = objective.evaluate(root, self.candidate, potential, 20, 3.5, 1.0)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.final_score, (
            first.main_body_gain + first.topfill_estimate + first.residual_quality
            + first.compactness + first.inventory_fit - first.fragmentation_penalty
            - first.unstable_geometry_penalty - first.door_penalty
        ))

    def test_state_fingerprint_replays_deterministically(self):
        a = root_search_state([self.sku])
        b = root_search_state([self.sku])
        self.assertEqual(a.fingerprint(), b.fingerprint())
        b.remaining_inventory["SKU"] -= 1
        self.assertNotEqual(a.fingerprint(), b.fingerprint())

    def test_legacy_is_default_and_global_is_opt_in(self):
        legacy = SearchConfig.for_profile(SearchProfile.BALANCED)
        self.assertEqual(legacy.wall_plan_search_mode, LEGACY_GREEDY)
        global_cfg = SearchConfig.for_profile(
            SearchProfile.BALANCED, wall_plan_search_mode=GLOBAL_SEARCH, beam_width=2,
        )
        self.assertEqual(global_cfg.wall_plan_search_mode, GLOBAL_SEARCH)
        self.assertEqual(global_cfg.beam_width, 2)


if __name__ == "__main__":
    unittest.main()
