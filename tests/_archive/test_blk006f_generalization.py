"""BLK-006F generic regression checks discovered by the benchmark suite."""
import unittest

from backend.solver_v2.domain.models import (
    BoxDim, CargoSKU, ContainerSpec, Orientation3D, Placement, PlacementContext,
    Point3D, QuantityPlan,
)
from backend.solver_v2.search.global_wall_search import FutureTopFillEstimator, WallCandidate


class TestBLK006FGeneralization(unittest.TestCase):
    def test_exact_roof_surface_has_zero_topfill_without_invalid_aabb(self):
        container = ContainerSpec("C", BoxDim(2.4, 1.2, 1.2), 1000)
        sku = CargoSKU("S", "s", BoxDim(.4, .4, .4), 1, QuantityPlan(10))
        placement = Placement(
            "p", "i", "S", Point3D(0, 0, .8),
            Orientation3D(.4, .4, .40000000000000013), 1,
            PlacementContext.MAIN_WALL,
        )
        candidate = WallCandidate.from_placements("w", "S", [placement])
        result = FutureTopFillEstimator(container, {"S": sku}).estimate(candidate, {"S": 9})
        self.assertEqual(result["usable_top_height"], 0.0)
        self.assertEqual(result["packable_volume_estimate"], 0.0)


if __name__ == "__main__":
    unittest.main()
