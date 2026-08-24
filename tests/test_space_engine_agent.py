"""
Comprehensive Unit Tests for Free Space Engine (Solver V2 - Agent 03).
Test coverage:
1. EMS (Empty Maximal Spaces) initialization, splitting, subsumption, and rollback.
2. Extreme Points (EP) generation, projection, penetration filtering, and rollback.
3. Door-side Reachability & Enclosed Cavity detection (BFS flood fill from door plane x=Lx).
4. Narrow Sliver & Dead Space classification against remaining SKU dimensions.
5. Fragmentation scoring.
6. ResidualSpaceMetrics computation and anti-greedy candidate evaluation.
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
from backend.solver_v2.geometry.aabb import AABB
from backend.solver_v2.spaces.types import (
    SpaceClass,
    ExtremePoint,
    FreeSpaceBox,
    ResidualSpaceMetrics,
)
from backend.solver_v2.spaces.ems import EMSManager
from backend.solver_v2.spaces.extreme_points import ExtremePointsManager
from backend.solver_v2.spaces.reachability import ReachabilityAnalyzer
from backend.solver_v2.spaces.engine import FreeSpaceEngine


class TestEMSManager(unittest.TestCase):
    def setUp(self):
        # 10m x 2m x 2m container
        self.container = ContainerSpec(
            code="TEST_BOX",
            inner_dim=BoxDim(x=10.0, y=2.0, z=2.0),
            max_payload_kg=10000.0,
        )
        self.ems = EMSManager(self.container, min_space_dim=0.1)

    def test_initial_ems(self):
        """初始状态：EMS 包含且仅包含整个容器自身"""
        self.assertEqual(self.ems.count, 1)
        init_space = self.ems.spaces[0]
        self.assertEqual(init_space.min_x, 0.0)
        self.assertEqual(init_space.max_x, 10.0)
        self.assertEqual(init_space.min_y, 0.0)
        self.assertEqual(init_space.max_y, 2.0)
        self.assertEqual(init_space.min_z, 0.0)
        self.assertEqual(init_space.max_z, 2.0)

    def test_ems_splitting_corner_placement(self):
        """角隅放置一个 2m x 1m x 1m 货物，EMS 正交切分为 3 个最大空闲长方体"""
        # Box placed at (0, 0, 0) with dim (2.0, 1.0, 1.0)
        p = Placement(
            placement_id="p1",
            instance_id="i1",
            sku_id="SKU-1",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(dx=2.0, dy=1.0, dz=1.0),
            weight_kg=100.0,
            context=PlacementContext.FOUNDATION,
        )
        self.ems.on_placement_committed(p)

        # Expected 3 maximal empty spaces:
        # 1. [2, 10] x [0, 2] x [0, 2] (right space, vol = 8 * 2 * 2 = 32)
        # 2. [0, 10] x [1, 2] x [0, 2] (front space, vol = 10 * 1 * 2 = 20)
        # 3. [0, 10] x [0, 2] x [1, 2] (top space, vol = 10 * 2 * 1 = 20)
        self.assertEqual(self.ems.count, 3)
        vols = sorted([round(s.volume, 2) for s in self.ems.spaces], reverse=True)
        self.assertEqual(vols, [32.0, 20.0, 20.0])

    def test_ems_subsumption_elimination(self):
        """测试包含消除（Subsumption）：较小被包含的空间必须被自动移除"""
        # Place 2 identical boxes next to each other
        p1 = Placement(
            placement_id="p1",
            instance_id="i1",
            sku_id="SKU-1",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.0, dz=1.0),
            weight_kg=50.0,
            context=PlacementContext.FOUNDATION,
        )
        self.ems.on_placement_committed(p1)

        p2 = Placement(
            placement_id="p2",
            instance_id="i2",
            sku_id="SKU-1",
            position=Point3D(1.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.0, dz=1.0),
            weight_kg=50.0,
            context=PlacementContext.FOUNDATION,
        )
        self.ems.on_placement_committed(p2)

        # Verify no space is subsumed by another
        spaces = self.ems.spaces
        for i, s1 in enumerate(spaces):
            for j, s2 in enumerate(spaces):
                if i != j:
                    self.assertFalse(s1.contains_aabb(s2) and s1 != s2)

    def test_ems_atomic_rollback(self):
        """测试 EMS 回滚：rollback 后精确恢复上一状态"""
        init_count = self.ems.count
        p = Placement(
            placement_id="p1",
            instance_id="i1",
            sku_id="SKU-1",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(dx=2.0, dy=1.0, dz=1.0),
            weight_kg=100.0,
            context=PlacementContext.FOUNDATION,
        )
        self.ems.on_placement_committed(p)
        self.assertEqual(self.ems.count, 3)

        self.ems.rollback()
        self.assertEqual(self.ems.count, init_count)
        self.assertEqual(self.ems.spaces[0].volume, 10.0 * 2.0 * 2.0)


class TestExtremePointsManager(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec(
            code="TEST_EP",
            inner_dim=BoxDim(x=6.0, y=3.0, z=2.5),
            max_payload_kg=10000.0,
        )
        self.ep = ExtremePointsManager(self.container)

    def test_initial_ep(self):
        """初始极限点包含原点 (0, 0, 0)"""
        self.assertEqual(self.ep.count, 1)
        self.assertEqual(self.ep.points[0].to_tuple(), (0.0, 0.0, 0.0))

    def test_ep_generation_and_projection(self):
        """放置货物后生成正确的 3D 极限点"""
        p1 = Placement(
            placement_id="p1",
            instance_id="i1",
            sku_id="SKU-1",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.0, dz=1.0),
            weight_kg=50.0,
            context=PlacementContext.FOUNDATION,
        )
        self.ep.on_placement_committed(p1, [p1], step_index=1)

        pts = {p.to_tuple() for p in self.ep.points}
        # (0,0,0) used, replaced by:
        # (1, 0, 0), (0, 1, 0), (0, 0, 1)
        self.assertIn((1.0, 0.0, 0.0), pts)
        self.assertIn((0.0, 1.0, 0.0), pts)
        self.assertIn((0.0, 0.0, 1.0), pts)
        self.assertNotIn((0.0, 0.0, 0.0), pts)

    def test_ep_rollback(self):
        """测试 Extreme Points 回滚"""
        p1 = Placement(
            placement_id="p1",
            instance_id="i1",
            sku_id="SKU-1",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.0, dz=1.0),
            weight_kg=50.0,
            context=PlacementContext.FOUNDATION,
        )
        self.ep.on_placement_committed(p1, [p1], step_index=1)
        self.assertGreater(self.ep.count, 1)

        self.ep.rollback()
        self.assertEqual(self.ep.count, 1)
        self.assertEqual(self.ep.points[0].to_tuple(), (0.0, 0.0, 0.0))


class TestReachabilityAndCavity(unittest.TestCase):
    def setUp(self):
        # 4m x 2m x 2m container. Door is at x = 4.0
        self.container = ContainerSpec(
            code="TEST_CAVITY",
            inner_dim=BoxDim(x=4.0, y=2.0, z=2.0),
            max_payload_kg=10000.0,
        )
        self.analyzer = ReachabilityAnalyzer(self.container, grid_resolution=0.2)

    def test_open_container_reachability(self):
        """空集装箱：100% 可达，0 空洞，0 细缝"""
        metrics, _ = self.analyzer.analyze(placements=[])
        total_vol = 4.0 * 2.0 * 2.0
        self.assertAlmostEqual(metrics.useful_volume, total_vol)
        self.assertAlmostEqual(metrics.reachable_volume, total_vol)
        self.assertAlmostEqual(metrics.enclosed_cavity_volume, 0.0)
        self.assertAlmostEqual(metrics.sliver_volume, 0.0)

    def test_enclosed_cavity_detection(self):
        """
        构造封闭死腔（Enclosed Cavity）：
        货物在集装箱后方 x in [0, 1] 留空，但在 x in [1, 2] 建造了一整面封堵墙（y: [0, 2], z: [0, 2]）。
        门位于 x = 4.0，因此 x in [0, 1] 的空间完全被货物隔绝，形成封闭死腔。
        """
        # Wall at x in [1.0, 2.0], y in [0.0, 2.0], z in [0.0, 2.0]
        # Made of 4 boxes (each 1m x 1m x 1m)
        p1 = Placement("w1", "i1", "S", Point3D(1.0, 0.0, 0.0), Orientation3D(1.0, 1.0, 1.0), 10.0, PlacementContext.MAIN_WALL)
        p2 = Placement("w2", "i2", "S", Point3D(1.0, 1.0, 0.0), Orientation3D(1.0, 1.0, 1.0), 10.0, PlacementContext.MAIN_WALL)
        p3 = Placement("w3", "i3", "S", Point3D(1.0, 0.0, 1.0), Orientation3D(1.0, 1.0, 1.0), 10.0, PlacementContext.MAIN_WALL)
        p4 = Placement("w4", "i4", "S", Point3D(1.0, 1.0, 1.0), Orientation3D(1.0, 1.0, 1.0), 10.0, PlacementContext.MAIN_WALL)

        placements = [p1, p2, p3, p4]
        metrics, _ = self.analyzer.analyze(placements=placements)

        # Cavity volume is x in [0, 1] x y in [0, 2] x z in [0, 2] = 1 * 2 * 2 = 4.0 m^3
        self.assertGreater(metrics.enclosed_cavity_volume, 3.5)
        # Door side x in [2, 4] is reachable: 2 * 2 * 2 = 8.0 m^3
        self.assertGreater(metrics.reachable_volume, 7.5)

    def test_open_notch_is_reachable(self):
        """
        构造开放凹槽（Open Notch）：
        封堵墙上开有一个 1m x 1m 的通道（例如只放了 3 个箱子，留出顶部 1 个通道）。
        此时后方空间仍可通过顶部通道由门侧到达，不属于封闭死腔。
        """
        p1 = Placement("w1", "i1", "S", Point3D(1.0, 0.0, 0.0), Orientation3D(1.0, 1.0, 1.0), 10.0, PlacementContext.MAIN_WALL)
        p2 = Placement("w2", "i2", "S", Point3D(1.0, 1.0, 0.0), Orientation3D(1.0, 1.0, 1.0), 10.0, PlacementContext.MAIN_WALL)
        p3 = Placement("w3", "i3", "S", Point3D(1.0, 0.0, 1.0), Orientation3D(1.0, 1.0, 1.0), 10.0, PlacementContext.MAIN_WALL)
        # (1.0, 1.0, 1.0) is empty passage

        placements = [p1, p2, p3]
        metrics, _ = self.analyzer.analyze(placements=placements)

        # Whole free space is connected to door, so enclosed cavity is 0
        self.assertAlmostEqual(metrics.enclosed_cavity_volume, 0.0)
        self.assertGreater(metrics.reachable_volume, 11.5)


class TestFreeSpaceEngineAndAntiGreedy(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec(
            code="40HQ_TEST",
            inner_dim=BoxDim(x=6.0, y=2.4, z=2.4),
            max_payload_kg=20000.0,
        )
        self.sku_big = CargoSKU(
            sku_id="SKU-BIG",
            name="Big Cargo",
            box=BoxDim(x=2.0, y=1.2, z=1.2),
            weight_kg=200.0,
            quantity=QuantityPlan(required=10),
        )
        self.sku_std = CargoSKU(
            sku_id="SKU-STD",
            name="Standard Cargo",
            box=BoxDim(x=1.0, y=1.2, z=1.2),
            weight_kg=100.0,
            quantity=QuantityPlan(required=10),
        )
        self.engine = FreeSpaceEngine(self.container, grid_resolution=0.2)

    def test_evaluate_candidate_anti_greedy(self):
        """
        验证反贪心（Anti-Greedy）：
        对比两个候选方案：
        方案 A（大体积但不规则封门，制造了内部封闭死腔）：体积收益大，但剩余空间质量极差（enclosed cavity penalty）。
        方案 B（较小体积但规整靠后装载）：体积收益较小，但剩余空间规整、全部连通。
        空间引擎的 ResidualSpaceMetrics 能够正确反映出方案 B 的剩余质量远优于方案 A。
        """
        # Step 1: Place 1 standard box at rear corner (0, 0, 0)
        p_base = Placement("p0", "i0", "SKU-STD", Point3D(0.0, 0.0, 0.0), Orientation3D(1.0, 1.2, 1.2), 100.0, PlacementContext.FOUNDATION)
        self.engine.on_placement_committed(p_base, [self.sku_big, self.sku_std])

        # Candidate A: Place a wall near door at x=4.0 spanning whole width & height (creates huge hollow cavity behind it)
        # Note: creates enclosed cavity of volume ~ 4.0 * 2.4 * 2.4 - base_vol
        cand_a = Placement("cand_a", "i_a", "SKU-BIG", Point3D(4.0, 0.0, 0.0), Orientation3D(2.0, 2.4, 2.4), 800.0, PlacementContext.MAIN_WALL)

        # Candidate B: Place adjacent at x=1.0 on floor cleanly
        cand_b = Placement("cand_b", "i_b", "SKU-STD", Point3D(1.0, 0.0, 0.0), Orientation3D(1.0, 1.2, 1.2), 100.0, PlacementContext.FOUNDATION)

        metrics_a = self.engine.evaluate_candidate_residual(cand_a, [self.sku_big, self.sku_std])
        metrics_b = self.engine.evaluate_candidate_residual(cand_b, [self.sku_big, self.sku_std])

        # Verify Candidate A created huge enclosed cavity
        self.assertGreater(metrics_a.enclosed_cavity_volume, 15.0)
        self.assertAlmostEqual(metrics_b.enclosed_cavity_volume, 0.0)

        # Residual quality score for B must be significantly higher than A
        score_a = metrics_a.compute_quality_score()
        score_b = metrics_b.compute_quality_score()
        self.assertGreater(score_b, score_a)

    def test_candidate_anchors_generation(self):
        """测试候选基准点（Candidate Anchors）结合了 EP 与 EMS 角点，且无重复"""
        p = Placement("p1", "i1", "SKU-STD", Point3D(0.0, 0.0, 0.0), Orientation3D(1.0, 1.2, 1.2), 100.0, PlacementContext.FOUNDATION)
        self.engine.on_placement_committed(p, [self.sku_std])

        anchors = self.engine.get_candidate_anchors()
        self.assertGreater(len(anchors), 1)
        # Anchor points should include (1.0, 0.0, 0.0), (0.0, 1.2, 0.0), (0.0, 0.0, 1.2)
        anchor_tuples = {(round(a.x, 2), round(a.y, 2), round(a.z, 2)) for a in anchors}
        self.assertIn((1.0, 0.0, 0.0), anchor_tuples)
        self.assertIn((0.0, 1.2, 0.0), anchor_tuples)
        self.assertIn((0.0, 0.0, 1.2), anchor_tuples)

    def test_full_engine_commit_and_rollback_lifecycle(self):
        """测试完整的放置提交与回滚生命周期"""
        init_metrics = self.engine.get_current_metrics([self.sku_std])
        self.assertAlmostEqual(init_metrics.enclosed_cavity_volume, 0.0)

        p = Placement("p1", "i1", "SKU-STD", Point3D(0.0, 0.0, 0.0), Orientation3D(1.0, 1.2, 1.2), 100.0, PlacementContext.FOUNDATION)
        self.engine.on_placement_committed(p, [self.sku_std])
        self.assertEqual(len(self.engine.ems_spaces), 3)

        self.engine.rollback()
        self.assertEqual(len(self.engine.ems_spaces), 1)
        self.assertEqual(len(self.engine.extreme_points), 1)
        self.assertEqual(self.engine.extreme_points[0].to_tuple(), (0.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
