import dataclasses
import unittest

from backend.solver_v2.domain.models import Orientation3D, Placement, PlacementContext, Point3D
from backend.solver_v2.solver.baseline_solver import SolverSolution, SolverTelemetry
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from run_blk003_benchmark import load_dataset
from src.constraints.door import (
    DoorSafetyConfig, DoorSafetyEngine, DoorWallValidator,
    TransportForceConfig,
)
from src.solver.integration.door import DoorConstraintAdapter, DoorIntegratedSolver, ReservedRegionManager


DATASET = "devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json"


class EmptyFrozenSolver:
    def solve(self, container, cargo_list, options=None):
        validation=IndependentGlobalValidator.validate(container,[],cargo_list)
        return SolverSolution("SUCCESS",container,[],0,sum(s.quantity.required for s in cargo_list),
                              0.0,0.0,validation,SolverTelemetry())


class TestBLK007F8ADoorTransport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container,cls.cargo=load_dataset(DATASET)
        cls.engine=DoorSafetyEngine(DoorSafetyConfig.formation_v2())
        cls.plan=cls.engine.plan(cls.container,cls.cargo)

    def test_f8a_001_wall_is_formed_near_door_plane(self):
        self.assertEqual(self.plan.status,"READY")
        self.assertGreaterEqual(self.plan.wall.coverage,.90)
        self.assertGreaterEqual(self.plan.wall.width_coverage,.95)
        self.assertGreaterEqual(self.plan.wall.height_coverage,.80)
        self.assertLessEqual(self.plan.wall.door_plane_clearance,.12)
        self.assertGreater(self.plan.wall.anchor_x,self.plan.zone.solver_start_x)

    def test_f8a_002_old_reserved_void_is_released_to_main_solver(self):
        prepared=DoorConstraintAdapter(self.engine).prepare(self.container,self.cargo)
        self.assertAlmostEqual(prepared.solver_container.Lx,self.plan.wall.anchor_x)
        self.assertGreater(prepared.solver_container.Lx-self.plan.zone.solver_start_x,.5)
        candidate=Placement("released","released","SKU-05",Point3D(11.0,0,0),
                            Orientation3D(.2,.2,.2,"UPRIGHT"),1,PlacementContext.MAIN_WALL)
        self.assertTrue(ReservedRegionManager(prepared.door_context.blocked_area).validate(candidate).valid)

    def test_f8a_003_transport_axes_are_hard_validated(self):
        result=self.plan.validation
        self.assertTrue(result.transport_stable)
        self.assertEqual(result.transport["outward_direction"],"+X")
        self.assertEqual({a["vector"] for a in result.transport["axes"]},{"+X","-X","+Y/-Y","Z"})
        self.assertTrue(all(a["valid"] for a in result.transport["axes"]))
        self.assertTrue(result.transport["door_open_valid"])

    def test_f8a_004_far_from_door_has_explicit_hard_rejection(self):
        shifted=tuple(dataclasses.replace(p,x=self.plan.zone.solver_start_x) for p in self.plan.wall.placements)
        far=dataclasses.replace(self.plan.wall,placements=shifted,anchor_x=self.plan.zone.solver_start_x)
        validator=DoorWallValidator(.90,.20,.70,.95,.80,TransportForceConfig(max_door_restraint_gap_m=.10))
        result=validator.validate(far,self.plan.zone,self.container)
        self.assertFalse(result.valid)
        self.assertIn("OUTWARD_DOOR_RESTRAINT_GAP_EXCEEDED",result.issues)

    def test_f8a_005_door_open_stable_orientation_and_mix_are_deterministic(self):
        again=self.engine.plan(self.container,self.cargo)
        self.assertEqual(self.plan.wall.to_dict(),again.wall.to_dict())
        self.assertEqual({p.orientation for p in self.plan.wall.placements},{"LONG_EDGE_FORWARD"})
        self.assertGreater(len(self.plan.wall.sku_mix),1)
        self.assertTrue(self.plan.validation.transport["door_open_valid"])

    def test_f8a_006_final_integration_runs_transport_gate(self):
        solver=DoorIntegratedSolver(EmptyFrozenSolver(),DoorConstraintAdapter(self.engine))
        solution=solver.solve(self.container,self.cargo)
        self.assertTrue(solution.validation_result.is_valid)
        self.assertTrue(solver.last_transport_validation.valid)
        self.assertTrue(solution.telemetry.door_readiness["transport_force_validation"]["valid"])


if __name__=="__main__":unittest.main()
