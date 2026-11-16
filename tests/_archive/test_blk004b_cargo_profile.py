"""BLK-004B declarative CargoProfile integration checks."""
import unittest

from run_blk003_benchmark import load_dataset
from backend.solver_v2.domain.models import (
    BoxDim, CargoClass, CargoSKU, ContainerSpec, OrientationMode,
    Placement, PlacementContext, Point3D, Orientation3D, QuantityPlan,
    StackingPolicy,
)
from backend.solver_v2.orientation.manager import OrientationEngine
from backend.solver_v2.physics.load_propagation import LoadPropagationEngine
from backend.solver_v2.physics.support_graph import SupportGraph


DATASET = "devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json"


class TestBLK004BCargoProfile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container, cls.cargo = load_dataset(DATASET)
        cls.catalog = {sku.sku_id: sku for sku in cls.cargo}

    def test_all_14_skus_have_explicit_profiles_and_sources(self):
        self.assertEqual(len(self.cargo), 14)
        for sku in self.cargo:
            self.assertIsNotNone(sku.cargo_profile)
            self.assertTrue(sku.cargo_profile.source_audit)

    def test_requirement_text_does_not_drive_profile_path(self):
        sku = self.catalog["SKU-14"]
        self.assertTrue(sku.quantity.is_elastic)
        self.assertTrue(sku.cargo_profile.placement_policy.reduction_allowed)
        self.assertEqual(sku.target_zone.value, "DOOR")

    def test_main_body_conditional_flat_is_forbidden(self):
        for sku in self.cargo:
            main = OrientationEngine().get_candidate_orientations(sku, PlacementContext.MAIN_WALL)
            self.assertFalse(any(candidate.orientation.is_flat for candidate in main), sku.sku_id)
        top = OrientationEngine().get_candidate_orientations(
            self.catalog["SKU-14"], PlacementContext.TOP_FILL, base_height=1.64, min_support_ratio=1.0,
        )
        self.assertTrue(any(candidate.orientation.is_flat for candidate in top))

    def test_load_engine_enforces_stack_category_policy(self):
        container = ContainerSpec("C", BoxDim(2, 2, 2), 1000)
        lower = CargoSKU(
            "LOW", "opaque", BoxDim(1, 1, 1), 10, QuantityPlan(1),
            stacking_policy=StackingPolicy(forbidden_above_categories=(CargoClass.FRAGILE,)),
        )
        upper = CargoSKU(
            "UP", "opaque", BoxDim(1, 1, 0.5), 5, QuantityPlan(1),
            cargo_class=CargoClass.FRAGILE,
        )
        graph = SupportGraph(container)
        graph.add_placement(Placement("low", "li", "LOW", Point3D(0, 0, 0), Orientation3D(1, 1, 1), 10, PlacementContext.MAIN_WALL))
        graph.add_placement(Placement("up", "ui", "UP", Point3D(0, 0, 1), Orientation3D(1, 1, 0.5), 5, PlacementContext.TOP_FILL))
        report = LoadPropagationEngine().compute_loads(graph, {"LOW": lower, "UP": upper})
        self.assertFalse(report.is_valid)
        self.assertTrue(report.item_reports["low"].is_no_stack_violated)


if __name__ == "__main__":
    unittest.main()
