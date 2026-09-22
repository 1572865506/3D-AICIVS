"""Tests for Transformer Decision Brain and Guided Beam Search Engine.

Validates:
1. PackingTransformer forward pass, dimension consistency, and CUDA device execution.
2. Soft action prior prediction (SKU distribution, spatial guidance, orientation logits).
3. GuidedBeamSearch integration with physical kernel, proving 0-violation hard pruning.
"""

import unittest
import torch

from backend.solver_v2.domain.models import (
    ContainerSpec,
    CargoSKU,
    Point3D,
    OrientationPolicy,
    StackingPolicy,
    QuantityPlan,
    PackingRole,
)
from backend.solver_v2.brain.packing_transformer import PackingTransformer, TransformerConfig
from backend.solver_v2.placement_engine.guided_beam_search import GuidedBeamSearch, SearchConfig
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator


class TestBrainAndSearch(unittest.TestCase):
    """阶段四：决策大脑与引导搜索综合测试"""

    def setUp(self):
        self.container = ContainerSpec(
            code="20GP_TEST",
            inner_dim=Point3D(x=5.898, y=2.352, z=2.393),
            max_payload_kg=28000.0,
            door_zone_length_m=0.6,
        )

        self.skus = [
            CargoSKU(
                sku_id="SKU_HEAVY_BASE",
                name="Heavy Machinery Base",
                box=Point3D(x=1.2, y=1.0, z=0.8),
                weight_kg=800.0,
                quantity=QuantityPlan(required=4),
                stacking_policy=StackingPolicy(
                    max_bearing_kg=3000.0,
                    max_stack_layers=3,
                    must_be_on_floor=True,
                    allow_stacking_on_top=True,
                ),
                orientation_policy=OrientationPolicy(allow_upright=True, allow_flat=False, allow_side=False),
            ),
            CargoSKU(
                sku_id="SKU_STANDARD_BOX",
                name="Industrial Part Carton",
                box=Point3D(x=0.8, y=0.6, z=0.5),
                weight_kg=120.0,
                quantity=QuantityPlan(required=12),
                stacking_policy=StackingPolicy(
                    max_bearing_kg=600.0,
                    max_stack_layers=5,
                    must_be_on_floor=False,
                    allow_stacking_on_top=True,
                ),
                orientation_policy=OrientationPolicy(allow_upright=True, allow_flat=False, allow_side=False),
            ),
            CargoSKU(
                sku_id="SKU_TOP_CUSHION",
                name="Fragile Cushion Block",
                box=Point3D(x=0.5, y=0.5, z=0.3),
                weight_kg=30.0,
                quantity=QuantityPlan(required=6, is_elastic=True),
                stacking_policy=StackingPolicy(
                    max_bearing_kg=0.0,
                    max_stack_layers=1,
                    must_be_on_floor=False,
                    allow_stacking_on_top=False,  # 绝不允许在其上方堆码
                ),
                packing_roles=(PackingRole.FLEXIBLE,),
                orientation_policy=OrientationPolicy(allow_upright=True, allow_flat=True, allow_side=True),
            ),
        ]

    def test_transformer_forward_and_action_prior(self):
        """测试 Transformer 决策大脑前向推导与动作先验输出"""
        cfg = TransformerConfig(d_model=64, nhead=2, num_encoder_layers=2)
        brain = PackingTransformer(config=cfg)

        c_feat = torch.tensor([[5.898, 2.352, 2.393, 28000.0]])
        sku_mat = torch.randn(1, 3, 9)
        state_feat = torch.tensor([[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]])

        out = brain(
            container_features=c_feat,
            sku_matrix=sku_mat,
            state_features=state_feat,
        )

        self.assertEqual(out["sku_logits"].shape, (1, 3))
        self.assertEqual(out["pos_guidance"].shape, (1, 3, 3))
        self.assertEqual(out["rot_logits"].shape, (1, 3, 3))
        self.assertEqual(out["value"].shape, (1, 1))

        # 测试推断先验 API
        priors = brain.predict_action_prior(
            container_features=c_feat,
            sku_matrix=sku_mat,
            state_features=state_feat,
        )
        self.assertEqual(len(priors["sku_probs"]), 3)
        self.assertAlmostEqual(sum(priors["sku_probs"]), 1.0, places=4)
        self.assertGreaterEqual(priors["estimated_value"], 0.0)
        self.assertLessEqual(priors["estimated_value"], 100.0)

        # 若本地 CUDA 可用，验证 GPU 推导
        if torch.cuda.is_available():
            brain_gpu = brain.cuda()
            out_gpu = brain_gpu(c_feat.cuda(), sku_mat.cuda(), state_feat.cuda())
            self.assertEqual(out_gpu["value"].device.type, "cuda")

    def test_guided_beam_search_execution_and_zero_violation(self):
        """测试 GuidedBeamSearch 深度搜索执行，并由独立验证器审计 0 违规保证"""
        searcher = GuidedBeamSearch(
            container=self.container,
            config=SearchConfig(
                beam_width=2,
                time_budget_sec=10.0,
                max_candidates_per_step=8,
            ),
        )

        solution = searcher.solve(
            cargo_list=self.skus,
            options={"time_budget_sec": 5.0, "beam_width": 2},
        )

        self.assertIsNotNone(solution)
        self.assertGreater(solution.placed_count, 0)
        self.assertGreater(solution.volume_utilization_pct, 0.0)

        # 核心铁律审计：独立验证器终审必须 0 违规
        validator = IndependentGlobalValidator()
        audit = validator.validate(
            container=self.container,
            placements=solution.placements,
            cargo_list=self.skus,
        )

        self.assertTrue(audit.is_valid, f"Search solution failed independent validation: {audit.rejection_reasons}")
        self.assertEqual(len(audit.violations), 0, f"Violations found: {audit.violations}")

        # 验证地面件物理约束：若不在地面，必须由同品类合规自叠支撑
        for p in solution.placements:
            if p.sku_id == "SKU_HEAVY_BASE" and p.position.z > 1e-3:
                supporters = [
                    sp for sp in solution.placements
                    if abs((sp.position.z + sp.orientation.dz) - p.position.z) <= 0.005
                    and sp.sku_id == "SKU_HEAVY_BASE"
                ]
                self.assertGreater(len(supporters), 0, "Non-floor SKU_HEAVY_BASE must be supported by same SKU")


if __name__ == "__main__":
    unittest.main()
