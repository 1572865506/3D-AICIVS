"""
Unit Tests for Solver V2 Agent 08 — Wall / Top Fill / Door subsystem:
- Block / Layer / Wall Slice Pattern generation & instantiation
- Interlocking Pinwheel Pattern generation
- Wall Surface elevation mapping, occupancy, roughness, and flatness metrics
- Cavity & Enclosed Void detection (Bad Case 001 regression avoidance)
- Top Fill Planner & Conditional Flat Display Placement (7 scenarios from tests_spec/TOPFILL_TESTS.md)
- Door Closure Planner: clearance margin, door face flatness, anti-toppling, and readiness scoring
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
from backend.solver_v2.geometry.aabb import AABB
from backend.solver_v2.patterns.models import (
    PatternType,
    ItemOffset,
    PackedBlock,
    PatternCandidate,
)
from backend.solver_v2.patterns.generator import PatternGenerator
from backend.solver_v2.structure.wall_surface import (
    WallSurfaceMap,
    WallSurfaceMetrics,
)
from backend.solver_v2.structure.wall_manager import (
    CavityVoidDetector,
    WallStructureManager,
    EnclosedVoidReport,
)
from backend.solver_v2.topfill.planner import (
    TopFillPlanner,
    TopFillSpace,
    ConditionalFlatCheckResult,
)
from backend.solver_v2.door.closure_planner import (
    DoorClosurePlanner,
    DoorReadinessReport,
)
from backend.solver_v2.world.state import WorldState


class TestWallTopfillDoorAgent(unittest.TestCase):
    def setUp(self):
        # Canonical 40HQ Container: 12.0m x 2.4m x 2.6m, max payload 26000 kg
        self.container = ContainerSpec(
            code="40HQ_AGENT8",
            inner_dim=BoxDim(x=12.0, y=2.4, z=2.6),
            max_payload_kg=26000.0,
            door_zone_length_m=1.2,
            rear_zone_length_m=1.0,
        )

        # Standard Cube SKU: 0.6m x 0.4m x 0.5m, 30 kg
        self.sku_std = CargoSKU(
            sku_id="SKU_STD",
            name="Standard Box",
            box=BoxDim(x=0.6, y=0.4, z=0.5),
            weight_kg=30.0,
            quantity=QuantityPlan(required=100),
            orientation_policy=OrientationPolicy(
                allow_upright=True,
                allow_flat=True,
                allowed_contexts_for_flat=(PlacementContext.TOP_FILL, PlacementContext.GAP_FILL),
                max_flat_stack_layers=2,
                flat_orientation_penalty=30.0,
            ),
            stacking_policy=StackingPolicy(
                max_stack_layers=5,
                max_bearing_kg=400.0,
                min_support_ratio=0.70,
                max_unsupported_span_m=0.10,
                allow_stacking_on_top=True,
            ),
            packing_roles=(PackingRole.MAIN_WALL, PackingRole.FOUNDATION),
        )

        # Canonical Display Carton (from docs/ORIENTATION_TOPFILL.md & tests_spec/TOPFILL_TESTS.md)
        # Dimensions: 0.553 x 0.080 x 0.355 (length=0.553, thickness=0.080, height=0.355)
        self.sku_display = CargoSKU(
            sku_id="SKU_DISPLAY",
            name="Display Carton",
            box=BoxDim(x=0.553, y=0.080, z=0.355),
            weight_kg=15.0,
            quantity=QuantityPlan(required=50),
            orientation_policy=OrientationPolicy(
                allow_upright=True,
                allow_flat=True,
                allowed_contexts_for_flat=(PlacementContext.TOP_FILL,),
                max_flat_stack_layers=2,
                flat_orientation_penalty=50.0,
            ),
            stacking_policy=StackingPolicy(
                max_bearing_kg=120.0,
                min_support_ratio=0.70,
                max_unsupported_span_m=0.10,
                allow_stacking_on_top=True,
            ),
            packing_roles=(PackingRole.MAIN_WALL, PackingRole.TOP_FILL),
        )

        # Base / Foundation SKU (Rigid support base): 1.2m x 0.8m x 1.0m, 200 kg
        self.sku_base = CargoSKU(
            sku_id="SKU_BASE",
            name="Rigid Base Cargo",
            box=BoxDim(x=1.2, y=0.8, z=1.0),
            weight_kg=200.0,
            quantity=QuantityPlan(required=20),
            stacking_policy=StackingPolicy(
                max_bearing_kg=1000.0,
                allow_stacking_on_top=True,
            ),
            packing_roles=(PackingRole.FOUNDATION,),
        )

        # Fragile / Low-Bearing SKU (Bearing = 20 kg): 0.6m x 0.4m x 0.5m
        self.sku_fragile = CargoSKU(
            sku_id="SKU_FRAGILE",
            name="Fragile Lower Box",
            box=BoxDim(x=0.6, y=0.4, z=0.5),
            weight_kg=20.0,
            quantity=QuantityPlan(required=10),
            stacking_policy=StackingPolicy(
                max_bearing_kg=20.0,  # Cannot support heavy top cargo
                allow_stacking_on_top=True,
            ),
        )

        # Door Seal SKU
        self.sku_door_seal = CargoSKU(
            sku_id="SKU_DOOR_SEAL",
            name="Door Barrier Carton",
            box=BoxDim(x=0.4, y=0.6, z=0.8),
            weight_kg=40.0,
            quantity=QuantityPlan(required=12),
            packing_roles=(PackingRole.DOOR_SEAL, PackingRole.FLEXIBLE),
        )

        self.catalog = {
            "SKU_STD": self.sku_std,
            "SKU_DISPLAY": self.sku_display,
            "SKU_BASE": self.sku_base,
            "SKU_FRAGILE": self.sku_fragile,
            "SKU_DOOR_SEAL": self.sku_door_seal,
        }

    # =========================================================================
    # 1. Pattern Engine Tests
    # =========================================================================

    def test_pattern_generator_homogeneous_blocks(self):
        """Test generating homogeneous 3D blocks and layer patterns for a SKU."""
        generator = PatternGenerator(container=self.container)
        blocks = generator.generate_blocks_for_sku(
            sku=self.sku_std,
            context=PlacementContext.MAIN_WALL,
            max_nx=2,
            max_ny=3,
            max_nz=2,
        )

        self.assertGreater(len(blocks), 0)
        for b in blocks:
            self.assertEqual(b.total_cartons, b.nx * b.ny * b.nz)
            self.assertEqual(len(b.item_offsets), b.total_cartons)
            self.assertAlmostEqual(b.total_weight_kg, b.total_cartons * self.sku_std.weight_kg, places=3)
            self.assertAlmostEqual(b.volume, b.bounding_box.x * b.bounding_box.y * b.bounding_box.z, places=5)

    def test_pattern_instantiation(self):
        """Test instantiating a PackedBlock into concrete Placement objects at an anchor."""
        generator = PatternGenerator(container=self.container)
        blocks = generator.generate_blocks_for_sku(
            sku=self.sku_std,
            context=PlacementContext.MAIN_WALL,
            max_nx=2,
            max_ny=2,
            max_nz=2,
        )
        b2x2x2 = [b for b in blocks if b.nx == 2 and b.ny == 2 and b.nz == 2][0]

        anchor = Point3D(1.0, 0.4, 0.0)
        placements = b2x2x2.instantiate(
            anchor_position=anchor,
            context=PlacementContext.MAIN_WALL,
            placement_id_prefix="p_block",
        )

        self.assertEqual(len(placements), 8)
        min_x = min(p.min_x for p in placements)
        max_x = max(p.max_x for p in placements)
        min_y = min(p.min_y for p in placements)
        max_y = max(p.max_y for p in placements)
        min_z = min(p.min_z for p in placements)
        max_z = max(p.max_z for p in placements)

        self.assertAlmostEqual(min_x, 1.0, places=5)
        self.assertAlmostEqual(max_x, 1.0 + b2x2x2.bounding_box.x, places=5)
        self.assertAlmostEqual(min_y, 0.4, places=5)
        self.assertAlmostEqual(max_y, 0.4 + b2x2x2.bounding_box.y, places=5)
        self.assertAlmostEqual(min_z, 0.0, places=5)
        self.assertAlmostEqual(max_z, b2x2x2.bounding_box.z, places=5)

    def test_pattern_generator_wall_slices_and_pinwheel(self):
        """Test transverse wall slice and interlocked pinwheel generation."""
        generator = PatternGenerator(container=self.container)

        slices = generator.generate_wall_slices(
            sku=self.sku_std,
            container_ly=self.container.Ly,
            container_lz=self.container.Lz,
        )
        self.assertGreater(len(slices), 0)
        top_slice = slices[0]
        self.assertEqual(top_slice.nx, 1)
        self.assertLessEqual(top_slice.bounding_box.y, self.container.Ly + 1e-4)
        self.assertLessEqual(top_slice.bounding_box.z, self.container.Lz + 1e-4)

        pw_patterns = generator.generate_pinwheel_layers(
            sku=self.sku_std,
            target_width=2.4,
            target_depth=2.4,
        )
        self.assertEqual(len(pw_patterns), 1)
        pw = pw_patterns[0]
        self.assertEqual(pw.pattern_type, PatternType.PINWHEEL)
        self.assertEqual(pw.total_cartons, 4)
        self.assertAlmostEqual(pw.bounding_box.x, 1.0, places=4)
        self.assertAlmostEqual(pw.bounding_box.y, 1.0, places=4)

    # =========================================================================
    # 2. Wall Surface & Structure Metrics Tests
    # =========================================================================

    def test_wall_surface_flat_vs_irregular_face(self):
        """Test that a flat vertical wall yields high flatness while a jagged wall yields lower score."""
        surface_map = WallSurfaceMap(container=self.container, grid_resolution_m=0.1)

        flat_placements = [
            Placement("f1", "i1", "SKU_STD", Point3D(0.0, 0.0, 0.0), Orientation3D(1.0, 1.0, 1.0), 50.0, PlacementContext.MAIN_WALL),
            Placement("f2", "i2", "SKU_STD", Point3D(0.0, 1.0, 0.0), Orientation3D(1.0, 1.0, 1.0), 50.0, PlacementContext.MAIN_WALL),
            Placement("f3", "i3", "SKU_STD", Point3D(0.0, 0.0, 1.0), Orientation3D(1.0, 1.0, 1.0), 50.0, PlacementContext.MAIN_WALL),
            Placement("f4", "i4", "SKU_STD", Point3D(0.0, 1.0, 1.0), Orientation3D(1.0, 1.0, 1.0), 50.0, PlacementContext.MAIN_WALL),
        ]
        flat_metrics = surface_map.build_from_placements(flat_placements)
        self.assertAlmostEqual(flat_metrics.flatness_score, 1.0, places=2)
        self.assertAlmostEqual(flat_metrics.variance_x, 0.0, places=4)
        self.assertAlmostEqual(flat_metrics.max_step_discontinuity, 0.0, places=4)

        jagged_placements = list(flat_placements)
        jagged_placements.append(
            Placement("j1", "i5", "SKU_STD", Point3D(1.0, 0.0, 0.0), Orientation3D(1.0, 1.0, 1.0), 50.0, PlacementContext.MAIN_WALL)
        )
        jagged_metrics = surface_map.build_from_placements(jagged_placements)
        self.assertLess(jagged_metrics.flatness_score, flat_metrics.flatness_score)
        self.assertGreater(jagged_metrics.max_step_discontinuity, 0.5)

    def test_wall_manager_slicing(self):
        """Test transverse wall slice segmentation."""
        manager = WallStructureManager(container=self.container)
        placements = [
            Placement("p1", "i1", "SKU_STD", Point3D(0.0, 0.0, 0.0), Orientation3D(1.0, 1.0, 1.0), 50.0, PlacementContext.MAIN_WALL),
            Placement("p2", "i2", "SKU_STD", Point3D(1.0, 0.0, 0.0), Orientation3D(1.0, 1.0, 1.0), 50.0, PlacementContext.MAIN_WALL),
        ]
        slices = manager.slice_container_walls(placements, slice_thickness_m=0.5)
        self.assertEqual(len(slices), 4)

    # =========================================================================
    # 3. Bad Case 001 Regression Avoidance (Cavity & Enclosed Void Detection)
    # =========================================================================

    def test_bad_case_001_enclosed_void_detection(self):
        """
        Regression Test for Bad Case 001:
        Construct a cargo layout with an enclosed hollow cavity trapped behind outer cargo walls.
        CavityVoidDetector must detect the hollow void, calculate its volume, and flag a violation.
        """
        void_detector = CavityVoidDetector(container=self.container, voxel_res_m=0.10)

        placements: List[Placement] = []
        pid = 0
        box_dim = Orientation3D(0.5, 0.5, 0.5)

        for ix in range(3):
            for iy in range(3):
                for iz in range(3):
                    if ix == 1 and iy == 1 and iz == 1:
                        continue
                    pid += 1
                    placements.append(
                        Placement(
                            placement_id=f"p_hollow_{pid}",
                            instance_id=f"inst_{pid}",
                            sku_id="SKU_STD",
                            position=Point3D(ix * 0.5, iy * 0.5, iz * 0.5),
                            orientation=box_dim,
                            weight_kg=20.0,
                            context=PlacementContext.MAIN_WALL,
                        )
                    )

        void_report = void_detector.detect_enclosed_voids(placements, max_allowed_void_vol_m3=0.01)

        self.assertTrue(void_report.has_enclosed_voids)
        self.assertGreater(void_report.void_count, 0)
        self.assertGreater(void_report.total_void_volume_m3, 0.05)
        self.assertGreater(void_report.enclosed_void_penalty, 50.0)
        self.assertIsNotNone(void_report.rejection_reason)
        self.assertIn("Bad Case 001", void_report.rejection_reason)

    def test_solid_cargo_has_no_enclosed_voids(self):
        """Test that a completely packed solid block has zero enclosed voids."""
        void_detector = CavityVoidDetector(container=self.container, voxel_res_m=0.10)
        placements: List[Placement] = []
        pid = 0
        box_dim = Orientation3D(0.5, 0.5, 0.5)

        for ix in range(2):
            for iy in range(2):
                for iz in range(2):
                    pid += 1
                    placements.append(
                        Placement(
                            placement_id=f"p_solid_{pid}",
                            instance_id=f"inst_{pid}",
                            sku_id="SKU_STD",
                            position=Point3D(ix * 0.5, iy * 0.5, iz * 0.5),
                            orientation=box_dim,
                            weight_kg=20.0,
                            context=PlacementContext.MAIN_WALL,
                        )
                    )

        void_report = void_detector.detect_enclosed_voids(placements)
        self.assertFalse(void_report.has_enclosed_voids)
        self.assertEqual(void_report.void_count, 0)
        self.assertAlmostEqual(void_report.total_void_volume_m3, 0.0, places=4)

    # =========================================================================
    # 4. Top Fill Planner & Conditional Flat Placement Tests (tests_spec/TOPFILL_TESTS.md)
    # =========================================================================

    def test_topfill_scenario_1_upright_preferred_when_room_exists(self):
        """
        Scenario 1: Main body has ample room for upright placement.
        Flat orientation should not be preferred (penalty > 0, upright preferred).
        """
        topfill_planner = TopFillPlanner(container=self.container)
        ws = WorldState(container=self.container, cargo_catalog=[self.sku_display])

        p_upright = Placement(
            placement_id="p_disp_upright",
            instance_id="i1",
            sku_id="SKU_DISPLAY",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(0.553, 0.080, 0.355, name="UPRIGHT_NORMAL", is_upright=True),
            weight_kg=15.0,
            context=PlacementContext.MAIN_WALL,
        )
        p_flat = Placement(
            placement_id="p_disp_flat",
            instance_id="i2",
            sku_id="SKU_DISPLAY",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(0.553, 0.355, 0.080, name="FLAT_XZ", is_flat=True, is_upright=False),
            weight_kg=15.0,
            context=PlacementContext.MAIN_WALL,
        )

        res_upright = topfill_planner.evaluate_conditional_flat_placement(self.sku_display, p_upright, ws, catalog=self.catalog)
        res_flat = topfill_planner.evaluate_conditional_flat_placement(self.sku_display, p_flat, ws, catalog=self.catalog)

        self.assertTrue(res_upright.is_valid)
        self.assertEqual(res_upright.penalty_score, 0.0)

        self.assertFalse(res_flat.is_valid)
        self.assertFalse(res_flat.flat_policy_allowed)

    def test_topfill_scenario_2_conditional_flat_legal_in_top_gap(self):
        """
        Scenario 2: Top gap < upright height (0.355m) but >= flat thickness (0.080m).
        Conditional flat is legal in TOP_FILL context.
        """
        topfill_planner = TopFillPlanner(container=self.container)
        ws = WorldState(container=self.container, cargo_catalog=[self.sku_base, self.sku_display])

        p_base = Placement(
            placement_id="p_base",
            instance_id="i_base",
            sku_id="SKU_BASE",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(1.2, 0.8, 2.45),
            weight_kg=400.0,
            context=PlacementContext.FOUNDATION,
        )
        ws.commit(p_base)

        p_flat_top = Placement(
            placement_id="p_disp_top",
            instance_id="i_top",
            sku_id="SKU_DISPLAY",
            position=Point3D(0.0, 0.0, 2.45),
            orientation=Orientation3D(0.553, 0.355, 0.080, name="FLAT_XZ", is_flat=True, is_upright=False),
            weight_kg=15.0,
            context=PlacementContext.TOP_FILL,
        )

        target_headspace = AABB(0.0, 0.0, 2.45, 1.2, 0.8, 2.60)
        res = topfill_planner.evaluate_conditional_flat_placement(
            self.sku_display,
            p_flat_top,
            ws,
            target_space=target_headspace,
            catalog=self.catalog,
        )

        self.assertFalse(res.upright_fits)
        self.assertTrue(res.flat_policy_allowed)
        self.assertTrue(res.support_ratio_passed)
        self.assertTrue(res.unsupported_span_passed)
        self.assertTrue(res.lower_compression_passed)
        self.assertTrue(res.is_valid)

    def test_topfill_scenario_3_insufficient_support_ratio_rejected(self):
        """Scenario 3: Insufficient support ratio (< 70%) -> reject."""
        topfill_planner = TopFillPlanner(container=self.container)
        ws = WorldState(container=self.container, cargo_catalog=[self.sku_base, self.sku_display])

        p_narrow = Placement(
            placement_id="p_narrow",
            instance_id="i_narrow",
            sku_id="SKU_BASE",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(0.6, 0.10, 2.45),
            weight_kg=100.0,
            context=PlacementContext.FOUNDATION,
        )
        ws.commit(p_narrow)

        p_flat_overhang = Placement(
            placement_id="p_flat_overhang",
            instance_id="i_top",
            sku_id="SKU_DISPLAY",
            position=Point3D(0.0, 0.0, 2.45),
            orientation=Orientation3D(0.553, 0.355, 0.080, name="FLAT_XZ", is_flat=True, is_upright=False),
            weight_kg=15.0,
            context=PlacementContext.TOP_FILL,
        )

        res = topfill_planner.evaluate_conditional_flat_placement(self.sku_display, p_flat_overhang, ws, catalog=self.catalog)
        self.assertFalse(res.is_valid)
        self.assertFalse(res.support_ratio_passed)
        self.assertLess(res.support_ratio, 0.70)
        self.assertTrue(any("Support ratio" in r for r in res.rejection_reasons))

    def test_topfill_scenario_4_excessive_unsupported_span_rejected(self):
        """Scenario 4: Excessive unsupported overhang span (> 0.10m) -> reject."""
        topfill_planner = TopFillPlanner(container=self.container)
        ws = WorldState(container=self.container, cargo_catalog=[self.sku_base, self.sku_display])

        p_base_short = Placement(
            placement_id="p_short",
            instance_id="i_short",
            sku_id="SKU_BASE",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(0.35, 0.8, 2.45),
            weight_kg=100.0,
            context=PlacementContext.FOUNDATION,
        )
        ws.commit(p_base_short)

        p_flat_span = Placement(
            placement_id="p_flat_span",
            instance_id="i_top",
            sku_id="SKU_DISPLAY",
            position=Point3D(0.0, 0.0, 2.45),
            orientation=Orientation3D(0.553, 0.355, 0.080, name="FLAT_XZ", is_flat=True, is_upright=False),
            weight_kg=15.0,
            context=PlacementContext.TOP_FILL,
        )

        res = topfill_planner.evaluate_conditional_flat_placement(self.sku_display, p_flat_span, ws, catalog=self.catalog)
        self.assertFalse(res.is_valid)
        self.assertFalse(res.unsupported_span_passed)
        self.assertGreater(res.unsupported_span_m, 0.10)
        self.assertTrue(any("Unsupported span" in r for r in res.rejection_reasons))

    def test_topfill_scenario_5_lower_cargo_compression_exceeded_rejected(self):
        """Scenario 5: Lower cargo compression exceeded -> reject."""
        topfill_planner = TopFillPlanner(container=self.container)
        ws = WorldState(container=self.container, cargo_catalog=[self.sku_fragile, self.sku_base])

        p_fragile = Placement(
            placement_id="p_fragile_base",
            instance_id="i_frag",
            sku_id="SKU_FRAGILE",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(1.2, 0.8, 1.0),
            weight_kg=20.0,
            context=PlacementContext.FOUNDATION,
        )
        ws.commit(p_fragile)

        p_heavy_top = Placement(
            placement_id="p_heavy_top",
            instance_id="i_heavy",
            sku_id="SKU_BASE",
            position=Point3D(0.0, 0.0, 1.0),
            orientation=Orientation3D(1.2, 0.8, 1.0),
            weight_kg=200.0,
            context=PlacementContext.TOP_FILL,
        )

        res = topfill_planner.evaluate_conditional_flat_placement(self.sku_base, p_heavy_top, ws, catalog=self.catalog)
        self.assertFalse(res.is_valid)
        self.assertFalse(res.lower_compression_passed)
        self.assertTrue(any("Bearing limit exceeded" in r for r in res.rejection_reasons))

    def test_topfill_scenario_6_flat_layer_limit_exceeded_rejected(self):
        """Scenario 6: Consecutive flat layer count exceeded (> 2) -> reject."""
        topfill_planner = TopFillPlanner(container=self.container)
        ws = WorldState(container=self.container, cargo_catalog=[self.sku_base, self.sku_display])

        p_base = Placement("p_base", "i_base", "SKU_BASE", Point3D(0, 0, 0), Orientation3D(1.2, 0.8, 2.0), 300.0, PlacementContext.FOUNDATION)
        ws.commit(p_base)

        p_flat_1 = Placement("p_f1", "i_f1", "SKU_DISPLAY", Point3D(0, 0, 2.0), Orientation3D(0.553, 0.355, 0.080, name="FLAT_XZ", is_flat=True), 15.0, PlacementContext.TOP_FILL)
        ws.commit(p_flat_1)

        p_flat_2 = Placement("p_f2", "i_f2", "SKU_DISPLAY", Point3D(0, 0, 2.08), Orientation3D(0.553, 0.355, 0.080, name="FLAT_XZ", is_flat=True), 15.0, PlacementContext.TOP_FILL)
        ws.commit(p_flat_2)

        p_flat_3 = Placement("p_f3", "i_f3", "SKU_DISPLAY", Point3D(0, 0, 2.16), Orientation3D(0.553, 0.355, 0.080, name="FLAT_XZ", is_flat=True), 15.0, PlacementContext.TOP_FILL)

        res = topfill_planner.evaluate_conditional_flat_placement(self.sku_display, p_flat_3, ws, catalog=self.catalog)
        self.assertFalse(res.is_valid)
        self.assertFalse(res.flat_layer_limit_passed)
        self.assertEqual(res.flat_layer_count, 3)
        self.assertTrue(any("Flat stack layer count" in r for r in res.rejection_reasons))

    def test_topfill_scenario_7_all_conditions_pass_and_block_generation(self):
        """Scenario 7: All criteria pass -> accept and generate TopFillBlock."""
        topfill_planner = TopFillPlanner(container=self.container)
        ws = WorldState(container=self.container, cargo_catalog=[self.sku_base, self.sku_display])

        p_base = Placement("p_base", "i_base", "SKU_BASE", Point3D(0, 0, 0), Orientation3D(1.2, 0.8, 2.44), 300.0, PlacementContext.FOUNDATION)
        ws.commit(p_base)

        top_spaces = topfill_planner.identify_top_spaces(ws, min_top_height_m=0.05)
        self.assertEqual(len(top_spaces), 1)
        space = top_spaces[0]
        self.assertAlmostEqual(space.available_height, 0.16, places=3)

        block = topfill_planner.generate_topfill_block(
            sku=self.sku_display,
            target_headspace=space,
            world_state=ws,
            max_quantity=10,
            catalog=self.catalog,
        )

        self.assertIsNotNone(block)
        self.assertTrue(block.unit_orientation.is_flat)
        self.assertLessEqual(block.nz, 2)
        self.assertLessEqual(block.bounding_box.z, space.available_height + 1e-4)

    # =========================================================================
    # 5. Door Closure Planner Tests
    # =========================================================================

    def test_door_closure_planner_evaluation_and_boundary_check(self):
        """Test door readiness, clearance margin, and out-of-bounds rejection."""
        door_planner = DoorClosurePlanner(container=self.container)

        p_exceeding = Placement(
            placement_id="p_exceed",
            instance_id="i_exceed",
            sku_id="SKU_DOOR_SEAL",
            position=Point3D(11.5, 0.0, 0.0),
            orientation=Orientation3D(0.6, 0.6, 0.8),
            weight_kg=40.0,
            context=PlacementContext.DOOR_SEAL,
        )
        rep_invalid = door_planner.evaluate_door_readiness([p_exceeding])
        self.assertFalse(rep_invalid.is_door_ready)
        self.assertTrue(any("Cargo exceeds door boundary" in r for r in rep_invalid.rejection_reasons))

        p_door1 = Placement(
            placement_id="p_d1",
            instance_id="i_d1",
            sku_id="SKU_DOOR_SEAL",
            position=Point3D(11.0, 0.0, 0.0),
            orientation=Orientation3D(0.8, 1.2, 1.2),
            weight_kg=100.0,
            context=PlacementContext.DOOR_SEAL,
        )
        p_door2 = Placement(
            placement_id="p_d2",
            instance_id="i_d2",
            sku_id="SKU_DOOR_SEAL",
            position=Point3D(11.0, 1.2, 0.0),
            orientation=Orientation3D(0.8, 1.2, 1.2),
            weight_kg=100.0,
            context=PlacementContext.DOOR_SEAL,
        )

        rep_valid = door_planner.evaluate_door_readiness([p_door1, p_door2])
        self.assertTrue(rep_valid.is_door_ready)
        self.assertAlmostEqual(rep_valid.door_clearance_margin_m, 0.2, places=4)
        self.assertGreater(rep_valid.door_face_flatness, 0.90)
        self.assertGreaterEqual(rep_valid.door_readiness_score, 70.0)

    def test_door_closure_filter_skus(self):
        """Test prioritizing SKUs configured with PackingRole.DOOR_SEAL."""
        door_planner = DoorClosurePlanner(container=self.container)
        door_skus = door_planner.filter_door_skus(list(self.catalog.values()))

        self.assertGreater(len(door_skus), 0)
        self.assertEqual(door_skus[0].sku_id, "SKU_DOOR_SEAL")


if __name__ == "__main__":
    unittest.main()
