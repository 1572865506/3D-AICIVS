import unittest

from backend.solver_v2.domain.models import (BoxDim,CargoSKU,ContainerSpec,Orientation3D,Placement,
    PlacementContext,Point3D,QuantityPlan)
from src.optimization.multisku_wall import ThreeDLayerRecompositionEngine


def sku(sku_id,quantity):return CargoSKU(sku_id,sku_id,BoxDim(.5,.5,.5),5,QuantityPlan(quantity))


def column(wall,slot,sku_id,x,y,layers,start):
    orientation=Orientation3D(.5,.5,.5,"UPRIGHT_NORMAL",is_upright=True)
    return [Placement(f"cargo_wall_{wall:03d}_{sku_id}_{start+i:03d}",f"{sku_id}_{start+i}",sku_id,
        Point3D(x,y,i*.5),orientation,5,PlacementContext.MAIN_WALL,start+i) for i in range(layers)]


class TestThreeDLayerRecomposition(unittest.TestCase):
    def setUp(self):
        self.container=ContainerSpec("3D",BoxDim(1,1,1),1000,door_zone_length_m=0)
        self.a=sku("A",3);self.b=sku("B",3)
        self.layout=tuple(column(1,0,"A",0,0,2,0)+column(1,1,"B",0,.5,1,2)+
                          column(2,0,"B",.5,0,2,3)+column(2,1,"A",.5,.5,1,5))

    def test_3dlayer_001_equal_footprint_columns_are_exchanged(self):
        result=ThreeDLayerRecompositionEngine().recompose(self.container,(self.a,self.b),self.layout)
        self.assertEqual(result.status,"SUCCESS");self.assertTrue(result.selected)
        self.assertGreater(result.metrics["columns_exchanged"],0)

    def test_3dlayer_002_raggedness_and_incomplete_columns_decrease(self):
        result=ThreeDLayerRecompositionEngine().recompose(self.container,(self.a,self.b),self.layout)
        self.assertGreater(result.metrics["raggedness_reduction_m"],0)
        self.assertGreater(result.metrics["incomplete_columns_reduced"],0)

    def test_3dlayer_003_inventory_and_orientations_are_permuted_not_created(self):
        result=ThreeDLayerRecompositionEngine().recompose(self.container,(self.a,self.b),self.layout)
        self.assertEqual(sorted((p.placement_id,p.sku_id,p.orientation.name) for p in result.placements),
                         sorted((p.placement_id,p.sku_id,p.orientation.name) for p in self.layout))

    def test_3dlayer_004_global_validator_is_authoritative(self):
        result=ThreeDLayerRecompositionEngine().recompose(self.container,(self.a,self.b),self.layout)
        self.assertTrue(result.validation.is_valid)
        self.assertTrue(all(candidate.validation.is_valid for candidate in result.selected))

    def test_3dlayer_005_deterministic_replay(self):
        engine=ThreeDLayerRecompositionEngine()
        first=engine.recompose(self.container,(self.a,self.b),self.layout)
        second=engine.recompose(self.container,(self.a,self.b),self.layout)
        self.assertEqual(tuple(p.aabb() for p in first.placements),tuple(p.aabb() for p in second.placements))


if __name__=="__main__":unittest.main()
