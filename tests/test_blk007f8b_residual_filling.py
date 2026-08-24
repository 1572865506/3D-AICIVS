import unittest
from collections import Counter

from backend.solver_v2.domain.models import (BoxDim,CargoSKU,ContainerSpec,Orientation3D,
    Placement,PlacementContext,Point3D,QuantityPlan)
from backend.solver_v2.solver.baseline_solver import SolverSolution,SolverTelemetry
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from run_blk003_benchmark import load_dataset
from src.constraints.wall.optimization import WallInterfaceRepairEngine
from src.optimization.residual_filling import ResidualSpaceFillingEngine
from src.solver.integration.door import DoorIntegratedSolver

DATASET="devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json"


class EmptyFrozenSolver:
    def solve(self,c,cargo_list,options=None):
        return SolverSolution("SUCCESS",c,[],0,sum(s.quantity.required for s in cargo_list),0,0,
            IndependentGlobalValidator.validate(c,[],cargo_list),SolverTelemetry())


class TestBLK007F8BResidualFilling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container,cls.cargo=load_dataset(DATASET)
        cls.solver=(DoorIntegratedSolver(EmptyFrozenSolver(),enable_cargo_walls=True,enable_wall_optimization=True)
            .with_direction_strategy().with_layer_optimization().with_topfill_optimization().with_global_rebuild("REBUILD")
            .with_cargo_recomposition().with_wall_interface_repair().with_dimension_corrected_rebuild()
            .with_wall_internal_repack().with_residual_filling())
        cls.solution=cls.solver.solve(cls.container,cls.cargo);cls.result=cls.solver.last_residual_prepared.result

    def test_f8b_001_incomplete_walls_are_not_centered(self):
        walls=self.solver.last_optimization_prepared.result.optimized_walls
        self.assertTrue(walls)
        self.assertTrue(all(abs(min(p.min_y for p in wall.placements))<=.003 or
            abs(max(p.max_y for p in wall.placements)-self.container.Ly)<=.003 for wall in walls if wall.placements))

    def test_f8b_002_no_opportunistic_single_carton_commit(self):
        self.assertTrue(all(item.source in {"STRUCTURED_FLOOR_ROW","STRUCTURED_TOP_ROW"} for item in self.result.accepted))
        self.assertTrue(all(len(plan.placements)>=2 and plan.coverage>=.85 for plan in self.result.plans))
        self.assertEqual(self.result.to_dict()["structural_quality"]["isolated_fill_count"],0)
        self.assertEqual(self.result.to_dict()["structural_quality"]["checkerboard_pattern_count"],0)

    def test_f8b_003_wall_interface_repair_is_active_and_bounded(self):
        repair=self.solver.last_wall_interface_repair
        self.assertEqual(repair.status,"SUCCESS")
        self.assertGreater(repair.moved_columns,0)
        self.assertLessEqual(repair.maximum_compaction_m,.45)

    def test_f8b_004_no_new_orientation_rights(self):
        self.assertTrue(all(p.orientation.is_upright or p.context==PlacementContext.TOP_FILL for p in self.result.placements))
        self.assertTrue(all(item.support_ratio>=.70 for item in self.result.accepted))

    def test_f8b_005_final_layout_is_physical_without_quality_regression(self):
        self.assertTrue(self.solution.validation_result.is_valid)
        self.assertEqual(len(self.solution.validation_result.violations),0)
        self.assertGreaterEqual(self.solution.volume_utilization_pct,75.6519)
        self.assertTrue(self.solver.last_transport_validation.valid)
        self.assertTrue(self.solver.last_transport_validation.door_open_valid)


class TestStructuredResidualRows(unittest.TestCase):
    def test_f8b_006_mixed_sku_top_row_is_atomic_and_complete(self):
        container=ContainerSpec("ROW",BoxDim(.5,2.0,1.5),5000,door_zone_length_m=0.0)
        sku_a=CargoSKU("A","A",BoxDim(.5,.5,.5),1,QuantityPlan(6))
        sku_b=CargoSKU("B","B",BoxDim(.5,.5,.5),1,QuantityPlan(2))
        orientation=Orientation3D(.5,.5,.5,"UPRIGHT_NORMAL")
        base=tuple(Placement(f"base_{i}",f"a_{i}","A",Point3D(0,i*.5,0),orientation,1,PlacementContext.MAIN_WALL,i) for i in range(4))
        result=ResidualSpaceFillingEngine(max_waves=1).fill(container,(sku_a,sku_b),base)
        self.assertEqual(result.status,"SUCCESS")
        self.assertEqual(len(result.plans),1)
        self.assertEqual(len(result.placements),4)
        self.assertAlmostEqual(result.plans[0].coverage,1.0)
        self.assertEqual(set(result.plans[0].sku_mix),{"A","B"})
        self.assertTrue(result.validation.is_valid)

    def test_f8b_007_single_frontier_obstruction_repairs_only_shoulders(self):
        container=ContainerSpec("IFACE",BoxDim(4,2,1),5000)
        sku=CargoSKU("A","A",BoxDim(.5,.5,.5),1,QuantityPlan(8))
        orientation=Orientation3D(.5,.5,.5,"UPRIGHT_NORMAL")
        placements=[]
        for i in range(4):
            ahead_x=1.5 if i==0 else 1.8
            placements.append(Placement(f"cargo_wall_002_A_{i:03d}",f"ahead_{i}","A",Point3D(ahead_x,i*.5,0),orientation,1,PlacementContext.MAIN_WALL,i))
            placements.append(Placement(f"cargo_wall_001_A_{i:03d}",f"rear_{i}","A",Point3D(1.0,i*.5,0),orientation,1,PlacementContext.MAIN_WALL,4+i))
        result=WallInterfaceRepairEngine().repair(container,(sku,),tuple(placements))
        self.assertEqual(result.status,"SUCCESS")
        self.assertEqual(result.moved_columns,3)
        repaired={p.placement_id:p for p in result.placements}
        self.assertAlmostEqual(repaired["cargo_wall_001_A_000"].min_x,1.0)
        self.assertTrue(all(abs(repaired[f"cargo_wall_001_A_{i:03d}"].min_x-1.3)<1e-9 for i in range(1,4)))
        self.assertTrue(result.validation.is_valid)

    def test_f8b_008_floor_region_is_split_around_center_obstruction(self):
        container=ContainerSpec("SIDE_GAPS",BoxDim(.5,2.5,1.0),5000,door_zone_length_m=0.0)
        filler=CargoSKU("F","F",BoxDim(.5,.25,.5),1,QuantityPlan(8))
        blocker=CargoSKU("B","B",BoxDim(.5,.5,.5),1,QuantityPlan(1))
        block_orientation=Orientation3D(.5,.5,.5,"UPRIGHT_NORMAL")
        existing=(Placement("block","block_i","B",Point3D(0,1.0,0),block_orientation,1,PlacementContext.MAIN_WALL,0),)
        result=ResidualSpaceFillingEngine(max_waves=2).fill(container,(filler,blocker),existing)
        self.assertTrue(result.validation.is_valid)
        self.assertEqual(len(result.placements),8)
        self.assertEqual(len(result.plans),2)
        self.assertTrue(all(plan.region.source=="STRUCTURED_FLOOR_ROW" for plan in result.plans))
        self.assertTrue(all(plan.coverage==1.0 for plan in result.plans))

    def test_f8b_009_multiple_cartons_form_one_continuous_top_support(self):
        container=ContainerSpec("UNION_TOP",BoxDim(.5,2.0,1.0),5000,door_zone_length_m=0.0)
        lower=CargoSKU("L","L",BoxDim(.25,.5,.5),1,QuantityPlan(8))
        upper=CargoSKU("U","U",BoxDim(.5,.5,.5),1,QuantityPlan(4))
        lower_orientation=Orientation3D(.25,.5,.5,"UPRIGHT_NORMAL")
        base=[]
        for ix in range(2):
            for iy in range(4):
                base.append(Placement(f"lower_{ix}_{iy}",f"lower_i_{ix}_{iy}","L",
                    Point3D(ix*.25,iy*.5,0),lower_orientation,1,PlacementContext.MAIN_WALL,len(base)))
        result=ResidualSpaceFillingEngine(max_waves=1).fill(container,(lower,upper),tuple(base))
        self.assertTrue(result.validation.is_valid)
        self.assertEqual(len(result.placements),4)
        self.assertEqual(len(result.plans),1)
        self.assertEqual(result.plans[0].region.source,"STRUCTURED_TOP_ROW")
        self.assertAlmostEqual(result.plans[0].coverage,1.0)


if __name__=="__main__":unittest.main()
