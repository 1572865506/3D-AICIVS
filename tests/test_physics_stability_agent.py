"""
Unit Tests for Solver V2 Agent 07 — Physics & Stability Engine:
- SupportGraph (DAG, support ratio, load ratio, grounding, topological sort, rollback)
- ContactGraph (6-direction contact detection, boundary bracing, lateral contacts, rollback)
- LoadPropagationEngine (fractional multi-layer load distribution, compression vs max_bearing, max_pressure, no-top-stack)
- ItemStabilityEvaluator (COM projection, cantilever overhang, edge margin, slenderness, lateral bracing)
- ClusterStabilityEvaluator (interlocked connected groups, collective COM, floor footprint, interlock score)
- WallStabilityEvaluator (transverse wall slices, H/T ratio, tipping moment resistance under deceleration, rear bracing)
- StabilityDebtTracker (bounded quota, neighbor resolution, zero-debt enforcement, rollback)
- PhysicsStabilityEngine & WorldState integration
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
    ZoneType,
    PackingRole,
)
from backend.solver_v2.physics.contact_graph import (
    ContactGraph,
    ContactEdge,
    ContactDirection,
    NODE_FLOOR,
    NODE_ROOF,
    NODE_WALL_BACK,
    NODE_WALL_LEFT,
    NODE_WALL_RIGHT,
)
from backend.solver_v2.physics.support_graph import (
    SupportGraph,
    SupportEdge,
)
from backend.solver_v2.physics.load_propagation import (
    LoadPropagationEngine,
    GlobalLoadReport,
    ItemLoadReport,
)
from backend.solver_v2.stability.models import (
    StabilityState,
    ItemStabilityReport,
    ClusterStabilityReport,
    WallStabilityReport,
    StabilityDebtItem,
)
from backend.solver_v2.stability.item_stability import ItemStabilityEvaluator
from backend.solver_v2.stability.cluster_stability import ClusterStabilityEvaluator
from backend.solver_v2.stability.wall_stability import WallStabilityEvaluator
from backend.solver_v2.stability.debt import (
    StabilityDebtTracker,
    StabilityDebtLimitExceeded,
    UnresolvedStabilityDebtError,
)
from backend.solver_v2.physics.evaluator import (
    PhysicsStabilityEngine,
    PhysicsStabilityReport,
)
from backend.solver_v2.world.state import WorldState


class TestPhysicsStabilityAgent(unittest.TestCase):
    def setUp(self):
        # Canonical 40HQ-like Container: 12.0m x 2.4m x 2.6m, max payload 26000 kg
        self.container = ContainerSpec(
            code="40HQ_TEST",
            inner_dim=BoxDim(x=12.0, y=2.4, z=2.6),
            max_payload_kg=26000.0,
            door_zone_length_m=1.2,
            rear_zone_length_m=1.0,
        )

        # Standard SKU: 1.0m x 1.0m x 1.0m, 100 kg
        self.sku_std = CargoSKU(
            sku_id="SKU_STD",
            name="Standard Cube",
            box=BoxDim(x=1.0, y=1.0, z=1.0),
            weight_kg=100.0,
            quantity=QuantityPlan(required=20),
            stacking_policy=StackingPolicy(
                max_bearing_kg=500.0,
                max_pressure_kg_m2=1000.0,
                min_support_ratio=0.70,
                max_unsupported_span_m=0.15,
                allow_stacking_on_top=True,
                must_be_on_floor=False,
            ),
        )

        # Heavy SKU: 1.0m x 1.0m x 1.0m, 800 kg
        self.sku_heavy = CargoSKU(
            sku_id="SKU_HEAVY",
            name="Heavy Base",
            box=BoxDim(x=1.0, y=1.0, z=1.0),
            weight_kg=800.0,
            quantity=QuantityPlan(required=5),
            stacking_policy=StackingPolicy(
                max_bearing_kg=2000.0,
                min_support_ratio=0.80,
                allow_stacking_on_top=True,
            ),
        )

        # Fragile SKU: max bearing 50 kg, no top stacking
        self.sku_fragile = CargoSKU(
            sku_id="SKU_FRAGILE",
            name="Fragile Electronics",
            box=BoxDim(x=1.0, y=1.0, z=1.0),
            weight_kg=50.0,
            quantity=QuantityPlan(required=5),
            stacking_policy=StackingPolicy(
                max_bearing_kg=0.0,
                allow_stacking_on_top=False,
            ),
        )

        # Tall Slender SKU: 0.4m x 0.4m x 1.6m, 60 kg (slenderness = 4.0)
        self.sku_tall = CargoSKU(
            sku_id="SKU_TALL",
            name="Tall Slender Column",
            box=BoxDim(x=0.4, y=0.4, z=1.6),
            weight_kg=60.0,
            quantity=QuantityPlan(required=10),
            stacking_policy=StackingPolicy(
                min_support_ratio=0.75,
                allow_stacking_on_top=True,
            ),
        )

        self.catalog = {
            "SKU_STD": self.sku_std,
            "SKU_HEAVY": self.sku_heavy,
            "SKU_FRAGILE": self.sku_fragile,
            "SKU_TALL": self.sku_tall,
        }

    # =========================================================================
    # 1. SupportGraph Tests
    # =========================================================================

    def test_support_graph_floor_and_direct_stacking(self):
        """Test vertical support graph for floor base and stacked boxes."""
        sg = SupportGraph(container=self.container)

        # p1 on floor
        p1 = Placement(
            placement_id="p1",
            instance_id="i1",
            sku_id="SKU_STD",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.0, dz=1.0),
            weight_kg=100.0,
            context=PlacementContext.FOUNDATION,
        )
        # p2 stacked directly on p1
        p2 = Placement(
            placement_id="p2",
            instance_id="i2",
            sku_id="SKU_STD",
            position=Point3D(0.0, 0.0, 1.0),
            orientation=Orientation3D(dx=1.0, dy=1.0, dz=1.0),
            weight_kg=100.0,
            context=PlacementContext.MAIN_WALL,
        )

        sg.add_placement(p1)
        sg.add_placement(p2)

        # Check p1 support
        self.assertTrue(sg.is_on_floor("p1"))
        self.assertEqual(sg.get_total_support_ratio("p1"), 1.0)
        p1_supp = sg.get_support_edges("p1")
        self.assertEqual(len(p1_supp), 1)
        self.assertEqual(p1_supp[0].lower_id, NODE_FLOOR)

        # Check p2 support
        self.assertFalse(sg.is_on_floor("p2"))
        self.assertEqual(sg.get_total_support_ratio("p2"), 1.0)
        p2_supp = sg.get_support_edges("p2")
        self.assertEqual(len(p2_supp), 1)
        self.assertEqual(p2_supp[0].lower_id, "p1")
        self.assertEqual(p2_supp[0].contact_area, 1.0)

        # Check p1 supported edges (upward)
        p1_supported = sg.get_supported_edges("p1")
        self.assertEqual(len(p1_supported), 1)
        self.assertEqual(p1_supported[0].upper_id, "p2")

        # Grounding check
        self.assertTrue(sg.is_grounded_to_floor("p1"))
        self.assertTrue(sg.is_grounded_to_floor("p2"))

        # Topological order top-down
        order = sg.topological_order_top_down()
        self.assertEqual(order, ["p2", "p1"])

    def test_support_graph_multi_support_and_partial_contact(self):
        """Test a box spanning across two lower boxes with exact fractional areas."""
        sg = SupportGraph(container=self.container)

        # Two base boxes side by side along Y
        p_left = Placement(
            placement_id="p_left",
            instance_id="i_left",
            sku_id="SKU_STD",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.0, dz=1.0),
            weight_kg=100.0,
            context=PlacementContext.FOUNDATION,
        )
        p_right = Placement(
            placement_id="p_right",
            instance_id="i_right",
            sku_id="SKU_STD",
            position=Point3D(0.0, 1.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.0, dz=1.0),
            weight_kg=100.0,
            context=PlacementContext.FOUNDATION,
        )
        # Bridge box spanning 0.5m on p_left and 0.5m on p_right
        p_bridge = Placement(
            placement_id="p_bridge",
            instance_id="i_bridge",
            sku_id="SKU_STD",
            position=Point3D(0.0, 0.5, 1.0),
            orientation=Orientation3D(dx=1.0, dy=1.0, dz=1.0),
            weight_kg=100.0,
            context=PlacementContext.MAIN_WALL,
        )

        sg.add_placement(p_left)
        sg.add_placement(p_right)
        sg.add_placement(p_bridge)

        edges = sg.get_support_edges("p_bridge")
        self.assertEqual(len(edges), 2)
        lower_ids = {e.lower_id for e in edges}
        self.assertEqual(lower_ids, {"p_left", "p_right"})

        # Each lower box supports exactly 0.5 m^2 (50% ratio)
        for e in edges:
            self.assertAlmostEqual(e.contact_area, 0.5, places=5)
            self.assertAlmostEqual(e.support_ratio, 0.5, places=5)

        self.assertAlmostEqual(sg.get_total_support_ratio("p_bridge"), 1.0, places=5)

    def test_support_graph_rollback(self):
        """Test removing placement cleanly restores graph topology."""
        sg = SupportGraph(container=self.container)
        p1 = Placement("p1", "i1", "SKU_STD", Point3D(0, 0, 0), Orientation3D(1, 1, 1), 100.0, PlacementContext.FOUNDATION)
        p2 = Placement("p2", "i2", "SKU_STD", Point3D(0, 0, 1), Orientation3D(1, 1, 1), 100.0, PlacementContext.MAIN_WALL)

        sg.add_placement(p1)
        sg.add_placement(p2)
        self.assertEqual(len(sg.get_supported_edges("p1")), 1)

        # Rollback p2
        sg.remove_placement("p2")
        self.assertNotIn("p2", sg.placements)
        self.assertEqual(len(sg.get_supported_edges("p1")), 0)
        self.assertEqual(len(sg.get_support_edges("p2")), 0)

    # =========================================================================
    # 2. ContactGraph Tests
    # =========================================================================

    def test_contact_graph_6_directions_and_boundary_bracing(self):
        """Test contact graph detects container boundary walls and pairwise lateral contacts."""
        cg = ContactGraph(container=self.container)

        # p1 placed at corner (x=0, y=0, z=0)
        p1 = Placement(
            placement_id="p1",
            instance_id="i1",
            sku_id="SKU_STD",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.0, dz=1.0),
            weight_kg=100.0,
            context=PlacementContext.FOUNDATION,
        )
        cg.add_placement(p1)

        # Check boundary contacts on p1
        self.assertTrue(cg.has_boundary_bracing("p1", ContactDirection.BOTTOM))  # Floor
        self.assertTrue(cg.has_boundary_bracing("p1", ContactDirection.BACK))    # Rear wall (x=0)
        self.assertTrue(cg.has_boundary_bracing("p1", ContactDirection.LEFT))    # Left wall (y=0)
        self.assertFalse(cg.has_boundary_bracing("p1", ContactDirection.RIGHT))
        self.assertFalse(cg.has_boundary_bracing("p1", ContactDirection.TOP))

        # Add p2 adjacent to p1 along Y (y=1.0)
        p2 = Placement(
            placement_id="p2",
            instance_id="i2",
            sku_id="SKU_STD",
            position=Point3D(0.0, 1.0, 0.0),
            orientation=Orientation3D(dx=1.0, dy=1.0, dz=1.0),
            weight_kg=100.0,
            context=PlacementContext.FOUNDATION,
        )
        cg.add_placement(p2)

        # p1 right contact touches p2 left contact
        p1_right = cg.get_contacts_in_direction("p1", ContactDirection.RIGHT)
        self.assertEqual(len(p1_right), 1)
        self.assertEqual(p1_right[0].node_b, "p2")
        self.assertTrue(p1_right[0].is_lateral)
        self.assertAlmostEqual(p1_right[0].contact_area, 1.0, places=5)

        p2_left = cg.get_contacts_in_direction("p2", ContactDirection.LEFT)
        self.assertEqual(len(p2_left), 1)
        self.assertEqual(p2_left[0].node_b, "p1")
        self.assertTrue(p2_left[0].is_lateral)

        # Test rollback on ContactGraph
        cg.remove_placement("p2")
        self.assertNotIn("p2", cg.placements)
        self.assertEqual(len(cg.get_contacts_in_direction("p1", ContactDirection.RIGHT)), 0)

    # =========================================================================
    # 3. Load Propagation & Compression Tests
    # =========================================================================

    def test_load_propagation_multi_layer_stack(self):
        """Test multi-tier vertical load propagation (p1 at z=0, p2 at z=1, p3 at z=2)."""
        sg = SupportGraph(container=self.container)
        load_engine = LoadPropagationEngine()

        p1 = Placement("p1", "i1", "SKU_STD", Point3D(0, 0, 0), Orientation3D(1, 1, 1), 100.0, PlacementContext.FOUNDATION)
        p2 = Placement("p2", "i2", "SKU_STD", Point3D(0, 0, 1), Orientation3D(1, 1, 1), 120.0, PlacementContext.MAIN_WALL)
        p3 = Placement("p3", "i3", "SKU_STD", Point3D(0, 0, 2), Orientation3D(1, 1, 1), 150.0, PlacementContext.TOP_FILL)

        sg.add_placement(p1)
        sg.add_placement(p2)
        sg.add_placement(p3)

        report = load_engine.compute_loads(sg, self.catalog)
        self.assertTrue(report.is_valid)
        self.assertAlmostEqual(report.total_cargo_weight_kg, 370.0, places=3)
        self.assertAlmostEqual(report.total_floor_load_kg, 370.0, places=3)

        # p3: top-most, 0 upper load
        r3 = report.item_reports["p3"]
        self.assertEqual(r3.accumulated_upper_load_kg, 0.0)
        self.assertEqual(r3.top_pressure_kg_m2, 0.0)

        # p2: carries p3 (150 kg)
        r2 = report.item_reports["p2"]
        self.assertAlmostEqual(r2.accumulated_upper_load_kg, 150.0, places=3)
        self.assertAlmostEqual(r2.top_pressure_kg_m2, 150.0, places=3)

        # p1: carries p2 (120 kg) + p3 (150 kg) = 270 kg
        r1 = report.item_reports["p1"]
        self.assertAlmostEqual(r1.accumulated_upper_load_kg, 270.0, places=3)
        self.assertAlmostEqual(r1.top_pressure_kg_m2, 270.0, places=3)

    def test_load_propagation_fractional_split_pyramid(self):
        """Test pyramid structure where top box splits weight 50/50 onto two base boxes."""
        sg = SupportGraph(container=self.container)
        load_engine = LoadPropagationEngine()

        p_base1 = Placement("b1", "i1", "SKU_STD", Point3D(0, 0, 0), Orientation3D(1, 1, 1), 100.0, PlacementContext.FOUNDATION)
        p_base2 = Placement("b2", "i2", "SKU_STD", Point3D(0, 1, 0), Orientation3D(1, 1, 1), 100.0, PlacementContext.FOUNDATION)
        p_top = Placement("t1", "i3", "SKU_STD", Point3D(0, 0.5, 1), Orientation3D(1, 1, 1), 200.0, PlacementContext.MAIN_WALL)

        sg.add_placement(p_base1)
        sg.add_placement(p_base2)
        sg.add_placement(p_top)

        report = load_engine.compute_loads(sg, self.catalog)
        self.assertTrue(report.is_valid)

        # Each base box carries 50% of top box (100 kg each)
        r_b1 = report.item_reports["b1"]
        r_b2 = report.item_reports["b2"]
        self.assertAlmostEqual(r_b1.accumulated_upper_load_kg, 100.0, places=3)
        self.assertAlmostEqual(r_b2.accumulated_upper_load_kg, 100.0, places=3)

    def test_load_propagation_compression_violations(self):
        """Test bearing limit exceeded and no-top-stacking violations."""
        sg = SupportGraph(container=self.container)
        load_engine = LoadPropagationEngine()

        # Fragile box on floor (allow_stacking_on_top=False)
        p_fragile = Placement("p_fragile", "i1", "SKU_FRAGILE", Point3D(0, 0, 0), Orientation3D(1, 1, 1), 50.0, PlacementContext.FOUNDATION)
        # Heavy box placed on top of fragile box
        p_heavy = Placement("p_heavy", "i2", "SKU_HEAVY", Point3D(0, 0, 1), Orientation3D(1, 1, 1), 800.0, PlacementContext.MAIN_WALL)

        sg.add_placement(p_fragile)
        sg.add_placement(p_heavy)

        report = load_engine.compute_loads(sg, self.catalog)
        self.assertFalse(report.is_valid)
        self.assertTrue(report.item_reports["p_fragile"].is_no_stack_violated)
        self.assertTrue(report.item_reports["p_fragile"].is_bearing_exceeded)

    # =========================================================================
    # 4. Item Stability Tests
    # =========================================================================

    def test_item_stability_self_stable_and_unstable(self):
        """Test self-stable floor placement vs unstable floating/overhanging placements."""
        sg = SupportGraph(container=self.container)
        cg = ContactGraph(container=self.container)
        evaluator = ItemStabilityEvaluator()

        p1 = Placement("p1", "i1", "SKU_STD", Point3D(0, 0, 0), Orientation3D(1, 1, 1), 100.0, PlacementContext.FOUNDATION)
        sg.add_placement(p1)
        cg.add_placement(p1)

        rep1 = evaluator.evaluate_placement(p1, self.sku_std, sg, cg, self.container)
        self.assertEqual(rep1.stability_state, StabilityState.SELF_STABLE)
        self.assertTrue(rep1.is_stable)
        self.assertTrue(rep1.com_projection_in_base)

        # Unstable box with COM outside support base (80% overhang along X)
        p_overhang = Placement("p_overhang", "i2", "SKU_STD", Point3D(0.8, 0, 1), Orientation3D(1, 1, 1), 100.0, PlacementContext.MAIN_WALL)
        sg.add_placement(p_overhang)
        cg.add_placement(p_overhang)

        rep_overhang = evaluator.evaluate_placement(p_overhang, self.sku_std, sg, cg, self.container)
        self.assertEqual(rep_overhang.stability_state, StabilityState.UNSTABLE)
        self.assertFalse(rep_overhang.is_stable)
        self.assertFalse(rep_overhang.com_projection_in_base)

    def test_item_stability_tall_slender_and_lateral_bracing(self):
        """Test tall slender column triggers WARNING when unbraced, and SUPPORTED_STABLE when braced."""
        sg = SupportGraph(container=self.container)
        cg = ContactGraph(container=self.container)
        evaluator = ItemStabilityEvaluator()

        # Tall box alone on floor away from walls (x=2.0, y=1.0)
        p_tall = Placement("p_tall", "i1", "SKU_TALL", Point3D(2.0, 1.0, 0), Orientation3D(0.4, 0.4, 1.6), 60.0, PlacementContext.FOUNDATION)
        sg.add_placement(p_tall)
        cg.add_placement(p_tall)

        rep_unbraced = evaluator.evaluate_placement(p_tall, self.sku_tall, sg, cg, self.container)
        self.assertEqual(rep_unbraced.stability_state, StabilityState.WARNING)
        self.assertGreater(rep_unbraced.slenderness, 2.5)

        # Add neighbor on the right (y=1.4) to laterally brace p_tall
        p_neighbor = Placement("p_neighbor", "i2", "SKU_TALL", Point3D(2.0, 1.4, 0), Orientation3D(0.4, 0.4, 1.6), 60.0, PlacementContext.FOUNDATION)
        sg.add_placement(p_neighbor)
        cg.add_placement(p_neighbor)

        rep_braced = evaluator.evaluate_placement(p_tall, self.sku_tall, sg, cg, self.container)
        self.assertEqual(rep_braced.stability_state, StabilityState.SUPPORTED_STABLE)
        self.assertTrue(rep_braced.has_lateral_bracing)

    # =========================================================================
    # 5. Cluster Stability Tests
    # =========================================================================

    def test_cluster_stability_interlocked_group(self):
        """Test connected cargo group extraction and cluster COM & interlock calculation."""
        cg = ContactGraph(container=self.container)
        evaluator = ClusterStabilityEvaluator()

        # 4 boxes arranged in a 2x2 base on floor
        p1 = Placement("p1", "i1", "SKU_STD", Point3D(0, 0, 0), Orientation3D(1, 1, 1), 100.0, PlacementContext.FOUNDATION)
        p2 = Placement("p2", "i2", "SKU_STD", Point3D(0, 1, 0), Orientation3D(1, 1, 1), 100.0, PlacementContext.FOUNDATION)
        p3 = Placement("p3", "i3", "SKU_STD", Point3D(1, 0, 0), Orientation3D(1, 1, 1), 100.0, PlacementContext.FOUNDATION)
        p4 = Placement("p4", "i4", "SKU_STD", Point3D(1, 1, 0), Orientation3D(1, 1, 1), 100.0, PlacementContext.FOUNDATION)
        placements = [p1, p2, p3, p4]

        for p in placements:
            cg.add_placement(p)

        clusters = evaluator.evaluate_clusters(placements, cg, self.container)
        self.assertEqual(len(clusters), 1)
        c = clusters[0]
        self.assertEqual(len(c.placement_ids), 4)
        self.assertAlmostEqual(c.total_weight_kg, 400.0, places=3)
        self.assertAlmostEqual(c.combined_com.x, 1.0, places=3)
        self.assertAlmostEqual(c.combined_com.y, 1.0, places=3)
        self.assertAlmostEqual(c.combined_com.z, 0.5, places=3)
        self.assertTrue(c.com_in_floor_base)
        self.assertTrue(c.is_stable)

    # =========================================================================
    # 6. Wall Stability Tests
    # =========================================================================

    def test_wall_stability_evaluation(self):
        """Test wall slice analysis, H/T ratio, and rear wall bracing."""
        cg = ContactGraph(container=self.container)
        evaluator = WallStabilityEvaluator()

        # Wall 1: at x=0 (rear wall backed by inner container wall)
        p1 = Placement("p1", "i1", "SKU_STD", Point3D(0, 0, 0), Orientation3D(1, 1, 1), 100.0, PlacementContext.FOUNDATION)
        p2 = Placement("p2", "i2", "SKU_STD", Point3D(0, 0, 1), Orientation3D(1, 1, 1), 100.0, PlacementContext.MAIN_WALL)
        placements = [p1, p2]

        for p in placements:
            cg.add_placement(p)

        wall_reports = evaluator.evaluate_walls(placements, cg, self.container)
        self.assertEqual(len(wall_reports), 1)
        w = wall_reports[0]
        self.assertTrue(w.rear_wall_braced)
        self.assertEqual(w.stability_state, StabilityState.SELF_STABLE)
        self.assertTrue(w.is_stable)

    # =========================================================================
    # 7. Stability Debt System Tests
    # =========================================================================

    def test_stability_debt_lifecycle_and_resolution(self):
        """Test creating temporary debt, resolving via neighbor placement, and zero-debt enforcement."""
        debt_tracker = StabilityDebtTracker(max_active_debts=2, max_debt_lifespan_steps=5)
        sg = SupportGraph(container=self.container)
        cg = ContactGraph(container=self.container)

        p_base = Placement("base", "i0", "SKU_STD", Point3D(0, 0, 0), Orientation3D(1, 1, 1), 100.0, PlacementContext.FOUNDATION)
        sg.add_placement(p_base)
        cg.add_placement(p_base)

        # Step 0: Record p_cond with partial support
        p_cond = Placement("cond1", "i1", "SKU_STD", Point3D(0, 0.4, 1), Orientation3D(1, 1, 1), 100.0, PlacementContext.MAIN_WALL)
        sg.add_placement(p_cond)
        cg.add_placement(p_cond)

        debt = debt_tracker.record_debt(
            placement=p_cond,
            step_index=0,
            cause="PARTIAL_SUPPORT_OVERHANG",
            required_resolution="ADJACENT_LATERAL_SUPPORT",
        )
        self.assertEqual(debt_tracker.active_debt_count, 1)
        self.assertTrue(debt_tracker.has_unresolved_debts)

        # Enforcing zero debt now must raise UnresolvedStabilityDebtError
        with self.assertRaises(UnresolvedStabilityDebtError):
            debt_tracker.enforce_zero_debt("Phase 1 Close")

        # Step 1: Place adjacent box on floor underneath the overhang (y=1.0)
        p_support_adj = Placement("supp_adj", "i2", "SKU_STD", Point3D(0, 1.0, 0), Orientation3D(1, 1, 1), 100.0, PlacementContext.FOUNDATION)
        sg.add_placement(p_support_adj)
        cg.add_placement(p_support_adj)

        # Trigger resolution check
        resolved = debt_tracker.on_placement_committed(
            new_placement=p_support_adj,
            current_step=1,
            support_graph=sg,
            contact_graph=cg,
            cargo_catalog=self.catalog,
            container=self.container,
        )

        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].placement_id, "cond1")
        self.assertEqual(debt_tracker.active_debt_count, 0)
        self.assertFalse(debt_tracker.has_unresolved_debts)

        # Now zero debt enforcement passes smoothly
        debt_tracker.enforce_zero_debt("Phase 1 Close")

    def test_stability_debt_quota_exceeded(self):
        """Test bounded stability debt quota rejects excess debts."""
        tracker = StabilityDebtTracker(max_active_debts=1)
        p1 = Placement("p1", "i1", "SKU_STD", Point3D(0, 0, 0), Orientation3D(1, 1, 1), 100.0, PlacementContext.FOUNDATION)
        p2 = Placement("p2", "i2", "SKU_STD", Point3D(1, 0, 0), Orientation3D(1, 1, 1), 100.0, PlacementContext.FOUNDATION)

        tracker.record_debt(p1, 0, "CAUSE_1")
        self.assertEqual(tracker.active_debt_count, 1)

        with self.assertRaises(StabilityDebtLimitExceeded):
            tracker.record_debt(p2, 1, "CAUSE_2")

    # =========================================================================
    # 8. WorldState & PhysicsStabilityEngine Integration Tests
    # =========================================================================

    def test_world_state_physics_integration_and_atomic_rollback(self):
        """Test WorldState commits update SupportGraph and ContactGraph, and rollback restores them."""
        ws = WorldState(container=self.container, cargo_catalog=[self.sku_std, self.sku_heavy])

        p1 = Placement("p1", "i1", "SKU_STD", Point3D(0, 0, 0), Orientation3D(1, 1, 1), 100.0, PlacementContext.FOUNDATION)
        p2 = Placement("p2", "i2", "SKU_STD", Point3D(0, 0, 1), Orientation3D(1, 1, 1), 100.0, PlacementContext.MAIN_WALL)

        delta1 = ws.commit(p1)
        self.assertEqual(len(ws.support_graph.placements), 1)
        self.assertEqual(len(ws.contact_graph.placements), 1)

        delta2 = ws.commit(p2)
        self.assertEqual(len(ws.support_graph.placements), 2)
        self.assertEqual(len(ws.contact_graph.placements), 2)
        self.assertEqual(ws.support_graph.get_total_support_ratio("p2"), 1.0)

        # Run unified physics evaluator
        physics_engine = PhysicsStabilityEngine()
        phys_report = physics_engine.evaluate_system(
            container=ws.container,
            placements=ws.placements,
            cargo_catalog=ws._cargo_catalog,
            debt_tracker=ws.stability_debt,
        )
        self.assertTrue(phys_report.is_valid)
        self.assertEqual(len(phys_report.compression_violations), 0)
        self.assertEqual(len(phys_report.stability_violations), 0)

        # Test Rollback of p2
        ws.rollback(delta2)
        self.assertEqual(len(ws.placements), 1)
        self.assertEqual(len(ws.support_graph.placements), 1)
        self.assertEqual(len(ws.contact_graph.placements), 1)
        self.assertNotIn("p2", ws.support_graph.placements)
        self.assertNotIn("p2", ws.contact_graph.placements)


if __name__ == "__main__":
    unittest.main()
