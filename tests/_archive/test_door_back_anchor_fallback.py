import unittest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.search.config import SearchConfig,SearchProfile
from backend.solver_v2.search.engine import HierarchicalSearchSolver
from backend.solver_v2.solver.baseline_solver import SolverSolution,SolverTelemetry
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from src.solver.integration.door import DoorIntegratedSolver


class _EmptyFrozenSolver:
    def solve(self,container,cargo_list,options=None):
        validation=IndependentGlobalValidator.validate(container,[],cargo_list)
        return SolverSolution("SUCCESS",container,[],0,sum(s.quantity.required for s in cargo_list),0,0,validation,SolverTelemetry())


class TestDoorBackAnchorFallback(unittest.TestCase):
    def setUp(self):
        self.container=InputAdapter.parse_container({
            "code":"40HQ","usable":{"L":12.032,"W":2.352,"H":2.698},
            "maxPayloadKg":28600,"doorZoneLengthM":1.2,"rearZoneLengthM":1.0,
        })
        self.cargo=InputAdapter.parse_cargo_list([
            {"sku":"ELEC-99","name":"Precision Electronics","w":.8,"d":.58,"h":.65,"weight":65,"quantity":48,"requirement":"放中间"},
            {"sku":"MECH-42","name":"Mechanical Parts","w":.8,"d":.58,"h":.65,"weight":110,"quantity":40,"requirement":"放柜子最里面"},
            {"sku":"MED-771","name":"Medical Cargo","w":.8,"d":.58,"h":.65,"weight":45,"quantity":36,"requirement":"放中间"},
            {"sku":"COLD-08","name":"Cold Chain","w":.8,"d":.58,"h":.65,"weight":55,"quantity":28,"requirement":"封柜门"},
        ])

    def test_sparse_manifest_builds_real_door_back_anchor(self):
        solver=DoorIntegratedSolver(_EmptyFrozenSolver(),enable_cargo_walls=True,enable_wall_optimization=True)
        solution=solver.solve(self.container,self.cargo)

        diagnostic=solver.last_wall_optimization_attempt
        self.assertEqual(diagnostic["admission_mode"],"DOOR_BACK_ANCHOR_ONLY")
        self.assertTrue(diagnostic["door_back_anchor_ready"])
        self.assertGreaterEqual(diagnostic["door_back_anchor_coverage"],.70)
        self.assertFalse(diagnostic["wall_chain_valid"])
        self.assertTrue(solver.last_transport_validation.valid)
        self.assertTrue(solution.validation_result.is_valid)
        self.assertEqual(len(solution.validation_result.overlap_violations),0)

    def test_complete_optimization_pipeline_cannot_move_back_anchor(self):
        solver=(DoorIntegratedSolver(
            HierarchicalSearchSolver(config=SearchConfig.for_profile(
                SearchProfile.BALANCED,time_budget_sec=20,seed=42)),
            enable_cargo_walls=True,enable_wall_optimization=True)
            .with_direction_strategy(True).with_layer_optimization(True)
            .with_topfill_optimization(True).with_global_rebuild("REBUILD")
            .with_cargo_recomposition(True).with_multisku_wall_recomposition(True)
            .with_3d_layer_recomposition(True).with_wall_interface_repair(True)
            .with_dimension_corrected_rebuild(True).with_wall_internal_repack(True)
            .with_residual_filling(True))

        solution=solver.solve(self.container,self.cargo)
        anchors=tuple(p for p in solution.placements if p.placement_id.startswith("transition_wall_"))
        self.assertTrue(solution.validation_result.is_valid)
        self.assertTrue(solver.last_transport_validation.valid)
        self.assertTrue(anchors)
        self.assertAlmostEqual(max(p.max_x for p in anchors),solver.last_prepared.door_wall.anchor_x)
        self.assertIn("MULTISKU_WALL_RECOMPOSITION",solver.last_structural_lock_rejections)


if __name__=="__main__":unittest.main()
