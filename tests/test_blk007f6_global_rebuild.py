import unittest

from backend.solver_v2.solver.baseline_solver import SolverSolution, SolverTelemetry
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from run_blk003_benchmark import load_dataset
from src.optimization.global_rebuild import RebuildController
from src.solver.integration.door import DoorIntegratedSolver


DATASET="devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json"


class EmptyFrozenSolver:
    def solve(self,container,cargo_list,options=None):
        validation=IndependentGlobalValidator.validate(container,[],cargo_list)
        return SolverSolution("SUCCESS",container,[],0,sum(s.quantity.required for s in cargo_list),0,0,validation,SolverTelemetry())


class TestBLK007F6GlobalRebuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container,cls.cargo=load_dataset(DATASET)
        cls.solver=(DoorIntegratedSolver(EmptyFrozenSolver(),enable_cargo_walls=True,enable_wall_optimization=True)
                    .with_direction_strategy().with_layer_optimization().with_topfill_optimization().with_global_rebuild("REBUILD"))
        cls.solution=cls.solver.solve(cls.container,cls.cargo)
        cls.result=cls.solver.last_rebuild_result

    def test_rebuild_controller_defaults_to_normal(self):
        self.assertFalse(RebuildController().enabled)
        self.assertTrue(RebuildController("REBUILD").enabled)

    def test_multiple_complete_candidates_are_generated(self):
        self.assertEqual(len(self.result.candidates),5)
        self.assertTrue(all(candidate.valid for candidate in self.result.candidates))

    def test_display_wall_001_short_edge_wall_is_preserved(self):
        displays=[p for p in self.solution.placements if p.sku_id in {"SKU-02","SKU-03","SKU-04","SKU-14"}
                  and p.context.value!="TOP_FILL" and not p.placement_id.startswith("door_pre_")]
        self.assertTrue(displays)
        self.assertTrue(all(p.orientation.dx<=p.orientation.dy+1e-9 for p in displays))

    def test_display_wall_002_direction_changes_visible_positions(self):
        old={p.placement_id:p.position.x for p in self.result.incumbent.placements if p.sku_id=="SKU-02"}
        new={p.placement_id:p.position.x for p in self.result.best_layout.placements if p.sku_id=="SKU-02"}
        self.assertGreater(sum(abs(old[key]-new[key])>1e-6 for key in old),0)
        self.assertTrue(self.result.comparison["direction_effective"])

    def test_global_layer_001_balanced_candidate_wins(self):
        self.assertEqual(self.result.best_layout.strategy.family,"LAYER_BALANCED")
        self.assertGreater(self.result.best_layout.score.layer_balance,self.result.incumbent.score.layer_balance)
        self.assertTrue(self.result.comparison["wall_order_changed"])

    def test_door_wall_is_regenerated_and_remains_safe(self):
        self.assertTrue(self.result.best_layout.wall_plan.door_wall_regenerated)
        door=[p for p in self.solution.placements if p.placement_id.startswith("door_pre_")]
        self.assertEqual(len(door),231)
        self.assertTrue(self.solver.last_transport_validation.door_open_valid)
        self.assertGreaterEqual(self.solver.last_diagnostics.door_seal_coverage,95)

    def test_14sku_rebuild_is_complete_legal_and_within_quality_gate(self):
        self.assertEqual(self.solution.status,"SUCCESS")
        self.assertTrue(self.solution.validation_result.is_valid)
        self.assertGreaterEqual(round(self.solution.volume_utilization_pct,4),71.0044)
        self.assertTrue(self.solver.last_diagnostics.global_rebuild_ready)
        self.assertEqual(self.solver.last_diagnostics.rebuilt_layout_id,"candidate_04")


if __name__=="__main__":unittest.main()
