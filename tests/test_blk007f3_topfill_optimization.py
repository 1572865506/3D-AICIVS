import unittest

from backend.solver_v2.loading.planner import LoadingSequencePlanner
from backend.solver_v2.solver.baseline_solver import SolverSolution,SolverTelemetry
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from run_blk003_benchmark import load_dataset
from src.constraints.topfill import TopFillEngine,TopOrientationOptimizer,TopSupportAnalyzer
from src.constraints.topfill.types import TopRegion
from src.solver.integration.door import DoorConstraintAdapter,DoorIntegratedSolver
from src.solver.integration.wall import WallConstraintAdapter,WallOptimizationAdapter

DATASET="devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json"

class EmptyFrozenSolver:
    def solve(self,container,cargo_list,options=None):
        v=IndependentGlobalValidator.validate(container,[],cargo_list)
        return SolverSolution("SUCCESS",container,[],0,sum(s.quantity.required for s in cargo_list),0,0,v,SolverTelemetry())

class TestBLK007F3TopFill(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container,cls.cargo=load_dataset(DATASET)
        cls.door=DoorConstraintAdapter().prepare(cls.container,cls.cargo)
        cls.wall=WallConstraintAdapter().prepare(cls.door.solver_container,cls.door.solver_cargo)
        cls.opt=WallOptimizationAdapter().prepare(cls.wall,cls.door).result
        inventory_layout=cls.door.door_context.anchor_placements+cls.opt.expanded_placements
        cls.top=TopFillEngine().fill(cls.container,cls.cargo,inventory_layout,cls.opt.optimized_walls)

    def test_top_001_detects_unused_height_regions(self):
        self.assertEqual(len(self.top.regions),15)
        self.assertTrue(any(r.classification=="AVAILABLE_TOP" and r.height>0 for r in self.top.regions))

    def test_top_002_sku02_explicit_flat_maps_to_horizontal(self):
        sku=next(s for s in self.cargo if s.sku_id=="SKU-02")
        region=TopRegion("R","W",0,0,2.53,2.12,.833,.16,.282,.833*2.12,"AVAILABLE_TOP","SKU-05",100,None)
        orientations=TopOrientationOptimizer().orientations(sku,region)
        self.assertTrue(any(label=="TOP_HORIZONTAL" and o.is_flat for o,label,_ in orientations))
        self.assertTrue(all(permission.topAllowed for _,_,permission in orientations))

    def test_top_003_supports_one_to_three_layers(self):
        indices={layer.layer_index for layer in self.top.layers}
        self.assertTrue({1,2,3}.issubset(indices))
        self.assertLessEqual(max(indices),3)

    def test_top_004_rejects_unsupported_placement(self):
        region=TopRegion("R","W",0,0,2,1,1,.5,.5,1,"AVAILABLE_TOP","S",100,None)
        state=TopSupportAnalyzer().analyze(region,2,2,.5,.5,1)
        self.assertFalse(state.valid)
        self.assertEqual(state.reason,"INSUFFICIENT_TOP_SUPPORT")

    def test_top_005_rejects_excess_top_load(self):
        region=TopRegion("R","W",0,0,2,1,1,.5,.5,1,"AVAILABLE_TOP","S",100,10)
        state=TopSupportAnalyzer().analyze(region,0,0,.5,.5,20)
        self.assertFalse(state.valid)
        self.assertEqual(state.reason,"TOP_LOAD_EXCEEDED")

    def test_top_006_real_case_improves_f2_utilization(self):
        solver=DoorIntegratedSolver(EmptyFrozenSolver(),enable_cargo_walls=True,enable_wall_optimization=True).with_topfill_optimization()
        solution=solver.solve(self.container,self.cargo)
        self.assertTrue(solution.validation_result.is_valid)
        self.assertGreater(solution.volume_utilization_pct,69.1412)
        self.assertEqual(solver.last_diagnostics.top_fill_max_layers,3)

    def test_structural_wall_fingerprint_is_preserved(self):
        self.assertTrue(self.top.structural_lock_preserved)
        self.assertEqual(len(self.opt.expanded_placements),1300)

    def test_loading_sequence_places_topfill_after_supporting_walls(self):
        all_placements=list(self.door.door_context.anchor_placements+self.opt.expanded_placements+self.top.placements)
        plan=LoadingSequencePlanner(self.container,self.cargo).plan(all_placements)
        self.assertTrue(plan.sequence_feasible)
        step={pid:s.step_index for s in plan.steps for pid in s.placement_ids}
        self.assertTrue(all(step[p.placement_id]>0 for p in self.top.placements))

if __name__=="__main__":unittest.main()
