"""BLK-006C state pruning, budgets, normalization, and phase contracts."""
import copy
import time
import unittest

from backend.solver_v2.domain.models import (
    BoxDim, CargoSKU, ContainerSpec, Orientation3D, Placement, PlacementContext,
    Point3D, QuantityPlan, StackingPolicy,
)
from backend.solver_v2.search.beam import BeamNode, BoundedBeamSearchEngine
from backend.solver_v2.search.config import SearchConfig, SearchProfile
from backend.solver_v2.search.global_wall_search import (
    GLOBAL_SEARCH, FutureTopFillEstimator, GlobalWallObjective,
    SearchStateSignature, WallCandidate, root_search_state,
)


class TestBLK006CMultiDepth(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec("C", BoxDim(12, 2.4, 2.7), 30000)
        self.sku = CargoSKU(
            "SKU", "opaque", BoxDim(.5, .4, .3), 2, QuantityPlan(100),
            stacking_policy=StackingPolicy(max_bearing_kg=100, min_support_ratio=.7),
        )
        self.config = SearchConfig.for_profile(
            SearchProfile.BALANCED, wall_plan_search_mode=GLOBAL_SEARCH,
            beam_width=2, global_wall_max_depth=4,
        )

    def _placement(self, placement_id="p", x=0.0):
        return Placement(
            placement_id, placement_id, "SKU", Point3D(x, 0, 0),
            Orientation3D(.5, .4, .3, "UPRIGHT_NORMAL", True), 2,
            PlacementContext.MAIN_WALL,
        )

    def _node(self, state, score=0.0):
        return BeamNode(
            node_id=state.state_id, placements=copy.deepcopy(state.placements),
            cumulative_score=score, total_volume=state.placed_volume,
            last_max_x=state.current_x, search_state=state,
        )

    def test_signature_is_structural_not_id_based(self):
        a = root_search_state([self.sku])
        b = root_search_state([self.sku])
        a.placements = [self._placement("id-a")]
        b.placements = [self._placement("id-b")]
        self.assertEqual(SearchStateSignature.from_state(a).key(), SearchStateSignature.from_state(b).key())

    def test_dedup_and_conservative_dominance_are_active(self):
        engine = BoundedBeamSearchEngine(self.container, [self.sku], self.config)
        base = root_search_state([self.sku])
        duplicate = base.clone("duplicate")
        deduped = engine._prune_global_states([self._node(base), self._node(duplicate)])
        self.assertEqual(len(deduped), 1)
        self.assertEqual(engine.telemetry["wall_plan_search"]["duplicate_states_removed"], 1)

        weaker = root_search_state([self.sku])
        weaker.state_id = "weaker"
        weaker.current_x = 1.0
        weaker.placed_volume = 1.0
        stronger = root_search_state([self.sku])
        stronger.state_id = "stronger"
        stronger.current_x = 2.0
        stronger.placed_volume = 2.0
        kept = engine._prune_global_states([self._node(weaker), self._node(stronger)])
        self.assertEqual([node.node_id for node in kept], ["stronger"])
        self.assertEqual(engine.telemetry["wall_plan_search"]["dominated_states_removed"], 1)

    def test_all_three_hard_budgets_stop_expansion(self):
        for field in ("global_max_states_generated", "global_max_states_expanded"):
            config = copy.deepcopy(self.config)
            setattr(config, field, 0)
            engine = BoundedBeamSearchEngine(self.container, [self.sku], config)
            self.assertTrue(engine._global_budget_reached())
            self.assertEqual(engine.telemetry["wall_plan_search"]["budget_stop_reason"], "STATE_BUDGET_STOP")
        engine = BoundedBeamSearchEngine(self.container, [self.sku], self.config)
        engine._global_started = time.perf_counter() - self.config.global_runtime_budget_sec - 1
        self.assertTrue(engine._global_budget_reached())
        self.assertEqual(engine.telemetry["wall_plan_search"]["budget_stop_reason"], "RUNTIME_STOP")

    def test_objective_exposes_raw_normalized_and_weighted_components(self):
        state = root_search_state([self.sku])
        candidate = WallCandidate.from_placements("W", "SKU", [self._placement()])
        potential = FutureTopFillEstimator(self.container, {"SKU": self.sku}).estimate(candidate, {"SKU": 99})
        breakdown = GlobalWallObjective(self.container).evaluate(state, candidate, potential, 100, 11.0, 1.0)
        self.assertEqual(len(breakdown.raw_component_value), 8)
        self.assertEqual(len(breakdown.normalized_component_value), 8)
        self.assertEqual(len(breakdown.weighted_component_value), 8)
        self.assertAlmostEqual(sum(breakdown.weighted_component_value.values()), breakdown.final_score)


if __name__ == "__main__":
    unittest.main()
