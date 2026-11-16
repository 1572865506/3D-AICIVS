import unittest

from backend.api.adapters.layout_adapter import LayoutAdapter
from backend.solver_v2.loading.planner import LoadingSequencePlanner
from backend.solver_v2.solver.baseline_solver import SolverSolution, SolverTelemetry
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from run_blk003_benchmark import load_dataset
from src.cargo.intelligence import CargoConstraintAdapter
from src.optimization.direction import LoadingDirectionEngine, TransportStabilityAnalyzer
from src.solver.integration.door import DoorIntegratedSolver


DATASET = "devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json"


class EmptyFrozenSolver:
    def solve(self, container, cargo_list, options=None):
        validation = IndependentGlobalValidator.validate(container, [], cargo_list)
        return SolverSolution("SUCCESS", container, [], 0, sum(s.quantity.required for s in cargo_list),
                              0, 0, validation, SolverTelemetry())


class TestBLK007F5LoadingDirection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container, cls.cargo = load_dataset(DATASET)
        cls.intelligence = CargoConstraintAdapter().prepare(cls.cargo)
        cls.engine = LoadingDirectionEngine()
        cls.plan = cls.engine.plan(cls.container, cls.cargo, cls.intelligence)
        cls.solver = (DoorIntegratedSolver(
            EmptyFrozenSolver(), enable_cargo_walls=True, enable_wall_optimization=True
        ).with_direction_strategy().with_layer_optimization().with_topfill_optimization())
        cls.solution = cls.solver.solve(cls.container, cls.cargo)

    def test_direction_001_display_prefers_short_edge_forward(self):
        for sku_id in ("SKU-02", "SKU-03", "SKU-04", "SKU-14"):
            choice = next(x for x in self.plan.selected_candidates if x.sku == sku_id)
            self.assertEqual(choice.facing, "SHORT_EDGE_FORWARD")
            self.assertLessEqual(choice.forward_depth, choice.wall_width)

    def test_direction_002_actual_display_wall_is_directionally_continuous(self):
        actual = self.solver.last_direction_plan.actual_validation
        self.assertTrue(actual["display_direction_valid"])
        self.assertEqual(actual["display_non_top_count"], actual["display_short_edge_forward_count"])
        self.assertGreater(actual["display_non_top_count"], 0)

    def test_direction_003_door_open_display_requires_self_stable_deep_base(self):
        sku = next(x for x in self.cargo if x.sku_id == "SKU-02")
        profile = self.intelligence.profiles[sku.sku_id]
        self.assertEqual(self.engine.door.evaluate(profile, "SHORT_EDGE_FORWARD", "DOOR_OPEN_BLOCKING_WALL"),
                         (False, "DOOR_OPEN_BASE_DEPTH_INSUFFICIENT"))
        self.assertEqual(self.engine.door.evaluate(profile, "LONG_EDGE_FORWARD", "DOOR_OPEN_BLOCKING_WALL"), (True, None))
        door = [p for p in self.solution.placements if p.placement_id.startswith("door_pre_")]
        self.assertTrue(door)
        self.assertTrue(all(p.orientation.dx >= p.orientation.dy for p in door))
        self.assertTrue(self.solver.last_transport_validation.door_open_valid)

    def test_direction_004_short_edge_has_lower_transport_risk(self):
        sku = next(x for x in self.cargo if x.sku_id == "SKU-02")
        analyzer = TransportStabilityAnalyzer()
        short = analyzer.analyze(sku, "SHORT_EDGE_FORWARD")
        long = analyzer.analyze(sku, "LONG_EDGE_FORWARD")
        self.assertGreater(short.transport_score, long.transport_score)

    def test_direction_005_real_case_preserves_quality_and_physics(self):
        self.assertTrue(self.solution.validation_result.is_valid)
        self.assertGreaterEqual(round(self.solution.volume_utilization_pct, 4), 71.5044)
        self.assertTrue(self.solver.last_diagnostics.loading_direction_ready)
        self.assertTrue(self.solver.last_direction_plan.actual_validation["wall_fingerprint_unchanged"])

    def test_layout_contains_direction_projection(self):
        sequence = LoadingSequencePlanner(self.container, self.cargo).plan(self.solution.placements)
        rows = LayoutAdapter.cargo(self.solution.placements, self.cargo, self.container, sequence, [])
        required = {"facing", "direction_reason", "transport_score", "wall_score"}
        self.assertTrue(all(required.issubset(row) for row in rows))


if __name__ == "__main__":
    unittest.main()
