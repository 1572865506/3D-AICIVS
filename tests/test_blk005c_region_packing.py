"""BLK-005C region-local candidate pool and residual packing checks."""
import unittest

from backend.solver_v2.domain.models import (
    BoxDim, CargoProfile, CargoSKU, ContainerSpec, HandlingPolicy,
    OrientationMode, OrientationPolicy, OrientationRegion, OrientationRule,
    Placement, PlacementContext, Point3D, Orientation3D, PolicySource,
    QuantityPlan, StabilityPolicy, StackingPolicy, TopFillAdmissionState,
    TopFillPolicy,
)
from backend.solver_v2.quantity.manager import QuantityManager
from backend.solver_v2.topfill.planner import ResidualRectangle, TopFillPlanner
from backend.solver_v2.world.state import WorldState


class TestBLK005CRegionPacking(unittest.TestCase):
    def _auto(self, sku_id, box):
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
                min_support_ratio=0.7,
            ),
            handling_policy=HandlingPolicy(keep_upright=True),
        )
        return CargoSKU(
            sku_id, "opaque", box, 2, QuantityPlan(20),
            orientation_policy=orientation, stacking_policy=stacking, cargo_profile=profile,
        )

    def setUp(self):
        self.container = ContainerSpec("C", BoxDim(2, 2, 2), 1000)
        self.base = CargoSKU(
            "BASE", "base", BoxDim(1.2, 1.2, 1.5), 20, QuantityPlan(1),
            stacking_policy=StackingPolicy(max_bearing_kg=500, min_support_ratio=0.7),
        )
        self.a = self._auto("A", BoxDim(0.4, 0.3, 0.2))
        self.b = self._auto("B", BoxDim(0.25, 0.2, 0.15))
        self.cargo = [self.base, self.a, self.b]
        self.catalog = {sku.sku_id: sku for sku in self.cargo}
        self.world = WorldState(self.container, self.cargo)
        self.world.commit(Placement(
            "base", "base_i", "BASE", Point3D(0, 0, 0), Orientation3D(1.2, 1.2, 1.5),
            20, PlacementContext.MAIN_WALL,
        ))
        self.qty = QuantityManager(self.cargo)
        self.qty.record_placement("BASE", PlacementContext.MAIN_WALL)
        self.planner = TopFillPlanner(self.container)

    def test_pool_retains_every_admitted_sku_and_upright_orientation(self):
        region = self.planner.extract_top_fill_regions(self.world, self.catalog, qty_mgr=self.qty)[0]
        pool = self.planner.build_region_candidate_pool(self.world, region, self.qty, self.catalog)
        self.assertEqual({item.sku_id for item in pool}, {"A", "B"})
        self.assertTrue(all(item.orientation.is_upright for item in pool))
        self.assertGreaterEqual(len(pool), 4)  # normal + rotated for both rectangular SKUs

    def test_guillotine_residuals_are_disjoint_on_each_plane(self):
        rect = ResidualRectangle("R", 0, 1.2, 0, 1.2, 1.5, 1)
        pieces = self.planner._normalize_residuals(
            self.planner._split_residual(rect, Orientation3D(0.4, 0.3, 0.2), "FRONT", 1, 3)
        )
        for i, left in enumerate(pieces):
            for right in pieces[i + 1:]:
                if abs(left.base_z - right.base_z) > 1e-6:
                    continue
                overlap_x = min(left.x1, right.x1) - max(left.x0, right.x0)
                overlap_y = min(left.y1, right.y1) - max(left.y0, right.y0)
                self.assertFalse(overlap_x > 1e-6 and overlap_y > 1e-6)

    def test_local_options_include_multiple_skus(self):
        region = self.planner.extract_top_fill_regions(self.world, self.catalog, qty_mgr=self.qty)[0]
        pool = self.planner.build_region_candidate_pool(self.world, region, self.qty, self.catalog)
        residuals = [ResidualRectangle("R", *region.x_range, *region.y_range, region.base_z, 1)]
        options = self.planner._local_options(region, pool, residuals, self.qty)
        self.assertEqual({item[1].sku_id for item in options}, {"A", "B"})


if __name__ == "__main__":
    unittest.main()
