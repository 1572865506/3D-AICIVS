"""
Comprehensive Unit Tests for Solver V2 WorldState & Geometry Kernel (Agent 02).
Test Coverage:
1. Face contact is not penetration (面接触不算穿插)
2. Edge and point contact are not penetration (边接触与点接触不算穿插)
3. Partial penetration is rejected (部分穿插硬拦截)
4. Full overlap / containment is rejected (完全重叠/包含硬拦截)
5. Out of bounds is rejected (越界硬拦截)
6. Atomic rollback completely restores state (rollback 后状态 100% 精确恢复)
7. Spatial index query consistency with independent OverlapDetector
"""
import unittest
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.domain.models import (
    BoxDim,
    Point3D,
    Orientation3D,
    ContainerSpec,
    CargoSKU,
    QuantityPlan,
    Placement,
    PlacementContext,
)
from backend.solver_v2.geometry.aabb import (
    AABB,
    ContactType,
    DEFAULT_GEOM_EPSILON,
)
from backend.solver_v2.geometry.spatial_index import SpatialIndex
from backend.solver_v2.geometry.overlap import OverlapDetector, OverlapReport
from backend.solver_v2.world.state import WorldState, GeometricIntegrityError, StateDelta


class TestGeometryKernelAndAABB(unittest.TestCase):
    def test_face_contact_not_penetration(self):
        """面接触：在 X、Y、Z 方向上紧密贴合（overlap <= eps），判定不是穿插，且正确识别为 FACE 接触"""
        # Box 1: [0.0, 1.0] x [0.0, 1.0] x [0.0, 1.0]
        b1 = AABB(0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
        # Box 2: [1.0, 2.0] x [0.0, 1.0] x [0.0, 1.0] (touches on +X face)
        b2 = AABB(1.0, 0.0, 0.0, 2.0, 1.0, 1.0)
        # Box 3: [0.0, 1.0] x [1.0, 2.0] x [0.0, 1.0] (touches on +Y face)
        b3 = AABB(0.0, 1.0, 0.0, 1.0, 2.0, 1.0)
        # Box 4: [0.0, 1.0] x [0.0, 1.0] x [1.0, 2.0] (touches on +Z face)
        b4 = AABB(0.0, 0.0, 1.0, 1.0, 1.0, 2.0)

        # 1. Intersection test must be False
        self.assertFalse(b1.intersects(b2))
        self.assertFalse(b1.intersects(b3))
        self.assertFalse(b1.intersects(b4))

        # 2. Penetration volume must be 0.0
        self.assertAlmostEqual(b1.penetration_volume(b2), 0.0)
        self.assertAlmostEqual(b1.penetration_volume(b3), 0.0)
        self.assertAlmostEqual(b1.penetration_volume(b4), 0.0)

        # 3. Contact classification must be FACE with contact area 1.0
        ctype_x, area_x = b1.classify_contact(b2)
        self.assertEqual(ctype_x, ContactType.FACE)
        self.assertAlmostEqual(area_x, 1.0)

        ctype_y, area_y = b1.classify_contact(b3)
        self.assertEqual(ctype_y, ContactType.FACE)
        self.assertAlmostEqual(area_y, 1.0)

        ctype_z, area_z = b1.classify_contact(b4)
        self.assertEqual(ctype_z, ContactType.FACE)
        self.assertAlmostEqual(area_z, 1.0)

    def test_edge_and_point_contact_not_penetration(self):
        """边接触与点接触：对角相邻或棱边接触，判定不是穿插"""
        b1 = AABB(0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
        # Edge contact along Z axis: [1.0, 2.0] x [1.0, 2.0] x [0.0, 1.0]
        b_edge = AABB(1.0, 1.0, 0.0, 2.0, 2.0, 1.0)
        # Point contact at (1.0, 1.0, 1.0): [1.0, 2.0] x [1.0, 2.0] x [1.0, 2.0]
        b_point = AABB(1.0, 1.0, 1.0, 2.0, 2.0, 2.0)

        # 1. No intersection
        self.assertFalse(b1.intersects(b_edge))
        self.assertFalse(b1.intersects(b_point))
        self.assertAlmostEqual(b1.penetration_volume(b_edge), 0.0)
        self.assertAlmostEqual(b1.penetration_volume(b_point), 0.0)

        # 2. Contact classification
        ctype_e, span_e = b1.classify_contact(b_edge)
        self.assertEqual(ctype_e, ContactType.EDGE)
        self.assertAlmostEqual(span_e, 1.0)

        ctype_p, _ = b1.classify_contact(b_point)
        self.assertEqual(ctype_p, ContactType.POINT)

    def test_partial_penetration(self):
        """部分穿插：即使穿插 1mm 也必须被判定为 PENETRATION 且 intersects 为 True"""
        b1 = AABB(0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
        # 1mm penetration in X: [0.999, 1.999] x [0.0, 1.0] x [0.0, 1.0]
        b_partial = AABB(0.999, 0.0, 0.0, 1.999, 1.0, 1.0)

        self.assertTrue(b1.intersects(b_partial))
        pen_vol = b1.penetration_volume(b_partial)
        self.assertAlmostEqual(pen_vol, 0.001 * 1.0 * 1.0, places=7)

        ctype, vol = b1.classify_contact(b_partial)
        self.assertEqual(ctype, ContactType.PENETRATION)
        self.assertAlmostEqual(vol, pen_vol)

    def test_full_overlap_and_containment(self):
        """完全重叠与包含"""
        b1 = AABB(0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
        # Identical
        b_same = AABB(0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
        self.assertTrue(b1.intersects(b_same))
        self.assertAlmostEqual(b1.penetration_volume(b_same), 1.0)

        # Contained
        b_inside = AABB(0.2, 0.2, 0.2, 0.8, 0.8, 0.8)
        self.assertTrue(b1.intersects(b_inside))
        self.assertTrue(b1.contains_aabb(b_inside))
        self.assertAlmostEqual(b1.penetration_volume(b_inside), 0.6 * 0.6 * 0.6)

    def test_out_of_bounds(self):
        """越界判定"""
        Lx, Ly, Lz = 12.0, 2.4, 2.6
        # Valid inside
        self.assertTrue(AABB(0.0, 0.0, 0.0, 1.0, 1.0, 1.0).is_within_bounds(Lx, Ly, Lz))
        # Negative X
        self.assertFalse(AABB(-0.01, 0.0, 0.0, 1.0, 1.0, 1.0).is_within_bounds(Lx, Ly, Lz))
        # Exceed Lx
        self.assertFalse(AABB(11.5, 0.0, 0.0, 12.1, 1.0, 1.0).is_within_bounds(Lx, Ly, Lz))
        # Exceed Ly
        self.assertFalse(AABB(0.0, 2.0, 0.0, 1.0, 2.5, 1.0).is_within_bounds(Lx, Ly, Lz))
        # Exceed Lz
        self.assertFalse(AABB(0.0, 0.0, 2.0, 1.0, 1.0, 2.7).is_within_bounds(Lx, Ly, Lz))


class TestWorldStateLifecycle(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec(
            code="40HQ",
            inner_dim=BoxDim(x=12.032, y=2.352, z=2.698),
            max_payload_kg=26500.0,
        )
        self.sku_a = CargoSKU(
            sku_id="SKU-A",
            name="Box A",
            box=BoxDim(x=1.0, y=0.5, z=0.5),
            weight_kg=100.0,
            quantity=QuantityPlan(required=10),
        )
        self.sku_b = CargoSKU(
            sku_id="SKU-B",
            name="Box B",
            box=BoxDim(x=0.5, y=0.5, z=0.5),
            weight_kg=50.0,
            quantity=QuantityPlan(required=10),
        )
        self.world = WorldState(
            container=self.container,
            cargo_catalog=[self.sku_a, self.sku_b],
            spatial_cell_size=0.5,
        )

    def test_candidate_face_contact_commit_allowed(self):
        """测试已提交货物与新候选货物面接触（无穿插）时允许正常提交"""
        p1 = Placement(
            placement_id="p1",
            instance_id="inst_1",
            sku_id="SKU-A",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=0.5, dz=0.5),
            weight_kg=100.0,
            context=PlacementContext.FOUNDATION,
        )
        can_c1, reason1 = self.world.can_commit(p1)
        self.assertTrue(can_c1, reason1)
        self.world.commit(p1)

        # p2 touches p1 on +X face: x in [1.0, 2.0]
        p2 = Placement(
            placement_id="p2",
            instance_id="inst_2",
            sku_id="SKU-A",
            position=Point3D(1.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=0.5, dz=0.5),
            weight_kg=100.0,
            context=PlacementContext.FOUNDATION,
        )
        can_c2, reason2 = self.world.can_commit(p2)
        self.assertTrue(can_c2, f"Face-touching candidate should be allowed: {reason2}")
        self.world.commit(p2)

        # p3 stacked on top of p1 (+Z face): z in [0.5, 1.0]
        p3 = Placement(
            placement_id="p3",
            instance_id="inst_3",
            sku_id="SKU-B",
            position=Point3D(0.0, 0.0, 0.5),
            orientation=Orientation3D(dx=0.5, dy=0.5, dz=0.5),
            weight_kg=50.0,
            context=PlacementContext.MAIN_WALL,
        )
        can_c3, reason3 = self.world.can_commit(p3)
        self.assertTrue(can_c3, f"Stacked face-touching candidate should be allowed: {reason3}")
        self.world.commit(p3)

        self.assertEqual(self.world.placement_count, 3)
        report = self.world.verify_integrity()
        self.assertTrue(report.is_valid)
        self.assertEqual(report.overlap_pair_count, 0)
        self.assertAlmostEqual(report.penetration_volume, 0.0)

    def test_candidate_collision_strictly_rejected(self):
        """测试候选与已提交货物存在部分或完全穿插时，严禁提交（零容忍）"""
        p1 = Placement(
            placement_id="p1",
            instance_id="inst_1",
            sku_id="SKU-A",
            position=Point3D(1.0, 1.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.0, dz=1.0),
            weight_kg=100.0,
            context=PlacementContext.FOUNDATION,
        )
        self.world.commit(p1)

        # 1. Partial penetration along X (x=1.9, overlaps 0.1m)
        p_collide_partial = Placement(
            placement_id="p_bad_1",
            instance_id="inst_bad_1",
            sku_id="SKU-B",
            position=Point3D(1.9, 1.0, 0.0),
            orientation=Orientation3D(dx=0.5, dy=0.5, dz=0.5),
            weight_kg=50.0,
            context=PlacementContext.MAIN_WALL,
        )
        can_c, reason = self.world.can_commit(p_collide_partial)
        self.assertFalse(can_c)
        self.assertIn("penetrates committed items", reason)

        with self.assertRaises(GeometricIntegrityError):
            self.world.commit(p_collide_partial)

        # 2. Complete duplicate overlap
        p_collide_full = Placement(
            placement_id="p_bad_2",
            instance_id="inst_bad_2",
            sku_id="SKU-A",
            position=Point3D(1.0, 1.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.0, dz=1.0),
            weight_kg=100.0,
            context=PlacementContext.MAIN_WALL,
        )
        can_c2, reason2 = self.world.can_commit(p_collide_full)
        self.assertFalse(can_c2)
        with self.assertRaises(GeometricIntegrityError):
            self.world.commit(p_collide_full)

        # WorldState remains clean with only 1 valid placement
        self.assertEqual(self.world.placement_count, 1)
        self.assertTrue(self.world.verify_integrity().is_valid)

    def test_out_of_bounds_candidate_strictly_rejected(self):
        """测试越界候选硬拦截"""
        # Negative coordinate
        p_neg = Placement(
            placement_id="p_neg",
            instance_id="inst_neg",
            sku_id="SKU-A",
            position=Point3D(-0.1, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=0.5, dz=0.5),
            weight_kg=100.0,
            context=PlacementContext.FOUNDATION,
        )
        can_neg, reason_neg = self.world.can_commit(p_neg)
        self.assertFalse(can_neg)
        self.assertIn("Bounds violation", reason_neg)
        with self.assertRaises(GeometricIntegrityError):
            self.world.commit(p_neg)

        # Exceeding container roof
        p_roof = Placement(
            placement_id="p_roof",
            instance_id="inst_roof",
            sku_id="SKU-A",
            position=Point3D(0.0, 0.0, 2.5),
            orientation=Orientation3D(dx=1.0, dy=0.5, dz=0.5),  # 2.5 + 0.5 = 3.0 > 2.698
            weight_kg=100.0,
            context=PlacementContext.TOP_FILL,
        )
        can_roof, reason_roof = self.world.can_commit(p_roof)
        self.assertFalse(can_roof)
        self.assertIn("Bounds violation", reason_roof)

    def test_atomic_rollback_exact_state_restoration(self):
        """测试 rollback() 后 WorldState 所有状态（货物列表、空间索引、剩余数量、重量、重心）完全精确恢复"""
        initial_qty_a = self.world.get_remaining_quantity("SKU-A")
        initial_qty_b = self.world.get_remaining_quantity("SKU-B")
        self.assertEqual(initial_qty_a, 10)
        self.assertEqual(initial_qty_b, 10)
        self.assertEqual(self.world.total_weight_kg, 0.0)
        self.assertEqual(self.world.placement_count, 0)

        # Commit 1
        p1 = Placement(
            placement_id="p1",
            instance_id="i1",
            sku_id="SKU-A",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=0.5, dz=0.5),
            weight_kg=100.0,
            context=PlacementContext.FOUNDATION,
        )
        delta1 = self.world.commit(p1)
        self.assertEqual(self.world.placement_count, 1)
        self.assertEqual(self.world.get_remaining_quantity("SKU-A"), 9)
        self.assertEqual(self.world.total_weight_kg, 100.0)
        self.assertAlmostEqual(self.world.center_of_mass.x, 0.5)

        # Commit 2
        p2 = Placement(
            placement_id="p2",
            instance_id="i2",
            sku_id="SKU-B",
            position=Point3D(1.0, 0.0, 0.0),
            orientation=Orientation3D(dx=0.5, dy=0.5, dz=0.5),
            weight_kg=50.0,
            context=PlacementContext.FOUNDATION,
        )
        delta2 = self.world.commit(p2)
        self.assertEqual(self.world.placement_count, 2)
        self.assertEqual(self.world.get_remaining_quantity("SKU-B"), 9)
        self.assertEqual(self.world.total_weight_kg, 150.0)
        # COM = (100 * 0.5 + 50 * 1.25) / 150 = 112.5 / 150 = 0.75
        self.assertAlmostEqual(self.world.center_of_mass.x, 0.75)

        # Verify spatial index contains both
        self.assertEqual(len(self.world.spatial_index), 2)
        self.assertIsNotNone(self.world.spatial_index.get_item("p1"))
        self.assertIsNotNone(self.world.spatial_index.get_item("p2"))

        # Rollback Commit 2
        rolled_p2 = self.world.rollback(delta2)
        self.assertEqual(rolled_p2.placement_id, "p2")
        self.assertEqual(self.world.placement_count, 1)
        self.assertIsNone(self.world.get_placement("p2"))
        self.assertIsNone(self.world.spatial_index.get_item("p2"))
        self.assertEqual(self.world.get_remaining_quantity("SKU-B"), 10)
        self.assertEqual(self.world.total_weight_kg, 100.0)
        self.assertAlmostEqual(self.world.center_of_mass.x, 0.5)

        # Spatial index query at p2 spot should now be empty
        p2_aabb = AABB(1.0, 0.0, 0.0, 1.5, 0.5, 0.5)
        self.assertEqual(len(self.world.query_overlaps(p2_aabb)), 0)

        # Rollback Commit 1
        rolled_p1 = self.world.rollback(delta1)
        self.assertEqual(rolled_p1.placement_id, "p1")
        self.assertEqual(self.world.placement_count, 0)
        self.assertIsNone(self.world.get_placement("p1"))
        self.assertIsNone(self.world.spatial_index.get_item("p1"))
        self.assertEqual(self.world.get_remaining_quantity("SKU-A"), 10)
        self.assertEqual(self.world.total_weight_kg, 0.0)
        self.assertEqual(len(self.world.spatial_index), 0)

        # Verify integrity on clean empty state
        self.assertTrue(self.world.verify_integrity().is_valid)

    def test_interleaved_commit_and_rollback_stress(self):
        """交替提交与回滚压力测试：验证状态不会发生漂移或残留"""
        for cycle in range(5):
            p = Placement(
                placement_id=f"p_cycle_{cycle}",
                instance_id=f"inst_{cycle}",
                sku_id="SKU-A",
                position=Point3D(0.0, 0.0, 0.0),
                orientation=Orientation3D(dx=1.0, dy=0.5, dz=0.5),
                weight_kg=100.0,
                context=PlacementContext.FOUNDATION,
            )
            d = self.world.commit(p)
            self.assertEqual(self.world.placement_count, 1)
            self.assertEqual(self.world.get_remaining_quantity("SKU-A"), 9)

            self.world.rollback(d)
            self.assertEqual(self.world.placement_count, 0)
            self.assertEqual(self.world.get_remaining_quantity("SKU-A"), 10)
            self.assertEqual(self.world.total_weight_kg, 0.0)
            self.assertEqual(len(self.world.spatial_index), 0)


class TestSpatialIndexAndIndependentOverlapDetector(unittest.TestCase):
    def test_spatial_index_accuracy_and_consistency(self):
        """验证空间索引的高效查询与独立全局验证器完全一致"""
        container = ContainerSpec(
            code="40HQ",
            inner_dim=BoxDim(x=12.0, y=2.4, z=2.6),
            max_payload_kg=26000.0,
        )
        world = WorldState(container=container, spatial_cell_size=0.5)

        # Place 4 non-overlapping cartons in a 2x2 grid
        p00 = Placement("p00", "i00", "S", Point3D(0.0, 0.0, 0.0), Orientation3D(1.0, 1.0, 1.0), 10.0, PlacementContext.FOUNDATION)
        p10 = Placement("p10", "i10", "S", Point3D(1.0, 0.0, 0.0), Orientation3D(1.0, 1.0, 1.0), 10.0, PlacementContext.FOUNDATION)
        p01 = Placement("p01", "i01", "S", Point3D(0.0, 1.0, 0.0), Orientation3D(1.0, 1.0, 1.0), 10.0, PlacementContext.FOUNDATION)
        p11 = Placement("p11", "i11", "S", Point3D(1.0, 1.0, 0.0), Orientation3D(1.0, 1.0, 1.0), 10.0, PlacementContext.FOUNDATION)

        world.commit(p00)
        world.commit(p10)
        world.commit(p01)
        world.commit(p11)

        # Independent sweep check
        report = OverlapDetector.run_independent_sweep(container, world.placements)
        self.assertTrue(report.is_valid)
        self.assertEqual(report.overlap_pair_count, 0)
        self.assertEqual(report.out_of_bounds_count, 0)
        self.assertAlmostEqual(report.penetration_volume, 0.0)

        # Query overlap at center (0.5, 0.5, 0.0) with small box [0.5, 1.5] x [0.5, 1.5] x [0.0, 0.5]
        # This small box overlaps all 4 committed placements
        center_probe = AABB(0.5, 0.5, 0.0, 1.5, 1.5, 0.5)
        overlaps = world.query_overlaps(center_probe)
        overlap_ids = {p.placement_id for p in overlaps}
        self.assertEqual(overlap_ids, {"p00", "p10", "p01", "p11"})

        # Query touching with side box at (2.0, 0.0, 0.0) [2.0, 3.0] x [0.0, 1.0] x [0.0, 1.0]
        # Touches p10 on +X face, and touches p11 on edge (x=2.0, y=1.0)
        touch_probe = AABB(2.0, 0.0, 0.0, 3.0, 1.0, 1.0)
        self.assertEqual(len(world.query_overlaps(touch_probe)), 0)
        touch_results = world.query_touching(touch_probe)
        touch_dict = {p.placement_id: ctype for p, ctype in touch_results}
        self.assertIn("p10", touch_dict)
        self.assertEqual(touch_dict["p10"], ContactType.FACE)
        self.assertIn("p11", touch_dict)
        self.assertEqual(touch_dict["p11"], ContactType.EDGE)


if __name__ == "__main__":
    unittest.main()
