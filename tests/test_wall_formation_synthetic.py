"""
Synthetic Bad Cases and Targeted Validation Suite for BLK-003:
Wall Formation, Row/Layer Coherence, Cavity Classification, and Anti-Bridge Gating.

Test Cases:
1. WALL-001 Same-size full wall
2. WALL-002 Mixed-size aligned wall
3. WALL-003 Valley filling
4. WALL-004 Enclosed cavity prevention
5. WALL-005 Bridge void prevention
6. WALL-006 Small filler usage
7. WALL-007 Height mismatch
8. WALL-008 Wall close repair
9. WALL-009 Thin display wall
10. WALL-010 Multiple consecutive walls
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
    OrientationPolicy,
    StackingPolicy,
    QuantityPlan,
    ContainerSpec,
    CargoSKU,
    Placement,
    PlacementContext,
    PackingRole,
    ZoneType,
)
from backend.solver_v2.world.state import WorldState
from backend.solver_v2.structure.wall_model import (
    WallStructureAnalyzer,
    WallState,
    LogicalWall,
    WallCompletionState,
    DimensionCompatibility,
)
from backend.solver_v2.structure.cavity_classifier import (
    AdvancedCavityClassifier,
    CavityType,
    ComprehensiveCavityReport,
)
from backend.solver_v2.structure.wall_repair import (
    WallCloseChecker,
    WallRepairPlanner,
)
from backend.solver_v2.solver.baseline_solver import BaselineGreedySolver


class TestWallFormationSynthetic(unittest.TestCase):
    def setUp(self):
        # Canonical test container: 6.0m x 2.4m x 2.4m
        self.container = ContainerSpec(
            code="WALL_TEST_CONT",
            inner_dim=BoxDim(x=6.0, y=2.4, z=2.4),
            max_payload_kg=20000.0,
            door_zone_length_m=1.0,
            rear_zone_length_m=1.0,
        )

        # Standard Brick SKU: 0.6 x 0.4 x 0.4
        self.sku_brick = CargoSKU(
            sku_id="SKU-BRICK",
            name="Standard Brick",
            box=BoxDim(x=0.6, y=0.4, z=0.4),
            weight_kg=20.0,
            quantity=QuantityPlan(required=72), # 1 full wall = 1 in x, 6 in y, 6 in z = 36 boxes
            packing_roles=(PackingRole.MAIN_WALL,),
        )

        # Small filler SKU: 0.3 x 0.4 x 0.4
        self.sku_filler = CargoSKU(
            sku_id="SKU-FILLER",
            name="Small Filler",
            box=BoxDim(x=0.3, y=0.4, z=0.4),
            weight_kg=10.0,
            quantity=QuantityPlan(required=20),
            packing_roles=(PackingRole.WALL_FILLER,),
        )

        # Large span SKU: 0.6 x 1.2 x 0.4
        self.sku_span = CargoSKU(
            sku_id="SKU-SPAN",
            name="Long Beam Span",
            box=BoxDim(x=0.6, y=1.2, z=0.4),
            weight_kg=40.0,
            quantity=QuantityPlan(required=10),
            packing_roles=(PackingRole.MAIN_WALL,),
        )

    def test_wall_001_same_size_full_wall(self):
        """WALL-001: Packing identical sized boxes creates a uniform wall with high flatness and rows/layers."""
        world = WorldState(container=self.container, cargo_catalog=[self.sku_brick])
        
        # Manually or greedily construct 1 full wall (6 across Y, 6 across Z)
        p_list = []
        for iy in range(6):
            for iz in range(6):
                p = Placement(
                    placement_id=f"P_{iy}_{iz}",
                    instance_id=f"I_{iy}_{iz}",
                    sku_id="SKU-BRICK",
                    position=Point3D(0.0, iy * 0.4, iz * 0.4),
                    orientation=Orientation3D(0.6, 0.4, 0.4, 0, 0, 0),
                    weight_kg=20.0,
                    context=PlacementContext.MAIN_WALL,
                )
                world.commit(p)

        walls = world.get_walls()
        self.assertEqual(len(walls), 1)
        wall = walls[0]
        self.assertGreaterEqual(wall.wall_flatness, 0.90)
        self.assertGreaterEqual(wall.wall_occupancy, 0.90)
        self.assertEqual(len(wall.rows), 6)
        self.assertEqual(len(wall.layers), 6)
        self.assertTrue(all(r.is_complete for r in wall.rows))
        self.assertTrue(all(l.is_complete for l in wall.layers))

    def test_wall_002_mixed_size_aligned_wall(self):
        """WALL-002: DimensionCompatibility accurately evaluates alignment compatibility between sizes."""
        # Same height/depth, different width
        d1 = BoxDim(0.6, 0.4, 0.4)
        d2 = BoxDim(0.6, 0.8, 0.4)
        comp = DimensionCompatibility.evaluate(d1, d2)
        self.assertEqual(comp.height_compat, 1.0)
        self.assertEqual(comp.depth_compat, 1.0)
        self.assertEqual(comp.width_compat, 0.5)
        self.assertGreaterEqual(comp.composite_score, 0.70)

    def test_wall_003_valley_filling(self):
        """WALL-003: Cavity Classifier detects open notches on the frontier."""
        world = WorldState(container=self.container, cargo_catalog=[self.sku_brick])
        
        # Place 2 columns on left and right, leaving center open (y from 0.8 to 1.6)
        world.commit(Placement("P1", "I1", "SKU-BRICK", Point3D(0.0, 0.0, 0.0), Orientation3D(0.6, 0.4, 0.8, 0, 0, 0), 20.0, PlacementContext.MAIN_WALL))
        world.commit(Placement("P2", "I2", "SKU-BRICK", Point3D(0.0, 2.0, 0.0), Orientation3D(0.6, 0.4, 0.8, 0, 0, 0), 20.0, PlacementContext.MAIN_WALL))

        report: ComprehensiveCavityReport = world.get_cavity_report()
        self.assertGreater(len(report.open_notches), 0)
        self.assertFalse(report.has_critical_enclosed_void)

    def test_wall_004_enclosed_cavity_prevention(self):
        """WALL-004: Enclosed hollow cavity created behind front face is detected and marked critical."""
        world = WorldState(container=self.container, cargo_catalog=[self.sku_brick])

        # Enclose a hollow box in 3D: surrounding on bottom, left, right, top, and front
        # Bottom
        world.commit(Placement("P_B", "I", "SKU-BRICK", Point3D(0.0, 0.0, 0.0), Orientation3D(1.2, 1.2, 0.4, 0, 0, 0), 20.0, PlacementContext.MAIN_WALL))
        # Left wall
        world.commit(Placement("P_L", "I", "SKU-BRICK", Point3D(0.0, 0.0, 0.4), Orientation3D(1.2, 0.4, 0.8, 0, 0, 0), 20.0, PlacementContext.MAIN_WALL))
        # Right wall
        world.commit(Placement("P_R", "I", "SKU-BRICK", Point3D(0.0, 0.8, 0.4), Orientation3D(1.2, 0.4, 0.8, 0, 0, 0), 20.0, PlacementContext.MAIN_WALL))
        # Front wall (sealing the x front)
        world.commit(Placement("P_F", "I", "SKU-BRICK", Point3D(0.8, 0.4, 0.4), Orientation3D(0.4, 0.4, 0.8, 0, 0, 0), 20.0, PlacementContext.MAIN_WALL))
        # Top cap
        world.commit(Placement("P_T", "I", "SKU-BRICK", Point3D(0.0, 0.0, 1.2), Orientation3D(1.2, 1.2, 0.4, 0, 0, 0), 20.0, PlacementContext.MAIN_WALL))

        report: ComprehensiveCavityReport = world.get_cavity_report()
        self.assertTrue(report.has_critical_enclosed_void)
        self.assertGreater(len(report.enclosed_cavities), 0)
        self.assertGreater(report.enclosed_volume_m3, 0.0)

    def test_wall_005_bridge_void_prevention(self):
        """WALL-005: Placing a wide spanning box over a large void is flagged as bridge void."""
        world = WorldState(container=self.container, cargo_catalog=[self.sku_brick, self.sku_span])

        # Two pillars with a 0.8m gap between them
        world.commit(Placement("P_P1", "I", "SKU-BRICK", Point3D(0.0, 0.0, 0.0), Orientation3D(0.6, 0.4, 0.8, 0, 0, 0), 20.0, PlacementContext.MAIN_WALL))
        world.commit(Placement("P_P2", "I", "SKU-BRICK", Point3D(0.0, 1.2, 0.0), Orientation3D(0.6, 0.4, 0.8, 0, 0, 0), 20.0, PlacementContext.MAIN_WALL))
        # Spanning bridge on top
        world.commit(Placement("P_SPAN", "I", "SKU-SPAN", Point3D(0.0, 0.2, 0.8), Orientation3D(0.6, 1.2, 0.4, 0, 0, 0), 40.0, PlacementContext.MAIN_WALL))

        report: ComprehensiveCavityReport = world.get_cavity_report()
        self.assertGreaterEqual(report.bridge_void_count, 1)
        self.assertGreaterEqual(report.max_bridge_span_m, 0.30)

    def test_wall_006_small_filler_usage(self):
        """WALL-006: WallRepairPlanner successfully generates filler placements to repair gaps."""
        world = WorldState(container=self.container, cargo_catalog=[self.sku_brick, self.sku_filler])
        
        # Incomplete wall with a 0.4m notch
        for iy in [0, 1, 2, 4, 5]:
            world.commit(Placement(f"P_F_{iy}", "I", "SKU-BRICK", Point3D(0.0, iy * 0.4, 0.0), Orientation3D(0.6, 0.4, 0.4, 0, 0, 0), 20.0, PlacementContext.MAIN_WALL))

        walls = world.get_walls()
        wall = walls[0]

        from backend.solver_v2.spaces.engine import FreeSpaceEngine
        from backend.solver_v2.orientation.manager import OrientationEngine
        from backend.solver_v2.zones.manager import AdaptiveZoneManager
        from backend.solver_v2.quantity.manager import QuantityManager

        space_engine = FreeSpaceEngine(container=self.container)
        ori_engine = OrientationEngine()
        zone_mgr = AdaptiveZoneManager(container=self.container)
        qty_mgr = QuantityManager(cargo_list=[self.sku_brick, self.sku_filler])

        repair_planner = WallRepairPlanner(container=self.container)
        repair_cands = repair_planner.plan_wall_repair(
            world_state=world,
            space_engine=space_engine,
            orientation_engine=ori_engine,
            zone_mgr=zone_mgr,
            qty_mgr=qty_mgr,
            active_skus=[self.sku_filler],
            wall=wall,
        )
        self.assertGreater(len(repair_cands), 0)

    def test_wall_007_height_mismatch(self):
        """WALL-007: Wall analyzer flags high height delta."""
        world = WorldState(container=self.container, cargo_catalog=[self.sku_brick])
        
        # Pillar on left reaching z=2.0m, while right remains z=0.4m
        world.commit(Placement("P_H1", "I", "SKU-BRICK", Point3D(0.0, 0.0, 0.0), Orientation3D(0.6, 0.4, 2.0, 0, 0, 0), 20.0, PlacementContext.MAIN_WALL))
        world.commit(Placement("P_H2", "I", "SKU-BRICK", Point3D(0.0, 2.0, 0.0), Orientation3D(0.6, 0.4, 0.4, 0, 0, 0), 20.0, PlacementContext.MAIN_WALL))

        walls = world.get_walls()
        wall = walls[0]
        self.assertGreater(wall.max_height_delta, 1.0)
        self.assertEqual(wall.completion_state, WallCompletionState.WALL_REPAIR)

    def test_wall_008_wall_close_repair(self):
        """WALL-008: WallCloseChecker rejects wall with high height delta or cavities."""
        world = WorldState(container=self.container, cargo_catalog=[self.sku_brick])
        world.commit(Placement("P1", "I", "SKU-BRICK", Point3D(0.0, 0.0, 0.0), Orientation3D(0.6, 0.4, 0.4, 0, 0, 0), 20.0, PlacementContext.MAIN_WALL))
        
        walls = world.get_walls()
        wall = walls[0]
        checker = WallCloseChecker()
        report = checker.evaluate_wall_close(wall, world.get_cavity_report())
        self.assertFalse(report.is_ready_to_close)
        self.assertGreater(len(report.rejection_reasons), 0)

    def test_wall_009_thin_display_wall(self):
        """WALL-009: Thin display boxes (depth=0.08m) form high-occupancy thin display walls."""
        sku_display = CargoSKU(
            sku_id="SKU-DISP",
            name="Thin Display",
            box=BoxDim(x=0.553, y=0.080, z=0.355),
            weight_kg=8.4,
            quantity=QuantityPlan(required=50),
            packing_roles=(PackingRole.MAIN_WALL,),
        )
        world = WorldState(container=self.container, cargo_catalog=[sku_display])
        for iy in range(20):
            world.commit(Placement(f"P_D_{iy}", "I", "SKU-DISP", Point3D(0.0, iy * 0.08, 0.0), Orientation3D(0.553, 0.08, 0.355, 0, 0, 0), 8.4, PlacementContext.MAIN_WALL))

        walls = world.get_walls()
        self.assertEqual(len(walls), 1)
        self.assertGreaterEqual(walls[0].wall_flatness, 0.85)

    def test_wall_010_multiple_consecutive_walls(self):
        """WALL-010: Longitudinal progression creates multiple consecutive structured walls."""
        world = WorldState(container=self.container, cargo_catalog=[self.sku_brick])
        
        # Wall 1 at x=0.0
        for iy in range(6):
            world.commit(Placement(f"W1_{iy}", "I", "SKU-BRICK", Point3D(0.0, iy * 0.4, 0.0), Orientation3D(0.6, 0.4, 0.4, 0, 0, 0), 20.0, PlacementContext.MAIN_WALL))
        # Wall 2 at x=0.6
        for iy in range(6):
            world.commit(Placement(f"W2_{iy}", "I", "SKU-BRICK", Point3D(0.6, iy * 0.4, 0.0), Orientation3D(0.6, 0.4, 0.4, 0, 0, 0), 20.0, PlacementContext.MAIN_WALL))

        walls = world.get_walls()
        self.assertGreaterEqual(len(walls), 2)

    def test_blk003b_logical_wall_collapses_same_band_micro_slices(self):
        """BLK-003B: equal X bands form one slice/wall instead of one wall per carton."""
        placements = [
            Placement(f"M_{iy}_{iz}", "I", "SKU-BRICK", Point3D(0.0, iy * 0.4, iz * 0.4),
                      Orientation3D(0.833, 0.4, 0.4, 0, 0, 0), 20.0, PlacementContext.MAIN_WALL)
            for iy in range(6) for iz in range(3)
        ]
        analyzer = WallStructureAnalyzer(self.container)
        slices = analyzer.extract_wall_slices(placements)
        walls = analyzer.extract_walls(placements)
        self.assertEqual(len(slices), 1)
        self.assertEqual(len(walls), 1)
        self.assertIsInstance(walls[0], LogicalWall)
        self.assertEqual(walls[0].item_count, 18)

    def test_blk003b_top_surface_is_area_bearing_and_available(self):
        """BLK-003B: logical walls expose a usable, quantitative top surface."""
        placements = [
            Placement(f"T_{iy}", "I", "SKU-BRICK", Point3D(0.0, iy * 0.4, 0.0),
                      Orientation3D(0.6, 0.4, 0.4, 0, 0, 0), 20.0, PlacementContext.MAIN_WALL)
            for iy in range(6)
        ]
        wall = WallStructureAnalyzer(self.container).extract_walls(placements)[0]
        self.assertIsNotNone(wall.frontier_surface)
        self.assertIsNotNone(wall.top_surface)
        self.assertTrue(wall.top_surface.available)
        self.assertGreater(wall.top_surface.covered_area_m2, 1.0)

    def test_blk003b_future_space_is_not_open_notch(self):
        """BLK-003B: empty capacity ahead of a flat wall has explicit future-space semantics."""
        placements = [
            Placement(f"F_{iy}", "I", "SKU-BRICK", Point3D(0.0, iy * 0.4, 0.0),
                      Orientation3D(0.6, 0.4, 0.8, 0, 0, 0), 20.0, PlacementContext.MAIN_WALL)
            for iy in range(6)
        ]
        report = AdvancedCavityClassifier(self.container).classify_cavities(placements)
        self.assertGreater(report.future_free_space_volume_m3, 0.0)
        self.assertEqual(report.open_notch_volume_m3, 0.0)


if __name__ == "__main__":
    unittest.main()
