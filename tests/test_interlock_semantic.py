"""
Unit tests for SKU semantic interlock and physical load propagation.
Tests:
1. Floor-rooted stack: must_be_on_floor + max_stack_layers allows same-SKU stacking, rejects foreign support.
2. Top-stacking disambiguation: allow_stacking_on_top=False + stack_on_self=True allows same-SKU, rejects foreign cargo.
3. Multi-layer load propagation: Accumulated weight through vertical DAG accurately captures bearing exceedance.
4. Orientation mutual exclusion: flat_only strictly disables upright rotation.
"""
import unittest
from backend.solver_v2.domain.models import (
    ContainerSpec,
    BoxDim,
    CargoSKU,
    QuantityPlan,
    StackingPolicy,
    OrientationPolicy,
    Placement,
    Point3D,
    Orientation3D,
    PlacementContext,
)
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from backend.solver_v2.api.adapter import InputNormalizer


class TestInterlockSemantic(unittest.TestCase):

    def test_orientation_mutual_exclusion(self):
        # flat_only disables upright
        ori1 = InputNormalizer.parse_orientation_policy({"allowedOrientation": "flat_only"})
        self.assertFalse(ori1.allow_upright)
        self.assertTrue(ori1.allow_flat)

        # keepUpright strictly disables flat & side
        ori2 = InputNormalizer.parse_orientation_policy({
            "allowedOrientation": "any",
            "keepUpright": True,
        })
        self.assertTrue(ori2.allow_upright)
        self.assertFalse(ori2.allow_flat)
        self.assertFalse(ori2.allow_side)

    def test_stacking_policy_interlock_synthesis(self):
        # allowStackingOnTop=False + maxStackLayers=3 synthesizes stack_on_self=True
        policy1 = InputNormalizer.parse_stacking_policy({
            "allowStackingOnTop": False,
            "maxStackLayers": 3,
        })
        self.assertFalse(policy1.allow_stacking_on_top)
        self.assertTrue(policy1.stack_on_self)

        # allowStackingOnTop=False + maxStackLayers=1 synthesizes absolute cap (stack_on_self=False)
        policy2 = InputNormalizer.parse_stacking_policy({
            "allowStackingOnTop": False,
            "maxStackLayers": 1,
        })
        self.assertFalse(policy2.allow_stacking_on_top)
        self.assertFalse(policy2.stack_on_self)

    def test_floor_rooted_same_sku_stacking(self):
        container = ContainerSpec(code="C1", inner_dim=BoxDim(5.0, 2.0, 2.5), max_payload_kg=10000.0)
        sku_a = CargoSKU(
            sku_id="SKU_FLOOR",
            name="落地重货",
            box=BoxDim(1.0, 1.0, 0.8),
            weight_kg=100.0,
            quantity=QuantityPlan(required=2),
            stacking_policy=StackingPolicy(must_be_on_floor=True, max_stack_layers=2),
        )

        p1 = Placement(
            placement_id="p1", instance_id="i1", sku_id="SKU_FLOOR",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(1.0, 1.0, 0.8),
            weight_kg=100.0, context=PlacementContext.MAIN_WALL
        )
        p2 = Placement(
            placement_id="p2", instance_id="i2", sku_id="SKU_FLOOR",
            position=Point3D(0.0, 0.0, 0.8),
            orientation=Orientation3D(1.0, 1.0, 0.8),
            weight_kg=100.0, context=PlacementContext.MAIN_WALL
        )

        res = IndependentGlobalValidator.validate(container, [p1, p2], [sku_a])
        self.assertTrue(res.is_valid, f"Floor-rooted same SKU stacking should pass, got: {res.violations}")

    def test_top_stacking_disambiguation(self):
        container = ContainerSpec(code="C1", inner_dim=BoxDim(5.0, 2.0, 2.5), max_payload_kg=10000.0)
        sku_a = CargoSKU(
            sku_id="SKU_NO_FOREIGN",
            name="不准杂货压但自叠2层",
            box=BoxDim(1.0, 1.0, 0.8),
            weight_kg=50.0,
            quantity=QuantityPlan(required=2),
            stacking_policy=StackingPolicy(allow_stacking_on_top=False, stack_on_self=True, max_stack_layers=2),
        )
        sku_b = CargoSKU(
            sku_id="SKU_FOREIGN",
            name="外来杂货",
            box=BoxDim(1.0, 1.0, 0.5),
            weight_kg=20.0,
            quantity=QuantityPlan(required=1),
        )

        p1 = Placement(
            placement_id="p1", instance_id="i1", sku_id="SKU_NO_FOREIGN",
            position=Point3D(0.0, 0.0, 0.0),
            orientation=Orientation3D(1.0, 1.0, 0.8),
            weight_kg=50.0, context=PlacementContext.MAIN_WALL
        )
        p2_same = Placement(
            placement_id="p2", instance_id="i2", sku_id="SKU_NO_FOREIGN",
            position=Point3D(0.0, 0.0, 0.8),
            orientation=Orientation3D(1.0, 1.0, 0.8),
            weight_kg=50.0, context=PlacementContext.MAIN_WALL
        )

        # Same SKU on top -> PASS
        res_same = IndependentGlobalValidator.validate(container, [p1, p2_same], [sku_a])
        self.assertTrue(res_same.is_valid, f"Same SKU on top should be permitted when stack_on_self=True, got: {res_same.violations}")

        # Foreign SKU on top -> REJECT
        p2_foreign = Placement(
            placement_id="p2", instance_id="i2", sku_id="SKU_FOREIGN",
            position=Point3D(0.0, 0.0, 0.8),
            orientation=Orientation3D(1.0, 1.0, 0.5),
            weight_kg=20.0, context=PlacementContext.MAIN_WALL
        )
        res_foreign = IndependentGlobalValidator.validate(container, [p1, p2_foreign], [sku_a, sku_b])
        self.assertFalse(res_foreign.is_valid)
        self.assertTrue(any(v.violation_type.value == "NO_TOP_STACK_VIOLATION" for v in res_foreign.violations))

    def test_multi_layer_load_propagation_captures_overweight(self):
        container = ContainerSpec(code="C1", inner_dim=BoxDim(5.0, 2.0, 3.0), max_payload_kg=10000.0)
        sku = CargoSKU(
            sku_id="SKU_BEAR",
            name="承重测试箱",
            box=BoxDim(1.0, 1.0, 0.5),
            weight_kg=15.0,
            quantity=QuantityPlan(required=4),
            stacking_policy=StackingPolicy(max_bearing_kg=30.0, max_stack_layers=4),
        )

        p1 = Placement("p1", "i1", "SKU_BEAR", Point3D(0, 0, 0.0), Orientation3D(1, 1, 0.5), 15.0, PlacementContext.MAIN_WALL)
        p2 = Placement("p2", "i2", "SKU_BEAR", Point3D(0, 0, 0.5), Orientation3D(1, 1, 0.5), 15.0, PlacementContext.MAIN_WALL)
        p3 = Placement("p3", "i3", "SKU_BEAR", Point3D(0, 0, 1.0), Orientation3D(1, 1, 0.5), 15.0, PlacementContext.MAIN_WALL)
        p4 = Placement("p4", "i4", "SKU_BEAR", Point3D(0, 0, 1.5), Orientation3D(1, 1, 0.5), 15.0, PlacementContext.MAIN_WALL)

        res = IndependentGlobalValidator.validate(container, [p1, p2, p3, p4], [sku])
        self.assertFalse(res.is_valid, "Multi-layer load propagation should reject 45kg load on 30kg bearing limit")
        bearing_viols = [v for v in res.violations if v.violation_type.value == "BEARING_EXCEEDED"]
        self.assertGreater(len(bearing_viols), 0)
        self.assertAlmostEqual(bearing_viols[0].extra_data["upper_weight_kg"], 45.0, places=2)


if __name__ == "__main__":
    unittest.main()
