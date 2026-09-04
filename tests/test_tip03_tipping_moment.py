"""
Tests for TIP-03: Tipping Moment Detection, Repair and Gate 11 Validation.
"""
import unittest

from backend.solver_v2.domain.models import (
    BoxDim,
    CargoSKU,
    ContainerSpec,
    QuantityPlan,
    UniversalCargoTensor,
)
from backend.solver_v2.solver.unified_solver import UnifiedSolver
from backend.solver_v2.stability.tipping_moment import TippingMomentAnalyzer
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from backend.solver_v2.validation.types import ViolationType


class TestTIP03TippingMoment(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec(
            code="40HQ",
            inner_dim=BoxDim(12.024, 2.350, 2.690),
            max_payload_kg=26000.0,
        )
        self.solver = UnifiedSolver(self.container)
        self.validator = IndependentGlobalValidator()
        self.analyzer = TippingMomentAnalyzer(
            container_length=self.container.inner_dim.x,
            container_width=self.container.inner_dim.y,
            container_height=self.container.inner_dim.z,
            decel_g=0.5,
            min_safety_factor=1.5,
        )

    def test_forward_support_near_door_passes(self):
        """A box placed directly against the door (x + dx = cL) has infinite SF and is safe."""
        p = {"x": 11.524, "y": 0.0, "z": 0.0, "dx": 0.5, "dy": 0.5, "dz": 1.0, "sku_id": "SKU1"}
        sf = self.analyzer.compute_safety_factor(p, [p])
        self.assertEqual(sf, float("inf"))
        self.assertTrue(self.analyzer.has_forward_support(p, [p]))

    def test_forward_support_with_front_neighbor_passes(self):
        """A tall box with a neighbor box directly in front (+X) is fully supported and safe."""
        p_tall = {"x": 2.0, "y": 0.0, "z": 0.0, "dx": 0.4, "dy": 0.5, "dz": 1.2, "sku_id": "SKU_TALL"}
        p_front = {"x": 2.4, "y": 0.0, "z": 0.0, "dx": 0.5, "dy": 0.5, "dz": 1.2, "sku_id": "SKU_FRONT"}
        placements = [p_tall, p_front]
        self.assertTrue(self.analyzer.has_forward_support(p_tall, placements))
        self.assertEqual(self.analyzer.compute_safety_factor(p_tall, placements), float("inf"))

    def test_unsupported_tall_box_fails_tipping_moment(self):
        """
        A tall box dx=0.4, dz=1.2 without forward neighbor.
        SF = 2.0 * dx / dz = 2.0 * 0.4 / 1.2 = 0.67 < 1.5.
        Must be marked unsafe by analyzer and flagged by Gate 11 validator.
        """
        p_tall = {
            "placement_id": "p1",
            "x": 2.0, "y": 0.0, "z": 0.0,
            "dx": 0.4, "dy": 0.5, "dz": 1.2,
            "weight_kg": 15.0,
            "sku_id": "SKU_TALL"
        }
        sf = self.analyzer.compute_safety_factor(p_tall, [p_tall])
        self.assertAlmostEqual(sf, 0.666666, places=4)
        self.assertLess(sf, 1.5)

        sku = CargoSKU(
            sku_id="SKU_TALL",
            name="Tall Box",
            box=BoxDim(0.40, 0.50, 1.20),
            weight_kg=15.0,
            quantity=QuantityPlan(required=1),
        )
        res = self.validator.validate(self.container, [p_tall], [sku])
        self.assertFalse(res.is_valid)
        unstable_viols = [v for v in res.violations if v.violation_type == ViolationType.UNSTABLE_PLACEMENT]
        self.assertGreater(len(unstable_viols), 0)

    def test_audit_and_repair_is_immutable(self):
        """
        PASS 5 immutability contract: audit_and_repair NEVER mutates, reorients or deletes placements.
        """
        sku = CargoSKU(
            sku_id="SKU_TALL",
            name="Tall Box",
            box=BoxDim(1.00, 0.50, 0.40),
            weight_kg=15.0,
            quantity=QuantityPlan(required=1),
        )
        p_tall = {
            "placement_id": "p1",
            "x": 2.0, "y": 0.0, "z": 0.0,
            "dx": 0.4, "dy": 0.5, "dz": 1.0,
            "weight_kg": 15.0,
            "sku_id": "SKU_TALL",
            "orientation": "UPRIGHT",
        }
        raw_placements = [p_tall]
        tensors = self.solver._convert_cargo_skus_to_tensors([sku])
        repaired = self.analyzer.audit_and_repair(
            placements=raw_placements,
            cargo_list=tensors,
            remaining_qty={"SKU_TALL": 0},
        )
        # Placement count and coordinates must be strictly identical (Append-Only Immutability)
        self.assertEqual(len(repaired), 1)
        self.assertEqual(repaired[0]["dx"], 0.4)
        self.assertEqual(repaired[0]["dz"], 1.0)
        self.assertFalse(self.analyzer.is_placement_stable_against_tipping(repaired[0], repaired))


    def test_end_to_end_solving_with_pass5_passes_validator(self):
        """End to end solve must pass Gate 11 with 0 unstable placement violations."""
        sku = CargoSKU(
            sku_id="SKU_BOX",
            name="General Box",
            box=BoxDim(0.40, 0.30, 0.40),
            weight_kg=10.0,
            quantity=QuantityPlan(required=60),
        )
        solution = self.solver.solve([sku])
        self.assertTrue(solution.validation_result.is_valid, f"Violations: {solution.validation_result.violations}")
        self.assertGreater(solution.placed_count, 0)


    def test_transactional_state_kernel_immutability(self):
        """Validates that LayoutState.spawn_child creates a new immutable state without mutating parent."""
        from backend.solver_v2.solver.unified_solver import LayoutState, PlacementAction, FastActionGate, LexicographicObjective

        sku = CargoSKU(
            sku_id="SKU_BASE",
            name="Base Box",
            box=BoxDim(0.50, 0.40, 0.30),
            weight_kg=10.0,
            quantity=QuantityPlan(required=10),
        )
        tensors = self.solver._convert_cargo_skus_to_tensors([sku])
        s0 = LayoutState.create_initial_state(self.container, tensors, door_boundary_x=10.8)
        self.assertEqual(len(s0.placements), 0)
        self.assertEqual(s0.remaining_qty["SKU_BASE"], 10)

        action = PlacementAction(
            action_id="act_1",
            source_proposer="INTERIOR",
            placements=({
                "sku_id": "SKU_BASE",
                "x": 0.0, "y": 0.0, "z": 0.0,
                "dx": 0.50, "dy": 0.40, "dz": 0.30,
                "weight_kg": 10.0,
                "orientation": "UPRIGHT",
                "step": 1,
            },),
            consumed_quantities={"SKU_BASE": 1},
            metadata={"stability_tier": 2, "continuity": 1.0, "flatness": 1.0},
        )

        self.assertTrue(FastActionGate.is_action_feasible(s0, action))
        s1 = s0.spawn_child(action)

        # Immutability assertion: s0 unchanged, s1 evolved
        self.assertEqual(len(s0.placements), 0)
        self.assertEqual(s0.remaining_qty["SKU_BASE"], 10)
        self.assertEqual(len(s1.placements), 1)
        self.assertEqual(s1.remaining_qty["SKU_BASE"], 9)
        self.assertEqual(s1.current_x, 0.50)

        rank = LexicographicObjective.rank_key(action)
        self.assertEqual(rank[0], 2)  # stability_tier


if __name__ == "__main__":
    unittest.main()

