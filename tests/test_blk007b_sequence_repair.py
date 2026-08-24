"""BLK-007B unit and REP-001..005 sequence-repair tests."""
import unittest

from backend.solver_v2.domain.models import (
    BoxDim,CargoSKU,ContainerSpec,Orientation3D,Placement,PlacementContext,
    Point3D,QuantityPlan,StackingPolicy,
)
from backend.solver_v2.loading import LoadingSequencePlanner
from backend.solver_v2.loading.planner import DependencyEdge,LoadingDependencyGraph
from backend.solver_v2.loading.repair import (
    LoadingGroup,LoadingGroupBuilder,RepairCandidate,RepairScorer,RepairValidator,
    SequenceRepairEngine,TemporaryDebtPolicy,TemporaryStabilityResolver,
)


class TestBLK007BSequenceRepair(unittest.TestCase):
    def setUp(self):
        self.container=ContainerSpec("REP",BoxDim(4,1.2,1.5),3000,door_zone_length_m=.4)
        self.thin=CargoSKU("T","thin",BoxDim(.4,.12,.8),4,QuantityPlan(10),
                           stacking_policy=StackingPolicy(max_bearing_kg=200))
        self.planner=LoadingSequencePlanner(self.container,[self.thin])

    def p(self,pid,y=.3):
        return Placement(pid,"i"+pid,"T",Point3D(.5,y,0),
                         Orientation3D(.4,.12,.8,"UPRIGHT",is_upright=True),4,
                         PlacementContext.MAIN_WALL)

    def failed_plan(self,target):
        return self.planner.plan([target])

    def test_pair_group_create(self):
        a,b=self.p("a"),self.p("b",.42)
        g=LoadingGroupBuilder().build((a,b),"PAIR","repair","SAME_ROW",.12)
        self.assertEqual(g.type,"PAIR");self.assertEqual(g.placement_ids,("a","b"))

    def test_thin_cargo_detect(self):
        self.assertTrue(LoadingGroupBuilder(.35).is_thin_cargo(self.p("a")))

    def test_temp_stability_resolve(self):
        a,b=self.p("a"),self.p("b",.42);original=self.failed_plan(a)
        result=SequenceRepairEngine(self.container,[self.thin]).repair(
            original,original.infeasible_reasons[0],original.graph,[a,b])
        self.assertTrue(result.validation_result["temporary_stability_resolved"])

    def test_repair_score_compare(self):
        pair=LoadingGroup("p",("a","b"),"PAIR","r",stability_after=True)
        wall=LoadingGroup("w",("a","b","c","d"),"WALL_SEGMENT","r",stability_after=True)
        scorer=RepairScorer()
        self.assertGreater(scorer.score(pair).total,scorer.score(wall).total)

    def test_rep_001_single_thin_unstable_pair_stable(self):
        a,b=self.p("a"),self.p("b",.42);original=self.failed_plan(a)
        self.assertFalse(original.sequence_feasible)
        repaired=SequenceRepairEngine(self.container,[self.thin]).repair(
            original,original.infeasible_reasons[0],original.graph,[a,b])
        self.assertTrue(repaired.repaired);self.assertTrue(repaired.updated_loading_plan.sequence_feasible)

    def test_rep_002_pair_invalid(self):
        a,b=self.p("a"),self.p("b",.9);graph,member,_=self.planner.build_dependency_graph([a,b])
        candidate=RepairCandidate(LoadingGroup("g",("a","b"),"PAIR","r"))
        RepairValidator(self.planner,TemporaryStabilityResolver()).validate(candidate,graph,[a,b],member)
        self.assertFalse(candidate.valid);self.assertEqual(candidate.rejection_reason,"PAIR_NOT_PHYSICALLY_COHERENT")

    def test_rep_003_group_dependency_cycle(self):
        a,b=self.p("a"),self.p("b",.42)
        graph=LoadingDependencyGraph({"a":a,"b":b},[
            DependencyEdge("a","b","SUPPORT"),DependencyEdge("b","a","BLOCKING")])
        group=LoadingGroup("g",("a","b"),"PAIR","r")
        self.assertFalse(RepairValidator.group_preserves_dag(group,graph))

    def test_rep_004_debt_cannot_resolve(self):
        a,b=self.p("a"),self.p("b",.42);original=self.failed_plan(a)
        engine=SequenceRepairEngine(self.container,[self.thin],debt_policy=TemporaryDebtPolicy(allowed=False))
        result=engine.repair(original,original.infeasible_reasons[0],original.graph,[a,b])
        self.assertFalse(result.repaired)

    def test_rep_005_minimal_repair_selection(self):
        a,b,c=self.p("a"),self.p("b",.42),self.p("c",.54);original=self.failed_plan(a)
        result=SequenceRepairEngine(self.container,[self.thin]).repair(
            original,original.infeasible_reasons[0],original.graph,[a,b,c])
        self.assertTrue(result.repaired);self.assertEqual(len(result.groups[0].placement_ids),2)


if __name__=="__main__":unittest.main()
