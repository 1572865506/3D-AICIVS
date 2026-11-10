"""
Unit Tests for Solver V2 Agent 09 — Hierarchical Search Subsystem:
- Multi-start heuristic exploration & seed determinism
- Aggregate block/layer pattern generation vs individual carton fallback
- Bounded beam search over aggregate structures
- Limited backtracking and branch state pruning
- Local search, headspace topfill & residual gap-fill repair
- Time budget cutoff & anytime best-so-far callbacks
- Profiles execution (FAST, BALANCED, OPTIMIZE)
- Independent Global Validator compliance (zero collision, zero penetration, zero out-of-bounds)
"""
import unittest
import os
import sys
import time

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
    CargoClass,
)
from backend.solver_v2.search.config import SearchConfig, SearchProfile
from backend.solver_v2.search.aggregate import AggregateCandidateGenerator, AggregateCandidate
from backend.solver_v2.search.multi_start import MultiStartManager, StartStrategy
from backend.solver_v2.search.beam import BoundedBeamSearchEngine, BeamNode
from backend.solver_v2.search.local_search import LocalSearchOptimizer
from backend.solver_v2.search.engine import HierarchicalSearchSolver
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator


class TestSearchAgent(unittest.TestCase):
    def setUp(self):
        # 40HQ Container: 12.0m x 2.4m x 2.6m, max payload 26000 kg
        self.container = ContainerSpec(
            code="40HQ_SEARCH_TEST",
            inner_dim=BoxDim(x=12.0, y=2.4, z=2.6),
            max_payload_kg=26000.0,
            door_zone_length_m=1.2,
            rear_zone_length_m=1.0,
        )

        # SKU 1: Standard Medium Carton
        self.sku_med = CargoSKU(
            sku_id="SKU_MED",
            name="Medium Carton",
            box=BoxDim(x=0.6, y=0.4, z=0.5),
            weight_kg=25.0,
            quantity=QuantityPlan(required=80),
            orientation_policy=OrientationPolicy(allow_upright=True, allow_flat=False),
            stacking_policy=StackingPolicy(max_stack_layers=5, max_bearing_kg=350.0),
            packing_roles=(PackingRole.MAIN_WALL, PackingRole.FOUNDATION),
        )

        # SKU 2: Heavy Base Box
        self.sku_heavy = CargoSKU(
            sku_id="SKU_HEAVY",
            name="Heavy Base Box",
            box=BoxDim(x=0.8, y=0.6, z=0.5),
            weight_kg=60.0,
            quantity=QuantityPlan(required=20),
            cargo_class=CargoClass.HEAVY,
            orientation_policy=OrientationPolicy(allow_upright=True, allow_flat=False),
            stacking_policy=StackingPolicy(max_stack_layers=3, must_be_on_floor=True),
            packing_roles=(PackingRole.FOUNDATION,),
        )

        # SKU 3: Small Display / Top Fill Carton
        self.sku_small = CargoSKU(
            sku_id="SKU_SMALL",
            name="Small Fill Carton",
            box=BoxDim(x=0.4, y=0.3, z=0.2),
            weight_kg=5.0,
            quantity=QuantityPlan(required=60),
            orientation_policy=OrientationPolicy(
                allow_upright=True,
                allow_flat=True,
                allowed_contexts_for_flat=(PlacementContext.TOP_FILL, PlacementContext.GAP_FILL),
            ),
            stacking_policy=StackingPolicy(max_stack_layers=8),
            packing_roles=(PackingRole.TOP_FILL, PackingRole.FLEXIBLE),
        )

        self.cargo_list = [self.sku_heavy, self.sku_med, self.sku_small]

    def test_multi_start_strategies_generation(self):
        """Tests that MultiStartManager generates diverse and deterministic strategies."""
        strategies_1 = MultiStartManager.generate_strategies(self.cargo_list, num_runs=4, base_seed=42)
        strategies_2 = MultiStartManager.generate_strategies(self.cargo_list, num_runs=4, base_seed=42)

        self.assertEqual(len(strategies_1), 4)
        self.assertEqual(len(strategies_2), 4)

        # Ensure determinism across identical seeds
        for s1, s2 in zip(strategies_1, strategies_2):
            self.assertEqual(s1.strategy, s2.strategy)
            self.assertEqual(s1.seed, s2.seed)
            self.assertEqual(s1.sku_priority_order, s2.sku_priority_order)

        # Ensure different strategies have distinct prioritization rules
        strategies_types = {s.strategy for s in strategies_1}
        self.assertTrue(len(strategies_types) >= 3)

    def test_aggregate_candidate_generation(self):
        """Tests that AggregateCandidateGenerator creates both multi-item blocks and single items."""
        from backend.solver_v2.spaces.engine import FreeSpaceEngine
        from backend.solver_v2.orientation.manager import OrientationEngine
        from backend.solver_v2.zones.manager import AdaptiveZoneManager
        from backend.solver_v2.quantity.manager import QuantityManager

        space_engine = FreeSpaceEngine(container=self.container)
        ori_engine = OrientationEngine()
        zone_mgr = AdaptiveZoneManager(container=self.container)
        qty_mgr = QuantityManager(cargo_list=self.cargo_list)

        agg_gen = AggregateCandidateGenerator()
        candidates = agg_gen.generate_aggregate_candidates(
            space_engine=space_engine,
            orientation_engine=ori_engine,
            zone_mgr=zone_mgr,
            qty_mgr=qty_mgr,
            active_skus=[self.sku_med],
            context=PlacementContext.MAIN_WALL,
            max_candidates=50,
            enable_patterns=True,
        )

        self.assertTrue(len(candidates) > 0)
        # Check that there are aggregate blocks (item_count > 1) and single items
        aggregate_blocks = [c for c in candidates if c.is_aggregate]
        self.assertTrue(len(aggregate_blocks) > 0, "Should generate multi-item aggregate block candidates")
        for b in aggregate_blocks:
            self.assertEqual(len(b.item_candidates), b.item_count)
            self.assertTrue(b.bounding_box.volume > 0)

    def test_bounded_beam_search_execution(self):
        """Tests that BoundedBeamSearchEngine executes phased beam search and returns valid placements."""
        cfg = SearchConfig(
            profile=SearchProfile.FAST,
            beam_width=2,
            time_budget_sec=5.0,
            seed=42,
        )
        beam_engine = BoundedBeamSearchEngine(
            container=self.container,
            cargo_list=self.cargo_list,
            config=cfg,
        )
        placements = beam_engine.search()

        self.assertTrue(len(placements) > 0, "Beam search should place cargo items")

        # Independent validation
        val_result = IndependentGlobalValidator.validate(
            container=self.container,
            placements=placements,
            cargo_list=self.cargo_list,
        )
        self.assertTrue(val_result.is_valid, f"Beam search placements must be geometrically valid: {val_result.rejection_reasons}")

    def test_local_search_repair_pass(self):
        """Tests that LocalSearchOptimizer performs gap fill & compaction on remaining cargo."""
        from backend.solver_v2.world.state import WorldState
        from backend.solver_v2.spaces.engine import FreeSpaceEngine
        from backend.solver_v2.orientation.manager import OrientationEngine
        from backend.solver_v2.zones.manager import AdaptiveZoneManager
        from backend.solver_v2.quantity.manager import QuantityManager, SpatialReservationManager

        world_state = WorldState(container=self.container, cargo_catalog=self.cargo_list)
        space_engine = FreeSpaceEngine(container=self.container)
        zone_mgr = AdaptiveZoneManager(container=self.container)
        qty_mgr = QuantityManager(cargo_list=self.cargo_list)
        res_mgr = SpatialReservationManager()
        sku_cat = {s.sku_id: s for s in self.cargo_list}

        # Place a few items initially
        p1 = Placement(
            placement_id="init_0",
            sku_id="SKU_HEAVY",
            position=Point3D(0, 0, 0),
            orientation=Orientation3D(0.8, 0.6, 0.5),
            context=PlacementContext.FOUNDATION,
            weight_kg=60.0,
            instance_id="inst_init_0",
            step_index=0,
        )
        world_state.commit(p1)
        space_engine.on_placement_committed(p1)
        qty_mgr.record_placement("SKU_HEAVY")

        optimizer = LocalSearchOptimizer()
        repair_res = optimizer.run_local_repair_pass(
            world_state=world_state,
            space_engine=space_engine,
            orientation_engine=OrientationEngine(),
            zone_mgr=zone_mgr,
            qty_mgr=qty_mgr,
            res_mgr=res_mgr,
            cargo_catalog=sku_cat,
            max_iterations=10,
        )

        self.assertTrue(repair_res.additional_placements > 0, "Local repair should place additional loose items")
        self.assertTrue(len(world_state.placements) > 1)

        val_result = IndependentGlobalValidator.validate(
            container=self.container,
            placements=world_state.placements,
            cargo_list=self.cargo_list,
        )
        self.assertTrue(val_result.is_valid, "Repaired state must remain strictly valid")

    def test_hierarchical_solver_fast_profile(self):
        """Tests HierarchicalSearchSolver with FAST profile."""
        solver = HierarchicalSearchSolver()
        solution = solver.solve(
            container=self.container,
            cargo_list=self.cargo_list,
            options={"profile": "FAST", "time_budget_sec": 4.0},
        )

        self.assertIn(solution.status, ("SUCCESS", "VALID_PARTIAL"))
        self.assertTrue(solution.placed_count > 0)
        self.assertTrue(solution.validation_result.is_valid)
        self.assertTrue(solution.telemetry.runtime_ms > 0)

    def test_hierarchical_solver_balanced_profile(self):
        """Tests HierarchicalSearchSolver with BALANCED profile."""
        solver = HierarchicalSearchSolver()
        solution = solver.solve(
            container=self.container,
            cargo_list=self.cargo_list,
            options={"profile": "BALANCED", "multi_start_runs": 2, "time_budget_sec": 6.0},
        )

        self.assertIn(solution.status, ("SUCCESS", "VALID_PARTIAL"))
        self.assertTrue(solution.placed_count > 0)
        self.assertTrue(solution.volume_utilization_pct > 0.0)
        self.assertTrue(solution.validation_result.is_valid)

    def test_best_so_far_callback_and_time_budget(self):
        """Tests that on_improvement_callback is invoked and time budget is respected."""
        callback_history = []

        def on_improved(sol_dict, run_idx, score):
            callback_history.append((run_idx, score, sol_dict["placed_count"]))

        solver = HierarchicalSearchSolver()
        t0 = time.perf_counter()
        solution = solver.solve(
            container=self.container,
            cargo_list=self.cargo_list,
            options={
                "profile": "CUSTOM",
                "time_budget_sec": 3.0,
                "multi_start_runs": 4,
                "beam_width": 2,
                "on_improvement_callback": on_improved,
            },
        )
        elapsed = time.perf_counter() - t0

        self.assertTrue(len(callback_history) >= 1, "Best-so-far callback should be triggered at least once")
        self.assertTrue(elapsed < 10.0, "Solver should strictly respect time budget")
        self.assertTrue(solution.validation_result.is_valid)


if __name__ == "__main__":
    unittest.main()
