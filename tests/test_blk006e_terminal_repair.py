"""TFR-001..012 acceptance tests for BLK-006E terminal repair."""
import unittest

from backend.solver_v2.domain.models import (
    BoxDim, CargoProfile, CargoSKU, ContainerSpec, HandlingPolicy,
    OrientationMode, OrientationPolicy, OrientationRegion, OrientationRule,
    Orientation3D, Placement, PlacementContext, Point3D, PolicySource,
    QuantityPlan, StabilityPolicy, StackingPolicy, TopFillAdmissionState,
    TopFillPolicy,
)
from backend.solver_v2.topfill.terminal_repair import (
    PLAN_FAMILIES, TerminalRepairConfig, TerminalTopFillRepairOptimizer,
)


class TestBLK006ETerminalRepair(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec("TFR", BoxDim(2.0, 2.0, 2.0), 2000)
        upright = OrientationPolicy(rules=(OrientationRule(
            OrientationMode.UPRIGHT,
            (OrientationRegion.MAIN_BODY, OrientationRegion.TOP_FILL, OrientationRegion.DOOR_ZONE),
        ),))
        stack = StackingPolicy(max_bearing_kg=500, min_support_ratio=0.7)
        auto = CargoProfile(
            orientation_policy=upright, stack_policy=stack,
            stability_policy=StabilityPolicy(min_support_ratio=0.7),
            top_fill_policy=TopFillPolicy(
                source=PolicySource.DEFAULT, admission_state=TopFillAdmissionState.AUTO,
                min_support_ratio=0.7,
            ),
            handling_policy=HandlingPolicy(keep_upright=True),
        )
        self.base_sku = CargoSKU(
            "BASE", "opaque", BoxDim(1.2, 1.2, 1.4), 20, QuantityPlan(4),
            orientation_policy=upright, stacking_policy=stack, cargo_profile=auto,
        )
        self.fill_sku = CargoSKU(
            "FILL", "opaque", BoxDim(0.4, 0.3, 0.2), 2, QuantityPlan(20),
            orientation_policy=upright, stacking_policy=stack, cargo_profile=auto,
        )
        self.cargo = [self.base_sku, self.fill_sku]
        self.optimizer = TerminalTopFillRepairOptimizer(self.container, self.cargo)
        self.base = Placement(
            "base", "base_i", "BASE", Point3D(0, 0, 0),
            Orientation3D(1.2, 1.2, 1.4, "UPRIGHT_NORMAL", is_upright=True),
            20, PlacementContext.MAIN_WALL,
        )

    def test_tfr_001_all_plan_families_declared(self):
        self.assertEqual(len(PLAN_FAMILIES), 8)

    def test_tfr_002_multiple_plans_per_region(self):
        _, plans = self.optimizer._describe_plans([self.base])
        by_region = {}
        for plan in plans:
            by_region.setdefault(plan["region_id"], set()).add(plan["plan_family"])
        self.assertTrue(by_region)
        self.assertTrue(all(len(families) == 8 for families in by_region.values()))

    def test_tfr_003_region_classification_is_explicit(self):
        regions, _ = self.optimizer._describe_plans([self.base])
        allowed = {"LARGE_CONTINUOUS", "LONG_STRIP", "NARROW_STRIP", "RECTANGULAR_POCKET",
                   "STEP_REGION", "MULTI_LEVEL_REGION", "SMALL_FRAGMENT"}
        self.assertTrue(all(row["classification"] in allowed for row in regions))

    def test_tfr_004_fast_profile_disables_wall_replacement(self):
        cfg = TerminalRepairConfig.for_profile("FAST")
        self.assertFalse(cfg.enable_stage_b)
        self.assertFalse(cfg.enable_stage_c)

    def test_tfr_005_balanced_profile_bounds_stage_c(self):
        cfg = TerminalRepairConfig.for_profile("BALANCED")
        self.assertTrue(cfg.enable_stage_b)
        self.assertFalse(cfg.enable_stage_c)

    def test_tfr_006_optimize_profile_bounds_two_wall_stage(self):
        cfg = TerminalRepairConfig.for_profile("OPTIMIZE")
        self.assertTrue(cfg.enable_stage_b and cfg.enable_stage_c)
        self.assertLessEqual(cfg.overall_budget_sec, 90)

    def test_tfr_007_auto_never_manufactures_flat(self):
        world, qty = self.optimizer._build_state([self.base])
        region = self.optimizer.planner.extract_top_fill_regions(world, self.optimizer.catalog, qty_mgr=qty)[0]
        pool = self.optimizer.planner.build_region_candidate_pool(world, region, qty, self.optimizer.catalog)
        self.assertTrue(pool)
        self.assertTrue(all(item.orientation.is_upright for item in pool))

    def test_tfr_008_inventory_replay_is_exact(self):
        _, qty = self.optimizer._build_state([self.base])
        self.assertEqual(qty.get_remaining("BASE"), 3)

    def test_tfr_009_last_wall_neighborhood_is_bounded(self):
        variants = self.optimizer._terminal_wall_variants([self.base], 1)
        self.assertGreaterEqual(len(variants), 1)
        self.assertLessEqual(len(variants), 3)

    def test_tfr_010_invalid_parent_rolls_back(self):
        result = self.optimizer.optimize([])
        self.assertFalse(result.accepted)
        self.assertEqual(result.placements, [])

    def test_tfr_011_lookahead_depth_is_bounded(self):
        self.assertIn(self.optimizer.config.lookahead_depth, (2, 3))

    def test_tfr_012_plan_generation_is_deterministic(self):
        first = self.optimizer._describe_plans([self.base])
        second = self.optimizer._describe_plans([self.base])
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
