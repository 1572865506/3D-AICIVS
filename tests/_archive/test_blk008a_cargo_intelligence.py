import unittest

from backend.api.adapters.layout_adapter import LayoutAdapter
from backend.solver_v2.loading.planner import LoadingSequencePlanner
from backend.solver_v2.solver.baseline_solver import SolverSolution,SolverTelemetry
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from run_blk003_benchmark import load_dataset
from src.cargo.intelligence import CargoConstraintAdapter,CargoProfileEngine
from src.solver.integration.door import DoorIntegratedSolver

DATASET="devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json"

class EmptyFrozenSolver:
    def solve(self,container,cargo_list,options=None):
        v=IndependentGlobalValidator.validate(container,[],cargo_list)
        return SolverSolution("SUCCESS",container,[],0,sum(s.quantity.required for s in cargo_list),0,0,v,SolverTelemetry())

class TestBLK008ACargoIntelligence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container,cls.cargo=load_dataset(DATASET)
        cls.adapter=CargoConstraintAdapter();cls.prepared=cls.adapter.prepare(cls.cargo)

    def test_cargo_001_display_classification_and_fragility(self):
        p=self.prepared.profiles["SKU-02"]
        self.assertEqual(p.category.value,"DISPLAY")
        self.assertEqual(p.fragility,"HIGH")
        self.assertEqual(p.source,"USER_DEFINED")

    def test_cargo_002_illegal_side_orientation_rejected(self):
        self.assertEqual(self.adapter.validate_orientation(self.prepared,"SKU-02","SIDE","MAIN_BODY"),(False,"CARGO_INTELLIGENCE_ORIENTATION_FORBIDDEN"))

    def test_cargo_003_explicit_top_flat_for_02_and_14(self):
        for sku_id in ("SKU-02","SKU-14"):
            allowed,reason=self.adapter.validate_orientation(self.prepared,sku_id,"FLAT","TOP_FILL")
            self.assertTrue(allowed);self.assertIsNone(reason)
        self.assertFalse(self.adapter.validate_orientation(self.prepared,"SKU-03","FLAT","TOP_FILL")[0])

    def test_cargo_004_heavy_load_on_display_rejected(self):
        self.assertEqual(self.adapter.validate_compression(self.prepared,"SKU-14",30),(False,"COMPRESSION_LIMIT_EXCEEDED"))
        self.assertEqual(self.adapter.validate_compression(self.prepared,"SKU-14",20),(True,None))

    def test_cargo_005_sku14_three_layers_pass_four_fail(self):
        self.assertTrue(self.adapter.validate_stack(self.prepared,"SKU-14",2,1)[0])
        ok,remaining,reason=self.adapter.validate_stack(self.prepared,"SKU-14",3,1)
        self.assertFalse(ok);self.assertEqual(remaining,0);self.assertEqual(reason,"MAX_STACK_LAYERS")

    def test_cargo_006_real_case_does_not_regress_f3(self):
        solver=DoorIntegratedSolver(EmptyFrozenSolver(),enable_cargo_walls=True,enable_wall_optimization=True).with_topfill_optimization()
        solution=solver.solve(self.container,self.cargo)
        self.assertTrue(solution.validation_result.is_valid)
        self.assertGreaterEqual(solution.volume_utilization_pct,71.3574)
        self.assertTrue(solver.last_diagnostics.cargo_intelligence_ready)

    def test_topfill_result_obeys_intelligence_orientation(self):
        solver=DoorIntegratedSolver(EmptyFrozenSolver(),enable_cargo_walls=True,enable_wall_optimization=True).with_topfill_optimization()
        solver.solve(self.container,self.cargo)
        for placement in solver.last_topfill_prepared.result.placements:
            self.assertTrue(self.adapter.validate_orientation(self.prepared,placement.sku_id,placement.orientation.name,"TOP_FILL")[0])

    def test_loading_result_contains_intelligence_fields(self):
        solver=DoorIntegratedSolver(EmptyFrozenSolver())
        solution=solver.solve(self.container,self.cargo)
        plan=LoadingSequencePlanner(self.container,self.cargo).plan(solution.placements)
        rows=LayoutAdapter.cargo(solution.placements,self.cargo,self.container,plan,[])
        required={"category","fragility","orientationUsed","stackLayer","loadingReason"}
        self.assertTrue(rows);self.assertTrue(all(required.issubset(row) for row in rows))

    def test_adapter_is_non_destructive_to_solver_profiles(self):
        before=[id(s.cargo_profile) for s in self.cargo]
        CargoConstraintAdapter().prepare(self.cargo)
        self.assertEqual(before,[id(s.cargo_profile) for s in self.cargo])
        self.assertFalse(self.prepared.audit["solver_constraints_mutated"])

if __name__=="__main__":unittest.main()
