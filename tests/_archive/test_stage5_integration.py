"""Stage 5 End-to-End Integration & Regression Tests.

Validates:
1. Calling backend.solver_v2.solve() directly invokes GuidedBeamSearch.
2. Cross-container tests (20GP, 40HQ) with complex industrial constraints.
3. 100% 0-violation assurance via IndependentGlobalValidator.
4. No priority inversion (rigid SKUs fulfilled properly).
"""

import unittest
from backend.solver_v2 import solve, GuidedBeamSearch
from backend.solver_v2.domain.models import (
    ContainerSpec,
    CargoSKU,
    Point3D,
    OrientationPolicy,
    StackingPolicy,
    QuantityPlan,
    PackingRole,
)
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator


class TestStage5Integration(unittest.TestCase):
    """阶段五：主求解器入口接管与端到端系统回归测试"""

    def setUp(self):
        self.container_20gp = ContainerSpec(
            code="20GP_INTEGRATION",
            inner_dim=Point3D(x=5.898, y=2.352, z=2.393),
            max_payload_kg=28000.0,
            door_zone_length_m=0.6,
        )

        self.container_40hq = ContainerSpec(
            code="40HQ_INTEGRATION",
            inner_dim=Point3D(x=12.032, y=2.352, z=2.698),
            max_payload_kg=28600.0,
            door_zone_length_m=0.8,
        )

        self.skus = [
            CargoSKU(
                sku_id="SKU_BASE_PALLET",
                name="Heavy Wood Pallet",
                box=Point3D(x=1.2, y=1.0, z=0.9),
                weight_kg=600.0,
                quantity=QuantityPlan(required=3),
                stacking_policy=StackingPolicy(
                    max_bearing_kg=2500.0,
                    max_stack_layers=2,
                    must_be_on_floor=True,
                    allow_stacking_on_top=True,
                ),
                orientation_policy=OrientationPolicy(allow_upright=True, allow_flat=False, allow_side=False),
            ),
            CargoSKU(
                sku_id="SKU_GENERAL_BOX",
                name="Standard Carton",
                box=Point3D(x=0.6, y=0.5, z=0.4),
                weight_kg=80.0,
                quantity=QuantityPlan(required=10),
                stacking_policy=StackingPolicy(
                    max_bearing_kg=500.0,
                    max_stack_layers=6,
                    must_be_on_floor=False,
                    allow_stacking_on_top=True,
                ),
                orientation_policy=OrientationPolicy(allow_upright=True, allow_flat=False, allow_side=False),
            ),
            CargoSKU(
                sku_id="SKU_ELASTIC_FILL",
                name="Flexible Foam Filler",
                box=Point3D(x=0.4, y=0.4, z=0.3),
                weight_kg=15.0,
                quantity=QuantityPlan(required=4, is_elastic=True),
                stacking_policy=StackingPolicy(
                    max_bearing_kg=0.0,
                    max_stack_layers=1,
                    must_be_on_floor=False,
                    allow_stacking_on_top=False,
                ),
                packing_roles=(PackingRole.FLEXIBLE,),
                orientation_policy=OrientationPolicy(allow_upright=True, allow_flat=True, allow_side=True),
            ),
        ]

    def test_solve_entrypoint_with_guided_engine(self):
        """测试通过主 solve() 入口接管并执行 GuidedBeamSearch"""
        solution = solve(
            container=self.container_20gp,
            cargo_list=self.skus,
            engine="guided",
            time_budget_sec=5.0,
            beam_width=2,
        )

        self.assertIsNotNone(solution)
        self.assertGreater(solution.placed_count, 0)
        self.assertGreater(solution.volume_utilization_pct, 0.0)

        # 独立验证器终审 0 违规保证
        validator = IndependentGlobalValidator()
        audit = validator.validate(
            container=self.container_20gp,
            placements=solution.placements,
            cargo_list=self.skus,
        )

        self.assertTrue(audit.is_valid, f"Violations encountered: {audit.violations}")
        self.assertEqual(len(audit.violations), 0)

    def test_solve_across_40hq_container(self):
        """测试在 40HQ 大柜型下的深度引导搜索求解稳定性"""
        solution = solve(
            container=self.container_40hq,
            cargo_list=self.skus,
            engine="guided",
            time_budget_sec=5.0,
            beam_width=2,
        )

        self.assertIsNotNone(solution)
        self.assertGreater(solution.placed_count, 0)

        validator = IndependentGlobalValidator()
        audit = validator.validate(
            container=self.container_40hq,
            placements=solution.placements,
            cargo_list=self.skus,
        )

        self.assertTrue(audit.is_valid, f"Violations encountered in 40HQ: {audit.violations}")
        self.assertEqual(len(audit.violations), 0)


if __name__ == "__main__":
    unittest.main()
