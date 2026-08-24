import dataclasses
import unittest

from backend.api.adapters.layout_adapter import LayoutAdapter
from backend.solver_v2.domain.models import (
    BoxDim,CargoSKU,ContainerSpec,Orientation3D,PackingRole,Placement,PlacementContext,Point3D,QuantityPlan,ZoneType,
)
from backend.solver_v2.loading.planner import LoadingSequencePlanner
from backend.solver_v2.solver.baseline_solver import SolverSolution,SolverTelemetry
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from run_blk003_benchmark import load_dataset
from src.constraints.wall import CargoWallEngine,WallRegionPlanner,WallVoidAnalyzer
from src.solver.integration.door import DoorIntegratedSolver
from src.solver.integration.wall import WallConstraintFilter


DATASET="devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json"


class EmptyFrozenSolver:
    def solve(self,container,cargo_list,options=None):
        v=IndependentGlobalValidator.validate(container,[],cargo_list)
        return SolverSolution("SUCCESS",container,[],0,sum(s.quantity.required for s in cargo_list),0,0,v,SolverTelemetry())


def wall_sku(sku_id="WALL",box=BoxDim(.5,.5,.5),quantity=16):
    return CargoSKU(sku_id,"Generic Wall Cargo",box,5.0,QuantityPlan(quantity),packing_roles=(PackingRole.MAIN_WALL,),target_zone=ZoneType.MIDDLE)


class TestBLK007F1CargoWall(unittest.TestCase):
    def test_wall_001_continuous_wall_has_zero_gap(self):
        container=ContainerSpec("TEST",BoxDim(1.5,2.0,2.0),10000,door_zone_length_m=.1)
        plan=CargoWallEngine().plan(container,[wall_sku()])
        self.assertEqual(plan.status,"READY")
        self.assertTrue(all(layer.gap_count==0 for layer in plan.build.walls[0].layers))
        self.assertEqual(plan.build.walls[0].continuity["largestGap"],0)

    def test_wall_002_thin_wall_has_no_isolated_cargo(self):
        container=ContainerSpec("TEST",BoxDim(1.5,2.0,2.0),10000,door_zone_length_m=.1)
        plan=CargoWallEngine().plan(container,[wall_sku("THIN",BoxDim(.5,.1,.5),16)])
        self.assertEqual(plan.status,"READY")
        self.assertFalse(plan.build.walls[0].stability["isolatedCargo"])
        self.assertTrue(plan.build.walls[0].stability["stable"])

    def test_wall_003_display_profile_forms_vertical_wall(self):
        container,cargo=load_dataset(DATASET)
        displays=[dataclasses.replace(s,packing_roles=(PackingRole.MAIN_WALL,),target_zone=ZoneType.MIDDLE) for s in cargo if s.sku_id in {"SKU-02","SKU-03","SKU-04","SKU-14"}]
        plan=CargoWallEngine().plan(container,displays)
        self.assertEqual(plan.status,"READY")
        self.assertTrue(plan.build.walls)
        self.assertTrue(all(p.orientation.is_upright for p in plan.build.placements))
        self.assertFalse(any(w.stability["isolatedCargo"] for w in plan.build.walls))

    def test_wall_004_internal_void_is_reported(self):
        ps=[]
        for iy in range(3):
            for iz in range(3):
                if (iy,iz)==(1,1):continue
                ps.append(Placement(f"p{iy}{iz}",f"p{iy}{iz}","WALL",Point3D(0,iy*.1,iz*.1),Orientation3D(.1,.1,.1,"UPRIGHT"),1,PlacementContext.MAIN_WALL))
        voids=WallVoidAnalyzer().analyze(ps,resolution=.1)
        self.assertEqual(len(voids),1)
        self.assertIn(voids[0].void_type,{"SMALL_GAP","BRIDGE_VOID","STRUCTURAL_VOID"})

    def test_wall_005_real_case_has_door_and_cargo_walls(self):
        container,cargo=load_dataset(DATASET)
        solver=DoorIntegratedSolver(EmptyFrozenSolver(),enable_cargo_walls=True)
        solution=solver.solve(container,cargo)
        self.assertTrue(solution.validation_result.is_valid)
        self.assertEqual(sum(p.placement_id.startswith("door_pre_") for p in solution.placements),231)
        self.assertGreater(sum(p.placement_id.startswith("cargo_wall_") for p in solution.placements),0)
        mixes=[{p.sku_id for p in wall.placements} for wall in solver.last_wall_prepared.plan.build.walls]
        self.assertTrue(any(len(mix)>1 for mix in mixes))

    def test_region_planner_covers_main_space_without_overlap(self):
        container=ContainerSpec("TEST",BoxDim(4.0,2.0,2.0),10000)
        regions=WallRegionPlanner().plan(container)
        self.assertEqual(regions[0].x_start,0)
        self.assertEqual(regions[-1].x_end,4.0)
        self.assertTrue(all(abs(a.x_end-b.x_start)<1e-9 for a,b in zip(regions,regions[1:])))

    def test_wall_constraint_filter_accepts_generated_walls(self):
        container=ContainerSpec("TEST",BoxDim(1.5,2.0,2.0),10000,door_zone_length_m=.1)
        wall=CargoWallEngine().plan(container,[wall_sku()]).build.walls[0]
        self.assertEqual(WallConstraintFilter().evaluate(wall),(True,None))

    def test_api_role_marks_structural_wall(self):
        container=ContainerSpec("TEST",BoxDim(1.5,2.0,2.0),10000,door_zone_length_m=.1)
        cargo=[wall_sku()];placements=list(CargoWallEngine().plan(container,cargo).build.placements)
        plan=LoadingSequencePlanner(container,cargo).plan(placements)
        rows=LayoutAdapter.cargo(placements,cargo,container,plan,[])
        self.assertTrue(all(row["role"]=="CARGO_WALL" for row in rows))


if __name__=="__main__":unittest.main()
