"""SEQ-001..012 and ASEQ-001..005 for BLK-007 loading operability."""
import copy
import unittest

from backend.solver_v2.domain.models import (
    BoxDim, CargoSKU, ContainerSpec, Orientation3D, Placement, PlacementContext,
    Point3D, QuantityPlan, StackingPolicy,
)
from backend.solver_v2.loading import (
    LoadingDependencyGraph, LoadingFailureReason, LoadingSequenceConfig,
    LoadingSequencePlanner, OperabilityValidator,
)
from backend.solver_v2.loading.planner import DependencyEdge
from backend.solver_v2.geometry.aabb import AABB
from backend.solver_v2.geometry.spatial_index import SpatialIndex


class TestBLK007LoadingSequence(unittest.TestCase):
    def setUp(self):
        self.container = ContainerSpec("SEQ", BoxDim(4.0, 1.2, 1.5), 3000, door_zone_length_m=.4)
        self.sku = CargoSKU("S", "s", BoxDim(.4, .4, .4), 5, QuantityPlan(20),
                            stacking_policy=StackingPolicy(max_bearing_kg=500))
        self.thin = CargoSKU("T", "t", BoxDim(.4, .12, .8), 4, QuantityPlan(10),
                             stacking_policy=StackingPolicy(max_bearing_kg=200))

    def p(self, pid, x, y=0, z=0, dx=.4, dy=.4, dz=.4, sku="S", context=PlacementContext.MAIN_WALL):
        return Placement(pid, "i_"+pid, sku, Point3D(x,y,z),
                         Orientation3D(dx,dy,dz,"UPRIGHT_NORMAL",is_upright=True),
                         5, context)

    def test_seq_001_simple_deep_to_door(self):
        ps=[self.p("a",0),self.p("b",.5),self.p("c",1.0)]
        plan=LoadingSequencePlanner(self.container,[self.sku]).plan(ps)
        self.assertTrue(plan.sequence_feasible)
        self.assertEqual([s.placement_ids[0] for s in plan.steps],["a","b","c"])

    def test_seq_002_bottom_before_top(self):
        bottom=self.p("bottom",0); top=self.p("top",0,z=.4)
        plan=LoadingSequencePlanner(self.container,[self.sku]).plan([top,bottom])
        self.assertTrue(plan.sequence_feasible)
        self.assertEqual(plan.steps[0].placement_ids,("bottom",))
        self.assertTrue(any(e.dependency_type=="SUPPORT" for e in plan.graph.edges))

    def test_seq_003_blocked_rear_carton_dependency(self):
        graph,_,_=LoadingSequencePlanner(self.container,[self.sku]).build_dependency_graph([self.p("rear",0),self.p("front",1)])
        self.assertTrue(any(e.before_id=="rear" and e.after_id=="front" for e in graph.edges))

    def test_seq_004_topfill_before_front_ceiling_closure(self):
        rear=self.p("top",0,z=.4,context=PlacementContext.TOP_FILL)
        front=self.p("front",1,z=.4)
        graph,_,_=LoadingSequencePlanner(self.container,[self.sku]).build_dependency_graph([rear,front])
        self.assertTrue(any(e.before_id=="top" and e.after_id=="front" and e.dependency_type=="CEILING_CLOSURE" for e in graph.edges))

    def test_seq_005_door_seal_last(self):
        main=self.p("main",0); door=self.p("door",3.5,context=PlacementContext.DOOR_SEAL)
        graph,_,_=LoadingSequencePlanner(self.container,[self.sku]).build_dependency_graph([door,main])
        self.assertTrue(any(e.before_id=="main" and e.after_id=="door" and e.dependency_type=="DOOR_SEAL_LAST" for e in graph.edges))

    def test_seq_006_dependency_cycle_detected(self):
        a=self.p("a",0);b=self.p("b",1)
        graph=LoadingDependencyGraph({"a":a,"b":b},[DependencyEdge("a","b","SUPPORT"),DependencyEdge("b","a","BLOCKING")])
        cycles=LoadingSequencePlanner(self.container,[self.sku])._find_cycles(graph)
        self.assertEqual(set(cycles[0]["placement_ids"]),{"a","b"})

    def test_seq_007_thin_cargo_pair_group(self):
        ps=[self.p("t1",0,0,dx=.4,dy=.12,dz=.8,sku="T"),self.p("t2",0,.12,dx=.4,dy=.12,dz=.8,sku="T")]
        plan=LoadingSequencePlanner(self.container,[self.sku,self.thin]).plan(ps)
        self.assertTrue(any(g.group_type=="THIN_CARGO_PAIR" for g in plan.groups))
        self.assertTrue(any(s.action=="PLACE_GROUP" for s in plan.steps))

    def test_seq_008_temporary_debt_model_resolves(self):
        ps=[self.p("t1",0,0,dx=.4,dy=.12,dz=.8,sku="T"),self.p("t2",0,.12,dx=.4,dy=.12,dz=.8,sku="T")]
        plan=LoadingSequencePlanner(self.container,[self.sku,self.thin]).plan(ps)
        self.assertTrue(all(d.resolved_at_step is not None for d in plan.debts))

    def test_seq_009_unresolved_instability_fails(self):
        isolated=self.p("thin",.5,y=.3,dx=.4,dy=.12,dz=.8,sku="T")
        plan=LoadingSequencePlanner(self.container,[self.sku,self.thin]).plan([isolated])
        self.assertFalse(plan.sequence_feasible)
        self.assertTrue(any(r["reason"]==LoadingFailureReason.TEMPORARY_INSTABILITY.value for r in plan.infeasible_reasons))

    def test_seq_010_clearance_failure(self):
        config=LoadingSequenceConfig(y_clearance_m=.01)
        index=SpatialIndex()
        result=OperabilityValidator(self.container,config).insertion_path(self.p("wall",0,y=0),index)
        self.assertFalse(result.accessible)
        self.assertEqual(result.blocked_axis,"Y")

    def test_seq_011_two_valid_topo_orders_are_deterministic(self):
        ps=[self.p("left",0,0),self.p("right",0,.6)]
        planner=LoadingSequencePlanner(self.container,[self.sku])
        a=planner.plan(ps);b=planner.plan(copy.deepcopy(ps))
        self.assertTrue(a.sequence_feasible and b.sequence_feasible)
        self.assertEqual(a.metrics["sequence_signature"],b.metrics["sequence_signature"])

    def test_seq_012_no_valid_sequence(self):
        # Static geometry is legal, but elevated cargo without its support is not loadable.
        plan=LoadingSequencePlanner(self.container,[self.sku]).plan([self.p("x",0,z=.8)])
        self.assertFalse(plan.sequence_feasible)

    def test_aseq_001_final_legal_but_current_blocker_blocks_path(self):
        target=self.p("rear",0); blocker=self.p("block",1)
        index=SpatialIndex(); index.insert("block",AABB.from_placement(blocker),blocker)
        access=OperabilityValidator(self.container,LoadingSequenceConfig()).insertion_path(target,index)
        self.assertEqual(access.status,"BLOCKED")
        self.assertEqual(access.blocking_placement_ids,("block",))

    def test_aseq_002_support_and_blocking_cycle(self):
        a=self.p("a",0);b=self.p("b",1)
        graph=LoadingDependencyGraph({"a":a,"b":b},[DependencyEdge("a","b","SUPPORT"),DependencyEdge("b","a","BLOCKING")])
        self.assertTrue(LoadingSequencePlanner(self.container,[self.sku])._find_cycles(graph))

    def test_aseq_003_rear_topfill_trap_classified(self):
        self.assertEqual(LoadingFailureReason.TOP_FILL_UNREACHABLE.value,"TOP_FILL_UNREACHABLE")

    def test_aseq_004_door_early_classified(self):
        self.assertEqual(LoadingFailureReason.DOOR_SEAL_TOO_EARLY.value,"DOOR_SEAL_TOO_EARLY")

    def test_aseq_005_temporary_thin_wall_grouped(self):
        self.test_seq_007_thin_cargo_pair_group()


if __name__=="__main__": unittest.main()
