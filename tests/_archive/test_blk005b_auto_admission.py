"""BLK-005B tri-state policy and AUTO Safe Admission checks."""
import unittest

from backend.solver_v2.domain.models import (
    BoxDim, CargoProfile, CargoSKU, ContainerSpec, HandlingPolicy,
    OrientationMode, OrientationPolicy, OrientationRegion, OrientationRule,
    Placement, PlacementContext, Point3D, Orientation3D, PolicySource,
    QuantityPlan, StabilityPolicy, StackingPolicy, TopFillAdmissionState,
    TopFillPolicy,
)
from backend.solver_v2.orientation.manager import OrientationEngine
from backend.solver_v2.topfill.planner import TopFillPlanner
from backend.solver_v2.world.state import WorldState
from run_blk003_benchmark import load_dataset


DATASET = "devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json"


class TestBLK005BAutoAdmission(unittest.TestCase):
    def _auto_sku(self, sku_id="AUTO", box=BoxDim(0.4, 0.3, 0.2)):
        orientation = OrientationPolicy(rules=(
            OrientationRule(OrientationMode.UPRIGHT, (OrientationRegion.MAIN_BODY, OrientationRegion.TOP_FILL)),
        ))
        stacking = StackingPolicy(max_bearing_kg=100, min_support_ratio=0.7)
        profile = CargoProfile(
            orientation_policy=orientation,
            stack_policy=stacking,
            stability_policy=StabilityPolicy(min_support_ratio=0.7),
            top_fill_policy=TopFillPolicy(
                source=PolicySource.DEFAULT,
                admission_state=TopFillAdmissionState.AUTO,
                enabled=False,
                max_layers=0,
                min_support_ratio=0.7,
            ),
            handling_policy=HandlingPolicy(keep_upright=True),
        )
        return CargoSKU(
            sku_id, "opaque", box, 5, QuantityPlan(10),
            orientation_policy=orientation, stacking_policy=stacking, cargo_profile=profile,
        )

    def test_canonical_default_profiles_are_auto_and_user_profiles_allow(self):
        _, cargo = load_dataset(DATASET)
        states = {sku.sku_id: sku.cargo_profile.top_fill_policy.admission_state for sku in cargo}
        self.assertEqual(states["SKU-03"], TopFillAdmissionState.AUTO)
        self.assertEqual(states["SKU-02"], TopFillAdmissionState.ALLOW)
        self.assertEqual(states["SKU-14"], TopFillAdmissionState.ALLOW)
        self.assertEqual(next(s for s in cargo if s.sku_id == "SKU-02").cargo_profile.top_fill_policy.min_base_height, 2.5)
        self.assertEqual(next(s for s in cargo if s.sku_id == "SKU-14").cargo_profile.top_fill_policy.min_base_height, 1.3)

    def test_auto_inherits_upright_only_and_never_gains_flat(self):
        sku = self._auto_sku()
        top = OrientationEngine().get_candidate_orientations(sku, PlacementContext.TOP_FILL)
        self.assertTrue(top)
        self.assertTrue(all(candidate.orientation.is_upright for candidate in top))
        self.assertFalse(any(candidate.orientation.is_flat for candidate in top))

    def test_auto_safe_admission_pass_and_geometry_rejection(self):
        container = ContainerSpec("C", BoxDim(2, 2, 2), 1000)
        base = CargoSKU(
            "BASE", "opaque", BoxDim(1, 1, 1.5), 20, QuantityPlan(1),
            stacking_policy=StackingPolicy(max_bearing_kg=100, min_support_ratio=0.7),
        )
        auto = self._auto_sku()
        too_large = self._auto_sku("LARGE", BoxDim(3, 3, 0.2))
        world = WorldState(container, [base, auto, too_large])
        world.commit(Placement(
            "base", "bi", "BASE", Point3D(0, 0, 0), Orientation3D(1, 1, 1.5),
            20, PlacementContext.MAIN_WALL,
        ))
        planner = TopFillPlanner(container)
        region = planner.extract_top_fill_regions(world, {s.sku_id: s for s in (base, auto, too_large)})[0]
        passed = planner.diagnose_region_admission(world, region, auto, True)
        failed = planner.diagnose_region_admission(world, region, too_large, True)
        self.assertTrue(passed.admitted)
        self.assertEqual(passed.rejection_reason, "AUTO_PASS")
        self.assertGreater(passed.effective_max_layers, 0)
        self.assertFalse(failed.admitted)
        self.assertEqual(failed.rejection_reason, "AUTO_GEOMETRY_FAIL")


if __name__ == "__main__":
    unittest.main()
