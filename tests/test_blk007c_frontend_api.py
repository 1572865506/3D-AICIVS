"""API-001..006 plus Solver -> API -> Three.js integration contract."""
import copy
import json
import time
import unittest

from backend.api.schemas import ResponseValidator
from backend.api.service import LoadingAPIService,LoadingJobStore,build_loading_result
from backend.solver_v2.domain.models import (BoxDim,CargoSKU,ContainerSpec,Orientation3D,
    Placement,PlacementContext,Point3D,QuantityPlan,StackingPolicy)
from backend.solver_v2.loading import LoadingSequencePlanner,SequenceRepairEngine


class TestBLK007CFrontendAPI(unittest.TestCase):
    def setUp(self):
        self.container=ContainerSpec("40HQ",BoxDim(4,1.2,1.5),3000,door_zone_length_m=.4)
        self.sku=CargoSKU("T","Thin Cargo",BoxDim(.4,.12,.8),4,QuantityPlan(10),
                          stacking_policy=StackingPolicy(max_bearing_kg=200),color_hex=0x3B82F6)
        self.a=self.p("a",.3);self.b=self.p("b",.42)
        planner=LoadingSequencePlanner(self.container,[self.sku]);failed=planner.plan([self.a])
        repair=SequenceRepairEngine(self.container,[self.sku]).repair(
            failed,failed.infeasible_reasons[0],failed.graph,[self.a,self.b])
        self.result=build_loading_result("job001",self.container,[self.sku],[self.a,self.b],failed,repair,
                                         {"utilization_pct":1.0})
        self.service=LoadingAPIService(LoadingJobStore());self.service.put_result(self.result)

    def p(self,pid,y):
        return Placement(pid,"i"+pid,"T",Point3D(.5,y,0),Orientation3D(.4,.12,.8,"UPRIGHT"),4,
                         PlacementContext.MAIN_WALL)

    def get(self,endpoint):
        status,payload=self.service.dispatch(f"/api/v1/loading/job001/{endpoint}")
        self.assertEqual(status,200);return payload

    def test_api_001_container_response(self):
        data=self.get("container")
        self.assertEqual(data["coordinate_system"]["origin"],"container_back_bottom_left")
        self.assertEqual(data["door"]["plane_x"],self.container.Lx)

    def test_api_002_cargo_response(self):
        data=self.get("cargo");self.assertEqual(data["count"],2)
        self.assertEqual(data["cargo"][0]["position"],{"x":.5,"y":.3,"z":0})
        self.assertEqual(data["cargo"][0]["size"],{"w":.4,"d":.12,"h":.8})

    def test_api_003_sequence_response(self):
        sequence=self.get("sequence")
        ordered=[pid for step in sequence["steps"] for pid in step["placements"]]
        self.assertEqual(set(ordered),{"a","b"});self.assertTrue(sequence["feasible"])

    def test_api_004_repair_response(self):
        repair=self.get("repair");self.assertTrue(repair["enabled"] and repair["repaired"])
        self.assertEqual(repair["groups"][0]["type"],"PAIR")

    def test_api_005_invalid_loading_id(self):
        status,data=self.service.dispatch("/api/v1/loading/missing/layout")
        self.assertEqual(status,404);self.assertEqual(data["error"],"LOADING_JOB_NOT_FOUND")

    def test_api_006_schema_validation(self):
        self.assertTrue(ResponseValidator.validate_result(self.result))
        invalid=copy.deepcopy(self.result);del invalid["cargo"][0]["position"]
        with self.assertRaises(ValueError):ResponseValidator.validate_result(invalid)

    def test_solver_api_threejs_data_consistency(self):
        layout=self.get("layout");scene=self.get("scene");animation=self.get("animation")
        self.assertEqual(len(layout["cargo"]),len(scene["objects"]))
        by_id={x["id"]:x for x in layout["cargo"]};obj={x["uuid"]:x for x in scene["objects"]}["a"]
        self.assertEqual(obj["scale"],[by_id["a"]["size"][k] for k in ("w","d","h")])
        self.assertEqual(animation["total_frames"],layout["sequence"]["total_steps"])


if __name__=="__main__":unittest.main()
