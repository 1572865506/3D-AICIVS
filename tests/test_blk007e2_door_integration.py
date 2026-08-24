import dataclasses
import unittest

from backend.api.adapters.layout_adapter import LayoutAdapter
from backend.solver_v2.domain.models import Orientation3D, Placement, PlacementContext, Point3D
from backend.solver_v2.loading.planner import LoadingSequencePlanner
from backend.solver_v2.solver.baseline_solver import SolverSolution, SolverTelemetry
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from run_blk003_benchmark import load_dataset
from src.solver.integration.door import (
    DoorConstraintAdapter, DoorConstraintFilter, DoorIntegratedSolver,
    DoorPlacementValidator, DoorWallCommitter, ReservedRegionManager,
)


DATASET = "devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json"


class EmptyFrozenSolver:
    def solve(self, container, cargo_list, options=None):
        validation = IndependentGlobalValidator.validate(container, [], cargo_list)
        return SolverSolution(
            "SUCCESS", container, [], 0, sum(s.quantity.required for s in cargo_list),
            0.0, 0.0, validation, SolverTelemetry(),
        )


class TestBLK007E2DoorIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container, cls.cargo = load_dataset(DATASET)
        cls.prepared = DoorConstraintAdapter().prepare(cls.container, cls.cargo)

    def test_door_integration_001_wall_enters_final_layout(self):
        solution = DoorIntegratedSolver(EmptyFrozenSolver()).solve(self.container, self.cargo)
        expected = {p.placement_id for p in self.prepared.door_context.anchor_placements}
        self.assertEqual({p.placement_id for p in solution.placements}, expected)
        self.assertEqual(len(solution.placements), 231)

    def test_door_integration_002_main_cargo_rejected_from_zone(self):
        anchor = self.prepared.door_context.anchor_placements[0]
        ordinary = dataclasses.replace(anchor, placement_id="ordinary", sku_id="SKU-05")
        result = ReservedRegionManager(self.prepared.door_context.blocked_area).validate(ordinary)
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "DOOR_ZONE_RESERVED")

    def test_door_integration_003_orientation_is_preserved(self):
        self.assertEqual(set(self.prepared.door_context.forced_orientation.values()), {"LONG_EDGE_FORWARD"})
        plan = DoorConstraintAdapter().engine.plan(self.container, self.cargo)
        self.assertEqual({p.orientation for p in plan.wall.placements}, {"LONG_EDGE_FORWARD"})

    def test_door_integration_004_full_manifest_forms_requested_wall(self):
        context = self.prepared.door_context
        self.assertEqual(context.door_anchor.wall_id, "DOOR_WALL_001")
        self.assertEqual(len(context.anchor_placements), 231)
        self.assertEqual({p.sku_id for p in context.anchor_placements}, {"SKU-02", "SKU-14"})
        self.assertAlmostEqual(context.blocked_area.x1, 11.429)
        self.assertAlmostEqual(context.blocked_area.x2, 12.032)

    def test_solver_space_is_cropped_before_frozen_solver(self):
        self.assertAlmostEqual(self.prepared.solver_container.Lx, 11.429)
        self.assertGreater(self.prepared.solver_container.Lx, 10.832)
        self.assertEqual(self.prepared.original_container.Lx, 12.032)

    def test_reserved_inventory_is_subtracted_not_mutated(self):
        original_04 = next(s for s in self.cargo if s.sku_id == "SKU-04")
        adapted_04 = next(s for s in self.prepared.solver_cargo if s.sku_id == "SKU-04")
        original_14 = next(s for s in self.cargo if s.sku_id == "SKU-14")
        adapted_14 = next(s for s in self.prepared.solver_cargo if s.sku_id == "SKU-14")
        self.assertEqual(original_04.quantity.required, 100)
        self.assertEqual(adapted_04.quantity.required, 100)
        self.assertEqual(original_14.quantity.required, 674)
        self.assertEqual(adapted_14.quantity.required, 450)

    def test_door_wall_is_locked_against_mutation(self):
        locked = frozenset(p.placement_id for p in self.prepared.door_context.anchor_placements)
        result = DoorPlacementValidator.validate_locked_operation(next(iter(locked)), locked, "ROTATE")
        self.assertFalse(result.valid)
        self.assertEqual(result.reasons, ("LOCKED_DOOR_WALL",))

    def test_constraint_filter_precedes_core_collision(self):
        anchor = self.prepared.door_context.anchor_placements[0]
        ordinary = dataclasses.replace(anchor, placement_id="candidate", sku_id="SKU-05")
        valid, reason = DoorConstraintFilter(self.prepared.door_context).evaluate(ordinary)
        self.assertFalse(valid)
        self.assertEqual(reason, "DOOR_ZONE_RESERVED")

    def test_final_global_validator_is_mandatory_and_valid(self):
        solution = DoorIntegratedSolver(EmptyFrozenSolver()).solve(self.container, self.cargo)
        self.assertTrue(solution.validation_result.is_valid)
        self.assertEqual(solution.status, "SUCCESS")

    def test_loading_sequence_contains_door_wall_build(self):
        solution = DoorIntegratedSolver(EmptyFrozenSolver()).solve(self.container, self.cargo)
        plan = LoadingSequencePlanner(self.container, self.cargo).plan(solution.placements)
        ids = {pid for step in plan.steps for pid in step.placement_ids}
        self.assertTrue(all(p.placement_id in ids for p in solution.placements))
        self.assertTrue(all(step.phase == "DOOR_SEAL" for step in plan.steps))

    def test_layout_contract_adds_role_without_removing_context(self):
        solution = DoorIntegratedSolver(EmptyFrozenSolver()).solve(self.container, self.cargo)
        plan = LoadingSequencePlanner(self.container, self.cargo).plan(solution.placements)
        rows = LayoutAdapter.cargo(solution.placements, self.cargo, self.container, plan, [])
        self.assertTrue(all(row["role"] == "DOOR_WALL" for row in rows))
        self.assertTrue(all(row["context"] == "DOOR_SEAL" for row in rows))

    def test_topfill_cannot_enter_reserved_zone(self):
        anchor = self.prepared.door_context.anchor_placements[0]
        top = dataclasses.replace(anchor, placement_id="top", context=PlacementContext.TOP_FILL)
        result = ReservedRegionManager(self.prepared.door_context.blocked_area).validate(top, "TOP_FILL")
        self.assertFalse(result.valid)


if __name__ == "__main__":
    unittest.main()
