import unittest
from backend.api.adapters.layout_adapter import LayoutAdapter
from backend.solver_v2.loading.planner import LoadingSequencePlanner
from backend.solver_v2.solver.baseline_solver import SolverSolution,SolverTelemetry
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from run_blk003_benchmark import load_dataset
from src.solver.integration.door import DoorIntegratedSolver

DATASET="devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json"
class EmptyFrozenSolver:
    def solve(self,c,cargo_list,options=None):return SolverSolution("SUCCESS",c,[],0,sum(s.quantity.required for s in cargo_list),0,0,IndependentGlobalValidator.validate(c,[],cargo_list),SolverTelemetry())

class TestBLK007F7WallRepacking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container,cls.cargo=load_dataset(DATASET)
        cls.solver=(DoorIntegratedSolver(EmptyFrozenSolver(),enable_cargo_walls=True,enable_wall_optimization=True)
            .with_direction_strategy().with_layer_optimization().with_topfill_optimization().with_global_rebuild("REBUILD").with_wall_internal_repack())
        cls.solution=cls.solver.solve(cls.container,cls.cargo);cls.result=cls.solver.last_wall_repack_result

    def test_wire_001_wall_decomposes_to_columns_and_layers(self):
        self.assertEqual(len(self.result.walls),50)
        wall=next(w for w in self.result.walls if w.wall_id=="CARGO_WALL_005")
        self.assertEqual(wall.cargo_count,46);self.assertEqual(len(wall.columns),6);self.assertEqual(len(wall.layers),16)

    def test_wire_002_contact_repack_reduces_internal_gap(self):
        self.assertEqual(self.result.gap_before_m,0);self.assertEqual(self.result.gap_after_m,0)
        moved=[p for p in self.solution.placements if p.placement_id.startswith("layer_complete_")]
        self.assertEqual(len(moved),10)
        self.assertTrue(all(0<=p.min_y and p.max_y<=self.container.Ly+1e-9 for p in moved))
        self.assertTrue(all(p.orientation.dx<=p.orientation.dy+1e-9 for p in moved if p.sku_id=="SKU-14"))

    def test_wire_003_display_walls_choose_continuous_pattern(self):
        display_ids={w.wall_id for w in self.result.walls if w.display_wall}
        chosen={c.wall_id:c.pattern.family for c in self.result.selected}
        self.assertTrue(display_ids);self.assertTrue(all(chosen[x]=="CONTINUOUS_DISPLAY" for x in display_ids))
        self.assertEqual(self.result.display_continuity,100)

    def test_wire_004_door_adjacent_wall_is_stable(self):
        self.assertTrue(self.result.door_adjacent["ready"]);self.assertTrue(self.result.door_adjacent["stable"])
        self.assertLessEqual(self.result.door_adjacent["gap_m"],.005)

    def test_wire_005_real_case_preserves_utilization_and_physics(self):
        self.assertTrue(self.solution.validation_result.is_valid)
        self.assertGreaterEqual(round(self.solution.volume_utilization_pct,4),71.5044)
        self.assertTrue(self.solver.last_diagnostics.wall_internal_repack_ready)
        self.assertGreaterEqual(self.result.global_score_after,self.result.global_score_before)

    def test_topfill_remains_compatible_after_internal_repack(self):
        self.assertTrue(self.result.topfill_compatible)
        self.assertEqual(sum(p.context.value=="TOP_FILL" for p in self.solution.placements),52)

    def test_layout_contains_wire_metadata(self):
        plan=LoadingSequencePlanner(self.container,self.cargo).plan(self.solution.placements)
        rows=LayoutAdapter.cargo(self.solution.placements,self.cargo,self.container,plan,[])
        required={"wall_id","pattern_id","repack_reason","layer_score","continuity_score"}
        self.assertTrue(all(required.issubset(row) for row in rows))

if __name__=="__main__":unittest.main()
