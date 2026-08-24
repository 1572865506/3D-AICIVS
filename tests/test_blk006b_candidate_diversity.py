"""BLK-006B diverse wall pool, signatures, and bounded family enumeration."""
import unittest

from backend.solver_v2.candidates.generator import CandidatePlacement
from backend.solver_v2.domain.models import (
    BoxDim, CargoSKU, ContainerSpec, Orientation3D, PlacementContext, Point3D,
    QuantityPlan, StackingPolicy,
)
from backend.solver_v2.geometry.aabb import AABB
from backend.solver_v2.patterns.models import PatternType
from backend.solver_v2.quantity.manager import QuantityManager
from backend.solver_v2.search.aggregate import AggregateCandidate
from backend.solver_v2.search.diverse_wall_candidates import (
    CandidateSignature, DiverseWallCandidateGenerator,
)
from backend.solver_v2.world.state import WorldState


class TestBLK006BCandidateDiversity(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec("C", BoxDim(6, 2.4, 3), 10000)
        self.a = CargoSKU("A", "a", BoxDim(.5, .4, .3), 2, QuantityPlan(100), stacking_policy=StackingPolicy(max_bearing_kg=100))
        self.b = CargoSKU("B", "b", BoxDim(.4, .3, .25), 2, QuantityPlan(100), stacking_policy=StackingPolicy(max_bearing_kg=100))
        self.cargo = [self.a, self.b]
        self.world = WorldState(self.container, self.cargo)
        self.qty = QuantityManager(self.cargo)

    def _aggregate(self, cid, sku, nx, ny, nz, orientation=None, x=0.0):
        ori = orientation or Orientation3D(sku.box.x, sku.box.y, sku.box.z, "UPRIGHT_NORMAL", True)
        items = []
        for ix in range(nx):
            for iy in range(ny):
                for iz in range(nz):
                    items.append(CandidatePlacement(
                        sku.sku_id, Point3D(x + ix * ori.dx, iy * ori.dy, iz * ori.dz), ori,
                        PlacementContext.MAIN_WALL, sku.weight_kg,
                    ))
        return AggregateCandidate(
            cid, sku.sku_id, PlacementContext.MAIN_WALL, Point3D(x, 0, 0),
            AABB(x, 0, 0, x + nx * ori.dx, ny * ori.dy, nz * ori.dz),
            items, len(items) * ori.volume, len(items) * sku.weight_kg, len(items), PatternType.BLOCK,
        )

    def test_signature_deduplicates_geometry_equivalent_candidates(self):
        first = self._aggregate("first", self.a, 4, 3, 2)
        duplicate = self._aggregate("duplicate", self.a, 4, 3, 2)
        pool = DiverseWallCandidateGenerator().build_pool([first, duplicate], self.world, self.qty, 8)
        self.assertEqual(len(pool.proposals), 1)
        self.assertEqual(pool.duplicates_removed, 1)

    def test_bounded_pool_retains_width_height_orientation_and_sku_variants(self):
        rotated = Orientation3D(self.a.box.y, self.a.box.x, self.a.box.z, "UPRIGHT_ROTATED", True)
        raw = [
            self._aggregate("a_max", self.a, 6, 5, 3),
            self._aggregate("a_w5", self.a, 5, 5, 3),
            self._aggregate("a_w4", self.a, 4, 5, 3),
            self._aggregate("a_h2", self.a, 6, 5, 2),
            self._aggregate("a_y4", self.a, 6, 4, 3),
            self._aggregate("a_rot", self.a, 5, 4, 3, rotated),
            self._aggregate("b_max", self.b, 6, 5, 3, x=3.0),
            self._aggregate("b_h2", self.b, 6, 5, 2, x=3.0),
        ]
        pool = DiverseWallCandidateGenerator().build_pool(raw, self.world, self.qty, 12)
        signatures = {item.candidate_signature for item in pool.proposals}
        self.assertGreaterEqual(len(pool.proposals), 8)
        self.assertEqual(len(signatures), len(pool.proposals))
        families = {item.candidate_family for item in pool.proposals}
        self.assertIn("ALTERNATE_WIDTH_WALL", families)
        self.assertIn("ALTERNATE_HEIGHT_WALL", families)
        self.assertIn("ALTERNATE_ORIENTATION_WALL", families)
        self.assertIn("MIXED_SKU_WALL", families)


if __name__ == "__main__":
    unittest.main()
