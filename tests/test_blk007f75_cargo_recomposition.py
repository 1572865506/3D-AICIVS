import unittest
from backend.solver_v2.solver.baseline_solver import SolverSolution,SolverTelemetry
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from backend.api.service import LoadingAPIService
from run_blk003_benchmark import load_dataset
from src.solver.integration.door import DoorIntegratedSolver

DATASET="devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json"
class EmptyFrozenSolver:
    def solve(self,c,cargo_list,options=None):return SolverSolution("SUCCESS",c,[],0,sum(s.quantity.required for s in cargo_list),0,0,IndependentGlobalValidator.validate(c,[],cargo_list),SolverTelemetry())

class TestBLK007F75CargoRecomposition(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container,cls.cargo=load_dataset(DATASET)
        cls.solver=(DoorIntegratedSolver(EmptyFrozenSolver(),enable_cargo_walls=True,enable_wall_optimization=True)
            .with_direction_strategy().with_layer_optimization().with_topfill_optimization().with_global_rebuild("REBUILD")
            .with_cargo_recomposition().with_wall_internal_repack())
        cls.solution=cls.solver.solve(cls.container,cls.cargo);cls.result=cls.solver.last_recomposition_result

    def test_tcrs_001_all_layout_cargo_enters_unbound_pool(self):
        self.assertEqual(len(self.result.pool.items),len(self.solution.placements))
        self.assertGreaterEqual(self.result.pool.original_wall_count,50)

    def test_tcrs_002_real_recomposition_moves_over_thirty_percent(self):
        self.assertGreaterEqual(self.result.best.changed_count/len(self.solution.placements),.30)
        self.assertGreater(self.result.best.wall_changes,0)
        self.assertNotEqual(self.result.best.strategy,"INCUMBENT")

    def test_tcrs_003_display_wall_is_continuous_and_same_direction(self):
        self.assertTrue(self.result.display["valid"])
        self.assertGreaterEqual(self.result.display["continuity"],95)
        self.assertGreaterEqual(self.result.display["same_orientation"],95)

    def test_tcrs_004_locked_door_first_layer_remains_stable(self):
        self.assertTrue(self.result.door["stable"])
        original={x["id"]:tuple(x["original_position"]) for x in self.result.pool.items if x["id"].startswith("door_pre_")}
        final={p.placement_id:(p.position.x,p.position.y,p.position.z) for p in self.solution.placements if p.placement_id.startswith("door_pre_")}
        self.assertEqual(original,final)

    def test_tcrs_005_real_case_improves_structure_score_and_is_valid(self):
        self.assertTrue(self.solution.validation_result.is_valid)
        self.assertGreater(self.result.best.score.global_score,self.result.candidates[0].score.global_score)
        self.assertAlmostEqual(self.solution.volume_utilization_pct,75.65192991478443)

    def test_search_is_bounded_and_all_candidates_are_hard_valid(self):
        self.assertEqual(len(self.result.candidates),10)
        self.assertTrue(all(candidate.valid for candidate in self.result.candidates))

    def test_orientation_search_never_exceeds_six_policy_legal_rotations(self):
        catalog={s.sku_id:s for s in self.cargo}
        search=self.solver.recomposition_engine.orientations
        self.assertTrue(all(len(search.candidates(catalog[p.sku_id],p))<=6 for p in self.solution.placements))

    def test_loading_result_exposes_recomposition_audit_without_schema_change(self):
        result=LoadingAPIService().register_solver_output("tcrs",self.solution,self.container,self.cargo)
        changed=[row for row in result["cargo"] if "original_position" in row]
        self.assertGreaterEqual(len(changed)/len(result["cargo"]),.30)
        self.assertEqual(result["version"],"BLK007C")

if __name__=="__main__":unittest.main()
