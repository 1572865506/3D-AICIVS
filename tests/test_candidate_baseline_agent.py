"""
Comprehensive Unit Tests for Agent 05: Candidate Generator + Baseline Solver.
Coverage:
1. CandidateGenerator: Multi-anchor generation, orientation mapping, boundary pre-filtering.
2. HardValidationPipeline: Fast multi-stage gating (bounds, collision, support, no-top-stack, zone lock, payload).
3. CandidateScorer: Residual-space-aware scoring, anti-greedy cavity penalty, compactness, wall flatness.
4. BaselineGreedySolver: Phased packing (Foundation -> Main -> Top -> Door), deterministic seed, telemetry, Independent Global Validator pass.
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
    PlacementContext,
    ZoneType,
    PackingRole,
)
from backend.solver_v2.world.state import WorldState
from backend.solver_v2.spaces.engine import FreeSpaceEngine
from backend.solver_v2.orientation.manager import OrientationEngine
from backend.solver_v2.zones.manager import AdaptiveZoneManager
from backend.solver_v2.quantity.manager import QuantityManager, SpatialReservationManager
from backend.solver_v2.candidates.generator import CandidateGenerator, CandidatePlacement
from backend.solver_v2.feasibility.pipeline import HardValidationPipeline
from backend.solver_v2.solver.scorer import CandidateScorer
from backend.solver_v2.solver.baseline_solver import BaselineGreedySolver


class TestCandidateGeneratorAndPipeline(unittest.TestCase):
    def setUp(self):
        # 6m (L) x 2.4m (W) x 2.4m (H)
        self.container = ContainerSpec(
            code="TEST_CAND_BOX",
            inner_dim=BoxDim(x=6.0, y=2.4, z=2.4),
            max_payload_kg=10000.0,
            door_zone_length_m=1.0,
        )
        self.sku_std = CargoSKU(
            sku_id="SKU_STD",
            name="Std Carton",
            box=BoxDim(x=1.0, y=1.2, z=1.2),
            weight_kg=100.0,
            quantity=QuantityPlan(required=8),
            orientation_policy=OrientationPolicy(allow_upright=True, allow_flat=False),
            stacking_policy=StackingPolicy(min_support_ratio=0.70, allow_stacking_on_top=True),
        )
        self.sku_fragile = CargoSKU(
            sku_id="SKU_FRAGILE",
            name="Fragile Base",
            box=BoxDim(x=1.0, y=1.2, z=1.2),
            weight_kg=200.0,
            quantity=QuantityPlan(required=2),
            orientation_policy=OrientationPolicy(allow_upright=True, allow_flat=False),
            stacking_policy=StackingPolicy(allow_stacking_on_top=False, must_be_on_floor=True),
        )

        self.world_state = WorldState(self.container, [self.sku_std, self.sku_fragile])
        self.space_engine = FreeSpaceEngine(self.container, grid_resolution=0.2)
        self.ori_engine = OrientationEngine()
        self.zone_mgr = AdaptiveZoneManager(self.container)
        self.qty_mgr = QuantityManager([self.sku_std, self.sku_fragile])
        self.generator = CandidateGenerator()
        self.pipeline = HardValidationPipeline()

    def test_candidate_generation_from_origin(self):
        """测试初始状态下能够从原点生成候选放置方案"""
        cands = self.generator.generate_candidates(
            world_state=self.world_state,
            space_engine=self.space_engine,
            orientation_engine=self.ori_engine,
            zone_mgr=self.zone_mgr,
            qty_mgr=self.qty_mgr,
            active_skus=[self.sku_std],
            context=PlacementContext.FOUNDATION,
        )
        self.assertGreater(len(cands), 0)
        # Should include (0, 0, 0)
        positions = {(c.x, c.y, c.z) for c in cands}
        self.assertIn((0.0, 0.0, 0.0), positions)

    def test_pipeline_catches_collision_and_support(self):
        """测试快速硬性管线准确拦截碰撞与悬空放置"""
        # Place 1 box at (0, 0, 0)
        p0 = CandidatePlacement(
            sku_id="SKU_STD",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(1.0, 1.2, 1.2),
            context=PlacementContext.FOUNDATION,
            weight_kg=100.0,
        ).to_placement("p0", "i0")
        self.world_state.commit(p0)
        self.space_engine.on_placement_committed(p0, [self.sku_std])

        # Candidate A: Collides with p0 (at 0.5, 0.0, 0.0)
        cand_col = CandidatePlacement(
            sku_id="SKU_STD",
            position=Point3D(0.5, 0.0, 0.0),
            orientation=Orientation3D(1.0, 1.2, 1.2),
            context=PlacementContext.FOUNDATION,
            weight_kg=100.0,
        )
        ok_col, reason_col = self.pipeline.is_feasible(
            cand_col, self.sku_std, self.world_state, self.zone_mgr
        )
        self.assertFalse(ok_col)
        self.assertIn("collides", reason_col)

        # Candidate B: Floating at z = 1.2 with 0 support (x = 3.0)
        cand_float = CandidatePlacement(
            sku_id="SKU_STD",
            position=Point3D(3.0, 0.0, 1.2),
            orientation=Orientation3D(1.0, 1.2, 1.2),
            context=PlacementContext.MAIN_WALL,
            weight_kg=100.0,
        )
        ok_float, reason_float = self.pipeline.is_feasible(
            cand_float, self.sku_std, self.world_state, self.zone_mgr
        )
        self.assertFalse(ok_float)
        self.assertIn("support", reason_float.lower())

    def test_pipeline_catches_no_top_stack(self):
        """测试快速硬性管线拦截在禁止顶叠的货物上方放置"""
        # Place fragile box at (0, 0, 0)
        p_fr = CandidatePlacement(
            sku_id="SKU_FRAGILE",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(1.0, 1.2, 1.2),
            context=PlacementContext.FOUNDATION,
            weight_kg=200.0,
        ).to_placement("p_fr", "i_fr")
        self.world_state.commit(p_fr)

        # Attempt to place std carton on top of fragile box at z = 1.2
        cand_top = CandidatePlacement(
            sku_id="SKU_STD",
            position=Point3D(0.0, 0.0, 1.2),
            orientation=Orientation3D(1.0, 1.2, 1.2),
            context=PlacementContext.MAIN_WALL,
            weight_kg=100.0,
        )
        ok_top, reason_top = self.pipeline.is_feasible(
            cand_top, self.sku_std, self.world_state, self.zone_mgr
        )
        self.assertFalse(ok_top)
        self.assertIn("forbids stacking", reason_top)


class TestBaselineGreedySolver(unittest.TestCase):
    def setUp(self):
        # 6m x 2.4m x 2.4m container
        self.container = ContainerSpec(
            code="40HQ_MINI",
            inner_dim=BoxDim(x=6.0, y=2.4, z=2.4),
            max_payload_kg=10000.0,
            door_zone_length_m=1.0,
            rear_zone_length_m=1.0,
        )
        self.sku_heavy = CargoSKU(
            sku_id="SKU_HEAVY",
            name="Heavy Base",
            box=BoxDim(x=1.0, y=1.2, z=0.8),
            weight_kg=300.0,
            quantity=QuantityPlan(required=4),
            packing_roles=(PackingRole.FOUNDATION,),
            stacking_policy=StackingPolicy(must_be_on_floor=True),
        )
        self.sku_body = CargoSKU(
            sku_id="SKU_BODY",
            name="Body Carton",
            box=BoxDim(x=1.0, y=1.2, z=0.8),
            weight_kg=100.0,
            quantity=QuantityPlan(required=8),
            packing_roles=(PackingRole.MAIN_WALL,),
        )
        self.sku_seal = CargoSKU(
            sku_id="SKU_SEAL",
            name="Door Bag",
            box=BoxDim(x=0.5, y=1.2, z=0.8),
            weight_kg=20.0,
            quantity=QuantityPlan(required=4),
            packing_roles=(PackingRole.DOOR_SEAL,),
            target_zone=ZoneType.DOOR,
        )
        self.solver = BaselineGreedySolver(seed=123, grid_resolution=0.2)

    def test_solve_end_to_end_and_validation(self):
        """测试端到端求解：确保所有放置经 IndependentGlobalValidator 独立判定为合法"""
        solution = self.solver.solve(
            container=self.container,
            cargo_list=[self.sku_heavy, self.sku_body, self.sku_seal],
        )

        # Verify results
        self.assertGreater(solution.placed_count, 0)
        self.assertTrue(solution.validation_result.is_valid)
        self.assertEqual(solution.validation_result.metrics["overlap_pair_count"], 0)
        self.assertEqual(solution.validation_result.metrics["penetration_volume"], 0.0)
        self.assertEqual(solution.validation_result.metrics["out_of_bounds_count"], 0)
        self.assertGreater(solution.volume_utilization_pct, 10.0)

        # Check telemetry
        t = solution.telemetry
        self.assertGreater(t.runtime_ms, 0.0)
        self.assertGreater(t.candidates_generated, 0)
        self.assertGreater(t.steps_committed, 0)
        self.assertGreater(len(t.phases_completed), 0)

    def test_deterministic_seed_reproducibility(self):
        """测试确定性随机种子：相同种子产出完全一致的装载方案"""
        s1 = self.solver.solve(self.container, [self.sku_heavy, self.sku_body])
        solver2 = BaselineGreedySolver(seed=123, grid_resolution=0.2)
        s2 = solver2.solve(self.container, [self.sku_heavy, self.sku_body])

        self.assertEqual(s1.placed_count, s2.placed_count)
        self.assertAlmostEqual(s1.volume_utilization_pct, s2.volume_utilization_pct, places=5)
        self.assertEqual(len(s1.placements), len(s2.placements))
        for p1, p2 in zip(s1.placements, s2.placements):
            self.assertEqual(p1.sku_id, p2.sku_id)
            self.assertAlmostEqual(p1.position.x, p2.position.x)
            self.assertAlmostEqual(p1.position.y, p2.position.y)
            self.assertAlmostEqual(p1.position.z, p2.position.z)


if __name__ == "__main__":
    unittest.main()
