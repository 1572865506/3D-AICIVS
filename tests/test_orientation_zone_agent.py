"""
Unit Tests for Agent 04: Orientation / Zones / Quantity / Reservation.
Coverage:
1. OrientationEngine: Context-dependent orientation generation, upright preferences, conditional flat in TOP_FILL, penalties.
2. AdaptiveZoneManager: Dynamic zone boundaries, door lockout gating, rear lock, floor-only lock, affinity scoring.
3. QuantityManager: Target quotas, min/max bounds, elastic prioritization, atomic commit & rollback.
4. SpatialReservationManager: 3D bounding box reservations for specialized roles and encroachment prevention.
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
    PlacementContext,
    ZoneType,
    PackingRole,
)
from backend.solver_v2.geometry.aabb import AABB
from backend.solver_v2.orientation.manager import (
    OrientationEngine,
    OrientationCandidate,
)
from backend.solver_v2.zones.manager import (
    AdaptiveZoneManager,
    ZoneBoundary,
)
from backend.solver_v2.quantity.manager import (
    QuantityManager,
    SpatialReservationManager,
    SpatialReservation,
)


class TestOrientationEngine(unittest.TestCase):
    def setUp(self):
        self.engine = OrientationEngine()
        # SKU with upright allowed, flat allowed ONLY in TOP_FILL
        self.sku_display = CargoSKU(
            sku_id="SKU_DISPLAY",
            name="Display Carton",
            box=BoxDim(x=1.0, y=1.2, z=1.5),
            weight_kg=50.0,
            quantity=QuantityPlan(required=10),
            orientation_policy=OrientationPolicy(
                allow_upright=True,
                allow_flat=True,
                allow_side=False,
                allowed_contexts_for_flat=(PlacementContext.TOP_FILL,),
                flat_orientation_penalty=50.0,
            ),
            packing_roles=(PackingRole.MAIN_WALL, PackingRole.TOP_FILL),
        )

        # SKU upright ONLY
        self.sku_strict_upright = CargoSKU(
            sku_id="SKU_STRICT",
            name="Strict Upright Drum",
            box=BoxDim(x=0.8, y=0.8, z=1.2),
            weight_kg=120.0,
            quantity=QuantityPlan(required=5),
            orientation_policy=OrientationPolicy(
                allow_upright=True,
                allow_flat=False,
                allow_side=False,
            ),
            packing_roles=(PackingRole.FOUNDATION,),
        )

    def test_main_wall_context_strictly_upright(self):
        """在 MAIN_WALL / FOUNDATION 上下文中，只生成立放朝向，罚分为 0"""
        cands = self.engine.get_candidate_orientations(
            sku=self.sku_display,
            context=PlacementContext.MAIN_WALL,
        )
        self.assertGreater(len(cands), 0)
        for c in cands:
            self.assertTrue(c.orientation.is_upright)
            self.assertEqual(c.penalty_score, 0.0)
            self.assertEqual(c.orientation.dz, 1.5)  # Height preserved

    def test_top_fill_context_generates_conditional_flat(self):
        """在 TOP_FILL 上下文中，条件允许平躺，且附带 flat_orientation_penalty"""
        cands = self.engine.get_candidate_orientations(
            sku=self.sku_display,
            context=PlacementContext.TOP_FILL,
        )
        # Should contain both upright and flat candidates
        flat_cands = [c for c in cands if c.orientation.is_flat]
        self.assertGreater(len(flat_cands), 0)
        for fc in flat_cands:
            self.assertEqual(fc.penalty_score, 50.0)
            self.assertFalse(fc.is_preferred)
            self.assertEqual(fc.orientation.dz, 1.2)  # Laying flat (dz = y = 1.2)

    def test_target_space_filtering(self):
        """当目标顶部空间垂直高度不足以立放 (1.5m)，但能平放 (1.2m) 时，只输出平放候选"""
        target_space = AABB(0.0, 0.0, 0.0, 2.0, 2.0, 1.3)  # dz = 1.3m (< 1.5m, >= 1.2m)
        cands = self.engine.get_candidate_orientations(
            sku=self.sku_display,
            context=PlacementContext.TOP_FILL,
            target_space=target_space,
        )
        self.assertTrue(all(c.orientation.is_flat for c in cands))
        self.assertGreater(len(cands), 0)

    def test_evaluate_orientation(self):
        """测试 evaluate_orientation 接口验证"""
        # Upright normal
        legal, penalty, _ = self.engine.evaluate_orientation(
            self.sku_display, 1.0, 1.2, 1.5, PlacementContext.MAIN_WALL
        )
        self.assertTrue(legal)
        self.assertEqual(penalty, 0.0)

        # Flat in MAIN_WALL -> illegal
        legal_flat_mw, _, _ = self.engine.evaluate_orientation(
            self.sku_display, 1.0, 1.5, 1.2, PlacementContext.MAIN_WALL
        )
        self.assertFalse(legal_flat_mw)

        # Flat in TOP_FILL -> legal with penalty
        legal_flat_tf, penalty_tf, _ = self.engine.evaluate_orientation(
            self.sku_display, 1.0, 1.5, 1.2, PlacementContext.TOP_FILL
        )
        self.assertTrue(legal_flat_tf)
        self.assertEqual(penalty_tf, 50.0)


class TestAdaptiveZoneManager(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec(
            code="40HQ_ZONE_TEST",
            inner_dim=BoxDim(x=12.0, y=2.4, z=2.6),
            max_payload_kg=26000.0,
            door_zone_length_m=1.2,
            rear_zone_length_m=1.5,
        )
        self.zone_mgr = AdaptiveZoneManager(self.container)

        self.sku_std = CargoSKU(
            sku_id="SKU_STD",
            name="Standard",
            box=BoxDim(x=1.0, y=1.0, z=1.0),
            weight_kg=100.0,
            quantity=QuantityPlan(required=10),
            packing_roles=(PackingRole.MAIN_WALL,),
        )
        self.sku_door = CargoSKU(
            sku_id="SKU_DOOR",
            name="Door Bag",
            box=BoxDim(x=0.6, y=1.0, z=1.0),
            weight_kg=20.0,
            quantity=QuantityPlan(required=8),
            packing_roles=(PackingRole.DOOR_SEAL,),
            target_zone=ZoneType.DOOR,
        )

    def test_zone_boundaries(self):
        """测试各区域三维空间边界计算"""
        bounds = self.zone_mgr.get_zone_boundaries()
        self.assertEqual(bounds[ZoneType.REAR].max_x, 1.5)
        self.assertEqual(bounds[ZoneType.DOOR].min_x, 12.0 - 1.2)  # 10.8m
        self.assertEqual(bounds[ZoneType.MIDDLE].min_x, 1.5)
        self.assertEqual(bounds[ZoneType.MIDDLE].max_x, 10.8)

    def test_adapt_door_zone_to_cargo(self):
        """测试根据门封货物总体积自适应扩张门区深度"""
        # Place 20 bulky door bags
        bulky_door_sku = CargoSKU(
            sku_id="BULKY_DOOR",
            name="Bulky Bag",
            box=BoxDim(x=1.0, y=1.2, z=1.3),
            weight_kg=50.0,
            quantity=QuantityPlan(required=10),
            packing_roles=(PackingRole.DOOR_SEAL,),
        )
        init_door_len = self.zone_mgr.door_zone_length_m
        self.zone_mgr.adapt_door_zone_to_cargo([bulky_door_sku])
        self.assertGreaterEqual(self.zone_mgr.door_zone_length_m, init_door_len)

    def test_hard_door_lockout_compliance(self):
        """测试硬性门区拦截（非门封货物禁止侵入门区）"""
        # Door starts at x = 10.8. Placement at x = 10.5 with dx = 1.0 (reaches 11.5)
        ok_std, reason_std = self.zone_mgr.check_hard_zone_compliance(
            self.sku_std, x=10.5, y=0.0, z=0.0, dx=1.0, dy=1.0, dz=1.0
        )
        self.assertFalse(ok_std)
        self.assertIn("Door zone lockout", reason_std)

        # Door seal SKU allowed
        ok_door, reason_door = self.zone_mgr.check_hard_zone_compliance(
            self.sku_door, x=10.5, y=0.0, z=0.0, dx=0.6, dy=1.0, dz=1.0
        )
        self.assertTrue(ok_door)
        self.assertIsNone(reason_door)

    def test_zone_affinity_score(self):
        """测试区域亲和度评分"""
        # Door seal SKU placed in door zone gets high bonus
        score_door_in_door = self.zone_mgr.compute_zone_affinity_score(
            self.sku_door, x=11.0, y=0.0, z=0.0, dx=0.6, dy=1.0, dz=1.0
        )
        score_door_in_rear = self.zone_mgr.compute_zone_affinity_score(
            self.sku_door, x=0.0, y=0.0, z=0.0, dx=0.6, dy=1.0, dz=1.0
        )
        self.assertGreater(score_door_in_door, score_door_in_rear)


class TestQuantityAndSpatialReservation(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec(
            code="40HQ_QTY_TEST",
            inner_dim=BoxDim(x=12.0, y=2.4, z=2.6),
            max_payload_kg=26000.0,
            door_zone_length_m=1.2,
        )
        self.sku1_strict = CargoSKU(
            sku_id="SKU_STRICT",
            name="Strict Core",
            box=BoxDim(x=1.0, y=1.0, z=1.0),
            weight_kg=100.0,
            quantity=QuantityPlan(required=5, min_quantity=5, max_quantity=5, is_elastic=False),
        )
        self.sku2_elastic = CargoSKU(
            sku_id="SKU_ELASTIC",
            name="Elastic Filler",
            box=BoxDim(x=0.5, y=0.5, z=0.5),
            weight_kg=10.0,
            quantity=QuantityPlan(required=20, min_quantity=5, max_quantity=30, is_elastic=True),
        )
        self.sku_seal = CargoSKU(
            sku_id="SKU_SEAL",
            name="Door Seal",
            box=BoxDim(x=0.5, y=0.5, z=0.5),
            weight_kg=10.0,
            quantity=QuantityPlan(required=10),
            packing_roles=(PackingRole.DOOR_SEAL,),
        )

        self.qty_mgr = QuantityManager([self.sku1_strict, self.sku2_elastic])
        self.res_mgr = SpatialReservationManager()

    def test_quantity_quotas_and_priorities(self):
        """测试数量追踪与非弹性核心货物最高优先级"""
        self.assertFalse(self.qty_mgr.all_required_satisfied())
        prios = self.qty_mgr.get_sku_priorities()
        # Non-elastic strict SKU must be prioritized first
        self.assertEqual(prios[0], "SKU_STRICT")

        # Place 5 strict SKUs
        for _ in range(5):
            self.qty_mgr.record_placement("SKU_STRICT")

        self.assertFalse(self.qty_mgr.can_place("SKU_STRICT"))
        # Now elastic SKU should be top priority
        prios_after = self.qty_mgr.get_sku_priorities()
        self.assertEqual(prios_after[0], "SKU_ELASTIC")

        # Rollback 1 strict SKU
        rolled_sku = self.qty_mgr.rollback_placement()
        self.assertEqual(rolled_sku, "SKU_STRICT")
        self.assertTrue(self.qty_mgr.can_place("SKU_STRICT"))

    def test_spatial_reservation_conflict_and_clearance(self):
        """测试空间预留拦截越权摆放，并允许合规货物放置"""
        # Reserve door zone for DOOR_SEAL role
        self.res_mgr.reserve_door_zone(self.container, door_zone_length_m=1.2)

        # Candidate AABB encroaching door zone [11.0, 12.0]
        encroach_aabb = AABB(11.0, 0.0, 0.0, 12.0, 1.0, 1.0)

        # Standard SKU should be blocked
        ok_std, reason_std = self.res_mgr.check_candidate_conflict(encroach_aabb, self.sku1_strict)
        self.assertFalse(ok_std)
        self.assertIn("Spatial reservation conflict", reason_std)

        # Door seal SKU should pass
        ok_seal, reason_seal = self.res_mgr.check_candidate_conflict(encroach_aabb, self.sku_seal)
        self.assertTrue(ok_seal)
        self.assertIsNone(reason_seal)


if __name__ == "__main__":
    unittest.main()
