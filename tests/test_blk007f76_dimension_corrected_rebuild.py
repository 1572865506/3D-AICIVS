import json,unittest
from pathlib import Path
from backend.solver_v2.solver.baseline_solver import SolverSolution,SolverTelemetry
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from run_blk003_benchmark import load_dataset
from src.solver.integration.door import DoorIntegratedSolver

DATASET="devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json"
class EmptyFrozenSolver:
    def solve(self,c,cargo_list,options=None):return SolverSolution("SUCCESS",c,[],0,sum(s.quantity.required for s in cargo_list),0,0,IndependentGlobalValidator.validate(c,[],cargo_list),SolverTelemetry())

class TestBLK007F76DimensionCorrectedRebuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container,cls.cargo=load_dataset(DATASET)
        cls.solver=(DoorIntegratedSolver(EmptyFrozenSolver(),enable_cargo_walls=True,enable_wall_optimization=True)
            .with_direction_strategy().with_layer_optimization().with_topfill_optimization().with_global_rebuild("REBUILD")
            .with_cargo_recomposition().with_dimension_corrected_rebuild().with_wall_internal_repack())
        cls.solution=cls.solver.solve(cls.container,cls.cargo)

    def test_sku14_uses_488_80_336_and_short_thickness_forward(self):
        sku=next(x for x in self.cargo if x.sku_id=="SKU-14")
        self.assertEqual((sku.box.x,sku.box.y,sku.box.z),(.488,.080,.336))
        choice=next(x for x in self.solver.last_direction_plan.selected_candidates if x.sku=="SKU-14")
        self.assertEqual(choice.facing,"SHORT_EDGE_FORWARD")
        self.assertEqual((choice.forward_depth,choice.wall_width),(.080,.488))

    def test_display_wall_is_regenerated_from_corrected_main_layout(self):
        display=self.solver.last_recomposition_result.display
        self.assertTrue(display["valid"]);self.assertEqual(display["continuity"],100);self.assertEqual(display["same_orientation"],100)

    def test_coordinates_are_fresh_and_not_reused_from_f75(self):
        old=json.loads(Path("BLK007F75_FINAL_LAYOUT.json").read_text())["loading_result"]["cargo"]
        old={row["id"]:(row["position"]["x"],row["position"]["y"],row["position"]["z"]) for row in old}
        common=[p for p in self.solution.placements if p.placement_id in old]
        changed=sum(old[p.placement_id]!=(p.position.x,p.position.y,p.position.z) for p in common)
        self.assertGreater(changed/max(len(common),1),.05)

    def test_layer_and_topfill_are_recomputed_after_recomposition(self):
        base_ids={p.placement_id for p in self.solver.last_recomposition_result.placements}
        self.assertFalse(any(x.startswith("layer_complete_") or x.startswith("top_opt_") for x in base_ids))
        self.assertEqual(len(self.solver.last_layer_prepared.result.added_placements),10)
        self.assertEqual(len(self.solver.last_topfill_prepared.result.placements),52)

    def test_final_layout_is_complete_and_physical(self):
        self.assertEqual(len(self.solution.placements),1593)
        self.assertAlmostEqual(self.solution.volume_utilization_pct,75.65192991478443)
        self.assertTrue(self.solution.validation_result.is_valid)
        self.assertEqual(len(self.solution.validation_result.violations),0)

    def test_door_adjacent_and_wire_validation_remain_ready(self):
        self.assertTrue(self.solver.last_recomposition_result.door["stable"])
        self.assertEqual(self.solver.last_wall_repack_result.display_continuity,100)
        self.assertTrue(self.solver.last_wall_repack_result.validation.is_valid)

if __name__=="__main__":unittest.main()
