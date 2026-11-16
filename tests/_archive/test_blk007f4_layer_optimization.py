import unittest

from backend.api.adapters.layout_adapter import LayoutAdapter
from backend.solver_v2.domain.models import PlacementContext
from backend.solver_v2.geometry.aabb import AABB
from backend.solver_v2.loading.planner import LoadingSequencePlanner
from backend.solver_v2.solver.baseline_solver import SolverSolution, SolverTelemetry
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from run_blk003_benchmark import load_dataset
from src.cargo.intelligence import CargoConstraintAdapter
from src.optimization.layer import LayerAnalyzer, OrientationOptimizer, WallBridgeEngine
from src.solver.integration.door import DoorIntegratedSolver


DATASET = "devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json"


class EmptyFrozenSolver:
    def solve(self, container, cargo_list, options=None):
        validation = IndependentGlobalValidator.validate(container, [], cargo_list)
        return SolverSolution(
            "SUCCESS", container, [], 0, sum(s.quantity.required for s in cargo_list),
            0, 0, validation, SolverTelemetry(),
        )


class TestBLK007F4LayerOptimization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container, cls.cargo = load_dataset(DATASET)
        cls.intelligence_adapter = CargoConstraintAdapter()
        cls.intelligence = cls.intelligence_adapter.prepare(cls.cargo)
        cls.solver = (DoorIntegratedSolver(
            EmptyFrozenSolver(), enable_cargo_walls=True, enable_wall_optimization=True
        ).with_layer_optimization().with_topfill_optimization())
        cls.solution = cls.solver.solve(cls.container, cls.cargo)
        cls.layer = cls.solver.last_layer_prepared.result

    def test_layer_001_analyzer_uses_half_metre_bands(self):
        layers = LayerAnalyzer().analyze(self.container, self.solution.placements)
        self.assertEqual(len(layers), 6)
        self.assertEqual(layers[0].height_range, (0.0, 0.5))
        self.assertEqual(layers[-1].height_range, (2.5, self.container.Lz))
        self.assertTrue(all(0.0 <= layer.occupancy <= 1.0 for layer in layers))

    def test_layer_002_completion_reduces_detected_void(self):
        self.assertGreater(len(self.layer.added_placements), 0)
        self.assertGreater(self.layer.occupancy_after, self.layer.occupancy_before)
        self.assertLess(self.layer.void_after, self.layer.void_before)

    def test_layer_003_sku14_dynamic_orientation_uses_best_legal_top_shape(self):
        sku = next(s for s in self.cargo if s.sku_id == "SKU-14")
        decision = OrientationOptimizer().optimize(
            sku, PlacementContext.TOP_FILL, AABB(0, 0, 2.0, 1.0, 1.0, 2.2),
            self.intelligence_adapter, self.intelligence, 0.9, 1.0,
        )
        self.assertIsNotNone(decision)
        self.assertEqual(decision.orientation_used, "FLAT_HORIZONTAL")
        self.assertEqual(decision.reason, "IMPROVE_LAYER_COMPLETION")

    def test_layer_004_display_is_vertical_in_main_and_flat_only_on_top(self):
        sku = next(s for s in self.cargo if s.sku_id == "SKU-02")
        optimizer = OrientationOptimizer()
        main = optimizer.optimize(
            sku, PlacementContext.MAIN_WALL, AABB(0, 0, 0, 1, 1, 1),
            self.intelligence_adapter, self.intelligence,
        )
        top = optimizer.optimize(
            sku, PlacementContext.TOP_FILL, AABB(0, 0, 2.5, 1, 1, 2.7),
            self.intelligence_adapter, self.intelligence, 0.9, 1.0,
        )
        self.assertEqual(main.orientation_used, "VERTICAL")
        self.assertEqual(top.orientation_used, "FLAT_HORIZONTAL")
        self.assertFalse(any(p.orientation.is_flat for p in self.layer.added_placements))

    def test_layer_005_door_seal_reaches_target_without_changing_anchor(self):
        seal = self.layer.door_seal
        self.assertGreaterEqual(seal["door_coverage"], 95.0)
        self.assertTrue(seal["door_wall_unchanged"])
        self.assertTrue(seal["cross_section_locked"])
        self.assertEqual(self.solver.last_diagnostics.door_wall_count, 231)

    def test_layer_006_bridge_requires_support_compression_and_profile(self):
        engine = WallBridgeEngine()
        valid = engine.evaluate("B1", "S", "L", "R", 0.8, True, True, 1.0)
        unsupported = engine.evaluate("B2", "S", "L", "R", 0.79, True, True, 1.0)
        compressed = engine.evaluate("B3", "S", "L", "R", 1.0, False, True, 1.0)
        self.assertTrue(valid.valid)
        self.assertFalse(unsupported.valid)
        self.assertEqual(unsupported.reason, "INSUFFICIENT_SUPPORT")
        self.assertEqual(compressed.reason, "COMPRESSION_FAILURE")

    def test_layer_007_real_case_improves_f3_and_remains_physical(self):
        self.assertTrue(self.solution.validation_result.is_valid)
        self.assertGreater(self.solution.volume_utilization_pct, 71.3574)
        self.assertTrue(self.layer.structural_lock_preserved)
        self.assertTrue(self.solver.last_diagnostics.layer_optimization_ready)

    def test_layout_exposes_layer_orientation_reason_and_role(self):
        plan = LoadingSequencePlanner(self.container, self.cargo).plan(self.solution.placements)
        rows = LayoutAdapter.cargo(self.solution.placements, self.cargo, self.container, plan, [])
        required = {"layer_id", "orientation_used", "optimization_reason", "structural_role"}
        self.assertTrue(all(required.issubset(row) for row in rows))
        self.assertTrue(any(row["structural_role"] == "LAYER_COMPLETION" for row in rows))


if __name__ == "__main__":
    unittest.main()
