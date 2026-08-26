import unittest

from backend.solver_v2.domain.models import (BoxDim,CargoSKU,ContainerSpec,Orientation3D,Placement,
    PlacementContext,Point3D,QuantityPlan,StackingPolicy)
from src.optimization.multisku_wall import (AboveCargoAdmissionResolver,
    MultiSkuWallRecompositionEngine,WallProblemDetector)


def cargo(sku,quantity=3,stack=None):
    return CargoSKU(sku,sku,BoxDim(.5,.5,.5),10,QuantityPlan(quantity),
                    stacking_policy=stack or StackingPolicy())


def placement(wall,index,sku,x,y,z=0):
    return Placement(f"cargo_wall_{wall:03d}_{sku}_{index:03d}",f"{sku}_{wall}_{index}",sku,
        Point3D(x,y,z),Orientation3D(.5,.5,.5,"UPRIGHT_NORMAL",is_upright=True),10,
        PlacementContext.MAIN_WALL,index)


class TestMultiSkuWallJointRecomposition(unittest.TestCase):
    def setUp(self):
        self.container=ContainerSpec("JOINT",BoxDim(3,2,1),10000,door_zone_length_m=0)
        self.a=cargo("A");self.b=cargo("B")
        self.layout=tuple(
            [placement(1,i,"A",0,.25+i*.5) for i in range(3)]+
            [placement(2,i,"B",.7,.25+i*.5) for i in range(3)])

    def test_mswall_001_two_skus_form_one_joint_structure(self):
        result=MultiSkuWallRecompositionEngine().recompose(self.container,(self.a,self.b),self.layout)
        self.assertEqual(result.status,"SUCCESS")
        self.assertTrue(result.selected)
        self.assertGreaterEqual(len(result.selected[0].blueprint.sku_mix),2)
        self.assertLess(result.metrics["inter_wall_gap_m_after"],result.metrics["inter_wall_gap_m_before"])
        self.assertTrue(result.validation.is_valid)

    def test_mswall_002_single_sku_is_not_forced_to_fake_diversity(self):
        layout=tuple(placement(1,i,"A",0,.25+i*.5) for i in range(3))
        result=MultiSkuWallRecompositionEngine().recompose(self.container,(self.a,),layout)
        self.assertTrue(result.validation.is_valid)
        self.assertTrue(all(len(candidate.blueprint.sku_mix)==1 for candidate in result.candidates))

    def test_mswall_003_centered_wall_becomes_side_anchored(self):
        result=MultiSkuWallRecompositionEngine().recompose(self.container,(self.a,self.b),self.layout)
        selected=[p for p in result.placements if p.placement_id.startswith("cargo_wall_")]
        self.assertTrue(abs(min(p.min_y for p in selected))<1e-9 or
                        abs(max(p.max_y for p in selected)-self.container.Ly)<1e-9)

    def test_mswall_004_problem_detection_is_geometry_driven(self):
        regions=WallProblemDetector().detect(self.container,self.layout)
        self.assertTrue(regions)
        self.assertIn("INTER_WALL_GAP",regions[0].problem_types)
        self.assertIn("CENTERED_WALL",regions[0].problem_types)

    def test_mswall_005_self_layer_limit_does_not_ban_other_sku_above(self):
        lower=cargo("LOW",3,StackingPolicy(max_stack_layers=3,max_bearing_kg=100,min_support_ratio=.7))
        upper=cargo("UP",1)
        allowed,reason=AboveCargoAdmissionResolver().resolve(lower,upper,10,.9)
        self.assertTrue(allowed);self.assertEqual(reason,"AUTO_PASS")

    def test_mswall_006_explicit_top_load_is_still_hard(self):
        lower=cargo("LOW",3,StackingPolicy(max_stack_layers=3,max_bearing_kg=0,min_support_ratio=.7))
        upper=cargo("UP",1)
        allowed,reason=AboveCargoAdmissionResolver().resolve(lower,upper,10,1.0)
        self.assertFalse(allowed);self.assertEqual(reason,"COMPRESSION_FAIL")

    def test_mswall_007_deterministic_replay(self):
        engine=MultiSkuWallRecompositionEngine()
        a=engine.recompose(self.container,(self.a,self.b),self.layout)
        b=engine.recompose(self.container,(self.a,self.b),self.layout)
        self.assertEqual(tuple(p.aabb() for p in a.placements),tuple(p.aabb() for p in b.placements))
        self.assertEqual(a.to_dict(),b.to_dict())

    def test_mswall_008_insufficient_support_remains_rejected(self):
        allowed,reason=AboveCargoAdmissionResolver().resolve(self.a,self.b,10,.5)
        self.assertFalse(allowed);self.assertEqual(reason,"SUPPORT_FAIL")

    def test_mswall_009_inventory_is_never_overdrawn(self):
        result=MultiSkuWallRecompositionEngine().recompose(self.container,(self.a,self.b),self.layout)
        counts={sku:sum(p.sku_id==sku for p in result.placements) for sku in ("A","B")}
        self.assertLessEqual(counts["A"],self.a.quantity.required)
        self.assertLessEqual(counts["B"],self.b.quantity.required)

    def test_mswall_010_all_selected_candidates_are_hard_valid(self):
        result=MultiSkuWallRecompositionEngine().recompose(self.container,(self.a,self.b),self.layout)
        self.assertTrue(all(candidate.validation.is_valid for candidate in result.selected))

    def test_mswall_011_locked_door_geometry_is_untouched(self):
        door=Placement("door_pre_0001","door_i","A",Point3D(2.5,0,0),
            Orientation3D(.5,.5,.5,"UPRIGHT_NORMAL",is_upright=True),10,PlacementContext.DOOR_SEAL,99)
        result=MultiSkuWallRecompositionEngine().recompose(self.container,(cargo("A",4),self.b),self.layout+(door,))
        actual=next(p for p in result.placements if p.placement_id==door.placement_id)
        self.assertEqual(actual,door)

    def test_mswall_012_no_new_orientation_rights_are_invented(self):
        result=MultiSkuWallRecompositionEngine().recompose(self.container,(self.a,self.b),self.layout)
        original={p.placement_id:p.orientation.name for p in self.layout}
        self.assertTrue(all(p.orientation.name==original[p.placement_id] for p in result.placements if p.placement_id in original))


if __name__=="__main__":unittest.main()
