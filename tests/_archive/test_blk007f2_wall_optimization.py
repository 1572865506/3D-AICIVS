import unittest

from backend.solver_v2.domain.models import BoxDim,ContainerSpec,Orientation3D,Placement,PlacementContext,Point3D
from backend.solver_v2.solver.baseline_solver import SolverSolution,SolverTelemetry
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from run_blk003_benchmark import load_dataset
from src.constraints.wall.optimization import WallBalanceAnalyzer,WallOptimizationEngine
from src.solver.integration.door import DoorConstraintAdapter,DoorIntegratedSolver
from src.solver.integration.wall import WallConstraintAdapter,WallOptimizationAdapter

DATASET="devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json"

class EmptyFrozenSolver:
    def solve(self,container,cargo_list,options=None):
        v=IndependentGlobalValidator.validate(container,[],cargo_list)
        return SolverSolution("SUCCESS",container,[],0,sum(s.quantity.required for s in cargo_list),0,0,v,SolverTelemetry())

class TestBLK007F2WallOptimization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container,cls.cargo=load_dataset(DATASET)
        cls.door=DoorConstraintAdapter().prepare(cls.container,cls.cargo)
        cls.wall=WallConstraintAdapter().prepare(cls.door.solver_container,cls.door.solver_cargo)
        cls.result=WallOptimizationEngine().optimize(cls.wall.plan,cls.wall.solver_cargo,cls.wall.original_container,cls.door.door_wall)

    def test_wall_opt_001_expansion_extends_wall_end(self):
        self.assertGreater(self.result.optimized_wall_end_x,7.227)
        self.assertGreater(self.result.coverage_increase_m,3.5)
        self.assertLessEqual(self.door.door_wall.anchor_x-self.result.optimized_wall_end_x,.03)

    def test_wall_opt_002_transition_chain_is_valid(self):
        self.assertTrue(self.result.transition_walls)
        self.assertTrue(self.result.chain.valid)
        self.assertFalse(self.result.chain.broken_points)
        roles={n["role"] for n in self.result.chain.nodes}
        self.assertTrue({"CARGO_WALL","TRANSITION_WALL","DOOR_WALL"}.issubset(roles))

    def test_wall_opt_003_merge_reduces_fragmentation(self):
        self.assertLess(self.result.fragmentation_after,self.result.fragmentation_before)
        self.assertTrue(any(len(segment["source_ids"])>1 for segment in self.result.merged_segments))

    def test_wall_opt_004_balance_analyzer_detects_left_bias(self):
        c=ContainerSpec("T",BoxDim(2,2,2),1000)
        p=Placement("p","p","S",Point3D(0,.1,0),Orientation3D(.5,.5,.5),10,PlacementContext.MAIN_WALL)
        report=WallBalanceAnalyzer().analyze([p],c)
        self.assertGreater(report.leftWeight,report.rightWeight)
        self.assertLess(report.balanceScore,100)

    def test_wall_opt_005_real_case_improves_f1_utilization(self):
        solver=DoorIntegratedSolver(EmptyFrozenSolver(),enable_cargo_walls=True,enable_wall_optimization=True)
        solution=solver.solve(self.container,self.cargo)
        self.assertTrue(solution.validation_result.is_valid)
        self.assertGreater(solution.volume_utilization_pct,60.3716)
        self.assertEqual(sum(p.placement_id.startswith("door_pre_") for p in solution.placements),231)

    def test_longitudinal_transition_coverage_exceeds_99_percent(self):
        self.assertLessEqual(self.door.door_wall.anchor_x-self.result.optimized_wall_end_x,.01)

    def test_optimization_adapter_reserves_transition_inventory(self):
        prepared=WallOptimizationAdapter().prepare(self.wall,self.door)
        self.assertAlmostEqual(prepared.x_offset,11.424)
        self.assertLess(prepared.solver_container.Lx,.01)
        for sku_id,count in self.result.consumed_inventory.items():
            before=next(s.quantity.required for s in self.wall.solver_cargo if s.sku_id==sku_id)
            after=next(s.quantity.required for s in prepared.solver_cargo if s.sku_id==sku_id)
            self.assertEqual(before-after,count)

if __name__=="__main__":unittest.main()
