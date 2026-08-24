"""BLK-004 Conditional Top Fill Planner acceptance cases TOP-001 through TOP-012."""
import unittest

from backend.solver_v2.domain.models import (
    BoxDim, Point3D, Orientation3D, OrientationPolicy, OrientationRule,
    OrientationMode, OrientationRegion, StackingPolicy, QuantityPlan,
    ContainerSpec, CargoSKU, Placement, PlacementContext, PackingRole,
)
from backend.solver_v2.world.state import WorldState
from backend.solver_v2.orientation.manager import OrientationEngine
from backend.solver_v2.topfill.planner import TopFillPlanner, TopFillRegion
from backend.solver_v2.candidates.generator import CandidatePlacement


class TestBLK004ConditionalTopFill(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec("TOP_TEST", BoxDim(3.0, 2.0, 3.0), 20000.0)
        self.base = CargoSKU(
            "BASE", "Rigid Base", BoxDim(1.2, 1.2, 2.4), 50.0, QuantityPlan(20),
            stacking_policy=StackingPolicy(max_bearing_kg=500.0, min_support_ratio=0.8),
            packing_roles=(PackingRole.MAIN_WALL,),
        )
        self.display = self._top_sku("DISPLAY", BoxDim(0.6, 0.12, 0.4), max_layers=3)
        self.catalog = {s.sku_id: s for s in (self.base, self.display)}
        self.planner = TopFillPlanner(self.container)

    def _top_sku(self, sku_id, box, max_layers=3, weight=5.0):
        return CargoSKU(
            sku_id, sku_id, box, weight, QuantityPlan(30),
            orientation_policy=OrientationPolicy(
                allow_upright=True,
                allow_flat=True,
                max_flat_stack_layers=max_layers,
                rules=(
                    OrientationRule(
                        OrientationMode.UPRIGHT,
                        (OrientationRegion.MAIN_BODY, OrientationRegion.TOP_FILL),
                    ),
                    OrientationRule(
                        OrientationMode.FLAT,
                        (OrientationRegion.TOP_FILL,),
                        min_support_ratio=0.8,
                        max_top_fill_layers=max_layers,
                        condition="UPRIGHT_DOES_NOT_FIT",
                    ),
                ),
            ),
            stacking_policy=StackingPolicy(
                max_bearing_kg=100.0,
                min_support_ratio=0.8,
                max_unsupported_span_m=0.05,
            ),
            packing_roles=(PackingRole.MAIN_WALL, PackingRole.TOP_FILL),
        )

    def _world_with_base(self, height):
        world = WorldState(self.container, list(self.catalog.values()))
        world.commit(Placement(
            "base", "base_i", "BASE", Point3D(0.0, 0.0, 0.0),
            Orientation3D(1.2, 1.2, height), 50.0, PlacementContext.MAIN_WALL,
        ))
        return world

    def _region(self, world):
        return self.planner.extract_top_fill_regions(world, self.catalog)[0]

    def test_top_001_upright_fits_do_not_force_flat(self):
        world = self._world_with_base(2.4)
        candidates = self.planner.generate_region_candidates(world, [self.display], cargo_catalog=self.catalog)
        self.assertTrue(candidates)
        self.assertTrue(all(c.orientation.is_upright for c in candidates))

    def test_top_002_upright_does_not_fit_flat_one_layer(self):
        world = self._world_with_base(2.87)
        region = self._region(world)
        candidates = self.planner.generate_region_candidates(world, [self.display], cargo_catalog=self.catalog)
        self.assertTrue(candidates)
        self.assertTrue(all(c.orientation.is_flat for c in candidates))
        self.assertEqual(candidates[0].topfill_layer_capacity, 1)

    def test_top_003_flat_two_layers(self):
        world = self._world_with_base(2.75)
        candidates = self.planner.generate_region_candidates(world, [self.display], cargo_catalog=self.catalog)
        self.assertEqual(candidates[0].topfill_layer_capacity, 2)

    def test_top_004_flat_three_layers(self):
        world = self._world_with_base(2.63)
        candidates = self.planner.generate_region_candidates(world, [self.display], cargo_catalog=self.catalog)
        self.assertEqual(candidates[0].topfill_layer_capacity, 3)

    def test_top_005_exceeds_max_top_fill_layers(self):
        world = self._world_with_base(2.4)
        for layer in range(3):
            world.commit(Placement(
                f"flat_{layer}", f"flat_i_{layer}", "DISPLAY", Point3D(0.0, 0.0, 2.4 + layer * 0.12),
                Orientation3D(0.6, 0.4, 0.12, "FLAT_XZ", False, True),
                5.0, PlacementContext.TOP_FILL,
            ))
        candidate = Placement(
            "flat_4", "flat_i_4", "DISPLAY", Point3D(0.0, 0.0, 2.76),
            Orientation3D(0.6, 0.4, 0.12, "FLAT_XZ", False, True),
            5.0, PlacementContext.TOP_FILL,
        )
        result = self.planner.evaluate_conditional_flat_placement(
            self.display, candidate, world, catalog=self.catalog,
        )
        self.assertFalse(result.flat_layer_limit_passed)
        self.assertEqual(result.flat_layer_count, 4)

    def test_top_006_insufficient_support(self):
        world = WorldState(self.container, list(self.catalog.values()))
        world.commit(Placement(
            "narrow", "narrow_i", "BASE", Point3D(0, 0, 0),
            Orientation3D(0.6, 0.2, 2.8), 50.0, PlacementContext.MAIN_WALL,
        ))
        candidate = Placement(
            "top", "top_i", "DISPLAY", Point3D(0, 0, 2.8),
            Orientation3D(0.6, 0.4, 0.12, "FLAT_XZ", False, True), 5.0, PlacementContext.TOP_FILL,
        )
        result = self.planner.evaluate_conditional_flat_placement(self.display, candidate, world, catalog=self.catalog)
        self.assertFalse(result.support_ratio_passed)

    def test_top_007_compression_failure(self):
        fragile = CargoSKU(
            "FRAGILE", "Fragile", BoxDim(1.2, 1.2, 2.8), 20.0, QuantityPlan(1),
            stacking_policy=StackingPolicy(max_bearing_kg=2.0, min_support_ratio=0.8),
        )
        catalog = {"FRAGILE": fragile, "DISPLAY": self.display}
        world = WorldState(self.container, list(catalog.values()))
        world.commit(Placement("fragile", "fi", "FRAGILE", Point3D(0, 0, 0), Orientation3D(1.2, 1.2, 2.8), 20.0, PlacementContext.MAIN_WALL))
        region = self.planner.extract_top_fill_regions(world, catalog)[0]
        cand = CandidatePlacement("DISPLAY", Point3D(0, 0, 2.8), Orientation3D(0.6, 0.4, 0.12, "FLAT_XZ", False, True), PlacementContext.TOP_FILL, 5.0, topfill_region_id=region.region_id, topfill_layer_capacity=1)
        result = self.planner.evaluate_topfill_candidate(cand, self.display, region, world, catalog)
        self.assertFalse(result.compression_passed)
        self.assertFalse(result.is_valid)

    def test_top_008_unsupported_span_failure(self):
        world = WorldState(self.container, list(self.catalog.values()))
        for idx, x in enumerate((0.0, 0.4)):
            world.commit(Placement(f"support_{idx}", f"si_{idx}", "BASE", Point3D(x, 0, 0), Orientation3D(0.2, 0.4, 2.8), 20.0, PlacementContext.MAIN_WALL))
        candidate = Placement("span", "span_i", "DISPLAY", Point3D(0, 0, 2.8), Orientation3D(0.6, 0.4, 0.12, "FLAT_XZ", False, True), 5.0, PlacementContext.TOP_FILL)
        result = self.planner.evaluate_conditional_flat_placement(self.display, candidate, world, catalog=self.catalog)
        self.assertFalse(result.unsupported_span_passed)
        self.assertGreaterEqual(result.unsupported_span_m, 0.2)

    def test_top_009_main_body_flat_forbidden(self):
        orientations = OrientationEngine().get_candidate_orientations(self.display, PlacementContext.MAIN_WALL)
        self.assertTrue(orientations)
        self.assertFalse(any(o.orientation.is_flat for o in orientations))

    def test_top_010_mixed_topfill_skus(self):
        other = self._top_sku("OTHER", BoxDim(0.4, 0.10, 0.3), max_layers=2, weight=3.0)
        catalog = {**self.catalog, "OTHER": other}
        world = WorldState(self.container, list(catalog.values()))
        world.commit(Placement("base", "bi", "BASE", Point3D(0, 0, 0), Orientation3D(1.2, 1.2, 2.75), 50.0, PlacementContext.MAIN_WALL))
        candidates = self.planner.generate_region_candidates(world, [self.display, other], cargo_catalog=catalog)
        self.assertEqual({c.sku_id for c in candidates}, {"DISPLAY", "OTHER"})

    def test_top_011_residual_height_optimization(self):
        region = TopFillRegion("R", "W", (0, 1.2), (0, 1.2), 2.74, 0.26, 1.44, 1.0, 1.0, 100.0, ("DISPLAY",))
        shorter = CandidatePlacement("DISPLAY", Point3D(0, 0, 2.74), Orientation3D(0.6, 0.4, 0.10, "FLAT_A", False, True), PlacementContext.TOP_FILL, 5.0)
        taller = CandidatePlacement("DISPLAY", Point3D(0, 0, 2.74), Orientation3D(0.6, 0.4, 0.13, "FLAT_B", False, True), PlacementContext.TOP_FILL, 5.0)
        self.assertGreater(sum(self.planner.score_topfill_candidate(taller, self.display, region).values()), sum(self.planner.score_topfill_candidate(shorter, self.display, region).values()))

    def test_top_012_irregular_top_surface(self):
        world = WorldState(self.container, list(self.catalog.values()))
        world.commit(Placement("low", "li", "BASE", Point3D(0, 0, 0), Orientation3D(0.6, 1.2, 2.5), 20.0, PlacementContext.MAIN_WALL))
        world.commit(Placement("high", "hi", "BASE", Point3D(0.6, 0, 0), Orientation3D(0.6, 1.2, 2.8), 20.0, PlacementContext.MAIN_WALL))
        regions = self.planner.extract_top_fill_regions(world, self.catalog)
        self.assertGreaterEqual(len(regions), 2)
        self.assertEqual({round(r.base_z, 1) for r in regions}, {2.5, 2.8})


if __name__ == "__main__":
    unittest.main()
