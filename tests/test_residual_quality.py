"""
Unit Tests for Residual Space Quality Scorer (TASK-05 Step 5.1).
Validates:
1. Performance criterion: single evaluation < 10ms.
2. Bad Case 001 criteria: ability to distinguish between "good placement" (contiguous wall fill)
   and "bad placement" (premature forward bridging creating enclosed hollow dead-space).
3. Large regular space bonus and fragmentation response.
"""
import unittest
import time
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.domain.models import (
    ContainerSpec,
    BoxDim,
    Placement,
    Point3D,
    Orientation3D,
    PlacementContext,
    CargoSKU,
    QuantityPlan,
)
from backend.solver_v2.world.state import WorldState
from backend.solver_v2.spaces.residual_quality import (
    ResidualQualityScorer,
    ResidualQualityWeights,
    ResidualQualityResult,
)
from backend.solver_v2.candidates.generator import CandidatePlacement


class TestResidualQualityScorer(unittest.TestCase):
    def setUp(self):
        # 40HQ standard test container
        self.container = ContainerSpec(
            code="40HQ_TEST",
            inner_dim=BoxDim(x=12.032, y=2.352, z=2.698),
            max_payload_kg=26000.0,
        )
        self.world_state = WorldState(self.container)
        self.scorer = ResidualQualityScorer(self.container)

        self.sku_wall = CargoSKU(
            sku_id="SKU-WALL",
            name="Wall Carton",
            box=BoxDim(x=0.5, y=0.5, z=0.5),
            weight_kg=10.0,
            quantity=QuantityPlan(required=100),
        )

    def test_single_score_latency_under_10ms(self):
        """验收标准：单次评分调用 < 10ms"""
        p = Placement(
            placement_id="p_init",
            instance_id="inst_init",
            sku_id="SKU-WALL",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(0.5, 0.5, 0.5),
            weight_kg=10.0,
            context=PlacementContext.FOUNDATION,
        )

        # Warmup
        self.scorer.score(self.world_state, p)

        iterations = 50
        t0 = time.perf_counter()
        for _ in range(iterations):
            s = self.scorer.score(self.world_state, p)
        elapsed_total_ms = (time.perf_counter() - t0) * 1000.0
        avg_ms = elapsed_total_ms / iterations

        print(f"\n[PERF] Single score evaluation avg latency: {avg_ms:.3f} ms over {iterations} calls")
        self.assertLess(avg_ms, 10.0, f"Average latency {avg_ms:.2f}ms exceeds 10ms limit")

    def test_distinguish_good_vs_bad_placement_bad_case_001(self):
        """
        验收标准：对已知 bad_case_001，该评分函数能区分"好放置"和"坏放置"。
        bad_case_001 的核心故障特征：前移飞架/封门制造后方空洞死空间（Wall Hollow & Enclosed Cavity）。
        好放置：紧凑贴紧现有货垛连续平铺，保持后方平整无封闭死腔。
        坏放置：直接跨越空隙往前放置，将中间大面积可用空间完全隔断封闭为内部死腔。
        """
        # Commit foundation rear items at x=0.0
        p_rear_1 = Placement("p_r1", "i_r1", "SKU-WALL", Point3D(0.0, 0.0, 0.0), Orientation3D(1.0, 2.352, 1.0), 100.0, PlacementContext.FOUNDATION)
        self.world_state.commit(p_rear_1)

        # Candidate Good: Contiguously place next row at x=1.0, y=0.0, z=0.0
        cand_good = CandidatePlacement(
            sku_id="SKU-WALL",
            position=Point3D(1.0, 0.0, 0.0),
            orientation=Orientation3D(1.0, 2.352, 1.0),
            context=PlacementContext.FOUNDATION,
            weight_kg=100.0,
        )

        # Candidate Bad: Premature forward placement at x=3.0, leaving x in [1.0, 3.0] hollow,
        # but completely sealing the cross-section to create an enclosed internal cavity
        cand_bad = CandidatePlacement(
            sku_id="SKU-WALL",
            position=Point3D(3.0, 0.0, 0.0),
            orientation=Orientation3D(1.0, 2.352, 2.698),
            context=PlacementContext.MAIN_WALL,
            weight_kg=300.0,
        )

        eval_good = self.scorer.evaluate_detailed(self.world_state, cand_good, [self.sku_wall])
        eval_bad = self.scorer.evaluate_detailed(self.world_state, cand_bad, [self.sku_wall])

        print(f"\n[BAD_CASE_001 Test] Good score: {eval_good.score} (cavity: {eval_good.enclosed_cavity_volume}m3)")
        print(f"[BAD_CASE_001 Test] Bad score:  {eval_bad.score} (cavity: {eval_bad.enclosed_cavity_volume}m3)")

        # Verify bad candidate creates enclosed cavity
        self.assertGreater(eval_bad.enclosed_cavity_volume, 1.0, "Bad candidate should create significant cavity")
        self.assertTrue(eval_bad.has_critical_cavity, "Bad candidate must be flagged with critical cavity")

        # Verify good candidate has zero enclosed cavity
        self.assertAlmostEqual(eval_good.enclosed_cavity_volume, 0.0, delta=0.01)
        self.assertFalse(eval_good.has_critical_cavity)

        # Good placement score MUST be significantly higher than bad placement score
        self.assertGreater(eval_good.score, eval_bad.score)
        score_diff = eval_good.score - eval_bad.score
        self.assertGreater(score_diff, 100.0, "Good placement should severely outperform bad placement")

    def test_bridge_void_penalty(self):
        """
        验证跨越悬空（Anti-Bridge Void）能够被识别并施加高额空腔惩罚。
        """
        # Two base pillars with 0.6m gap between them in Y
        p_left = Placement("p_l", "i_l", "SKU-WALL", Point3D(0.0, 0.0, 0.0), Orientation3D(1.0, 0.6, 1.0), 50.0, PlacementContext.FOUNDATION)
        p_right = Placement("p_r", "i_r", "SKU-WALL", Point3D(0.0, 1.4, 0.0), Orientation3D(1.0, 0.6, 1.0), 50.0, PlacementContext.FOUNDATION)
        self.world_state.commit(p_left)
        self.world_state.commit(p_right)

        # Candidate spans across the gap at z=1.0
        cand_bridge = CandidatePlacement(
            sku_id="SKU-WALL",
            position=Point3D(0.0, 0.0, 1.0),
            orientation=Orientation3D(1.0, 2.0, 0.5),
            context=PlacementContext.MAIN_WALL,
            weight_kg=100.0,
        )

        eval_bridge = self.scorer.evaluate_detailed(self.world_state, cand_bridge, [self.sku_wall])
        self.assertTrue(eval_bridge.has_critical_cavity)
        self.assertGreater(eval_bridge.enclosed_cavity_volume, 0.1)

    def test_large_regular_space_bonus(self):
        """
        验证规则的大块剩余空间享有额外奖励 (large_regular_space_bonus)。
        """
        p = Placement("p1", "i1", "SKU-WALL", Point3D(0.0, 0.0, 0.0), Orientation3D(1.0, 1.0, 1.0), 50.0, PlacementContext.FOUNDATION)
        eval_res = self.scorer.evaluate_detailed(self.world_state, p, [self.sku_wall])
        self.assertGreater(eval_res.large_regular_space_bonus, 0.0)

    def test_cavity_hard_constraint_gate(self):
        """
        验证 Step 5.3：空腔硬约束闸门 (ENCLOSED_CAVITY_EXCEEDED)。
        """
        from backend.solver_v2.feasibility.pipeline import HardValidationPipeline
        from backend.solver_v2.zones.manager import AdaptiveZoneManager

        # Seed wall item at x=0.0..1.0
        p_base = Placement(
            "p_base", "item_base", "SKU-WALL",
            Point3D(0.0, 0.0, 0.0), Orientation3D(1.0, 2.352, 2.698),
            500.0, PlacementContext.FOUNDATION,
        )
        self.world_state.commit(p_base)

        # Bad candidate seals cross-section at x=3.0, leaving hollow
        cand_bad = CandidatePlacement(
            sku_id="SKU-WALL",
            position=Point3D(3.0, 0.0, 0.0),
            orientation=Orientation3D(1.0, 2.352, 2.698),
            context=PlacementContext.MAIN_WALL,
            weight_kg=300.0,
        )

        zone_mgr = AdaptiveZoneManager(container=self.container)

        # Without cavity constraint: feasible
        pipeline_unconstrained = HardValidationPipeline(max_allowed_cavity_volume=None)
        is_valid, reason = pipeline_unconstrained.is_feasible(
            cand_bad, self.sku_wall, self.world_state, zone_mgr
        )
        self.assertTrue(is_valid, f"Expected valid without cavity constraint, got {reason}")

        # With cavity threshold 0.05m3: hard rejected
        pipeline_constrained = HardValidationPipeline(max_allowed_cavity_volume=0.05)
        is_valid, reason = pipeline_constrained.is_feasible(
            cand_bad, self.sku_wall, self.world_state, zone_mgr
        )
        self.assertFalse(is_valid, "Expected rejection due to ENCLOSED_CAVITY_EXCEEDED")
        self.assertIn("ENCLOSED_CAVITY_EXCEEDED", reason)
        self.assertEqual(pipeline_constrained.rejection_counts["ENCLOSED_CAVITY_EXCEEDED"], 1)


if __name__ == "__main__":
    unittest.main()

