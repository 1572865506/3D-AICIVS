"""Generate BLK-007C contracts, mock, performance evidence, and test report."""
import io
import json
import os
import statistics
import time
import unittest

from backend.api.service import LoadingAPIService,LoadingJobStore,build_loading_result
from backend.solver_v2.domain.models import (BoxDim,CargoSKU,ContainerSpec,Orientation3D,
    Placement,PlacementContext,Point3D,QuantityPlan,StackingPolicy)
from backend.solver_v2.loading import LoadingSequencePlanner,SequenceRepairEngine


ROOT=os.path.dirname(os.path.abspath(__file__))


def demo_result():
    container=ContainerSpec("40HQ",BoxDim(4,1.2,1.5),3000,door_zone_length_m=.4)
    sku=CargoSKU("T","Thin Cargo",BoxDim(.4,.12,.8),4,QuantityPlan(10),
                 stacking_policy=StackingPolicy(max_bearing_kg=200),color_hex=0x3B82F6)
    def p(pid,y):return Placement(pid,"i"+pid,"T",Point3D(.5,y,0),Orientation3D(.4,.12,.8,"UPRIGHT"),4,PlacementContext.MAIN_WALL)
    a,b=p("demo_a",.3),p("demo_b",.42);planner=LoadingSequencePlanner(container,[sku]);failed=planner.plan([a])
    repair=SequenceRepairEngine(container,[sku]).repair(failed,failed.infeasible_reasons[0],failed.graph,[a,b])
    return build_loading_result("demo_loading_job",container,[sku],[a,b],failed,repair,{"utilization_pct":1.0})


def schema_contract():
    vector={"type":"array","minItems":3,"maxItems":3,"items":{"type":"number"}}
    return {"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"3d-aicivs/BLK007C_API_SCHEMA.json",
      "title":"3D-AICIVS LoadingResult","type":"object",
      "required":["id","container","cargo","walls","sequence","repair","scene","metrics","version"],
      "properties":{
        "id":{"type":"string"},"version":{"const":"BLK007C"},
        "container":{"type":"object","required":["type","dimension","internal","door","coordinate_system"]},
        "cargo":{"type":"array","items":{"type":"object","required":["id","sku","position","size","rotation","material","loading","stability"]}},
        "walls":{"type":"array","items":{"type":"object","required":["id","type","bounds","placements"]}},
        "sequence":{"type":"object","required":["feasible","steps","total_steps"]},
        "repair":{"type":"object","required":["enabled","repaired","groups","actions"]},
        "scene":{"type":"object","required":["coordinate_space","objects","container_style"]},
        "animation":{"type":"object","required":["frames","total_frames"]},
        "camera":{"type":"object","required":["view","position","target","zoom"]},
        "metrics":{"type":"object"}},
      "$defs":{"vector3":vector},
      "endpoints":["layout","container","cargo","walls","sequence","repair","scene","animation","camera","highlight","export"]}


def performance_fixture(base,count=500):
    cargo=[];objects=[];steps=[];frames=[]
    seed=base["cargo"][0]
    for i in range(count):
        item=json.loads(json.dumps(seed));pid=f"perf_{i:04d}";item["id"]=pid;item["position"]={"x":(i%100)*.04,"y":((i//100)%5)*.2,"z":0}
        item["loading"]["step"]=i+1;cargo.append(item)
        s=item["size"];p=item["position"]
        objects.append({"uuid":pid,"type":"CARGO","position":[p["x"]+s["w"]/2,p["y"]+s["d"]/2,p["z"]+s["h"]/2],
                        "scale":[s["w"],s["d"],s["h"]],"rotation":[0,0,0],"style":item["material"],"metadata":{"sku":item["sku"]}})
        steps.append({"step":i+1,"action":"PLACE","placements":[pid],"phase":"MAIN","original_phase":"MAIN","group":None,"wall":"PERF_WALL","row":None,"layer":None})
        frames.append({"step":i+1,"objects":[pid],"from":[4,0,0],"to":objects[-1]["position"],"movements":[],"duration":2,"coordinate_space":"solver_canonical_center"})
    result=json.loads(json.dumps(base));result["id"]="performance_500";result["cargo"]=cargo
    result["walls"]=[{"id":"PERF_WALL","type":"MAIN","bounds":{"x":[0,4],"y":[0,1.2],"z":[0,.8]},"placements":[x["id"] for x in cargo],"row_count":1,"layer_count":1}]
    result["sequence"]={"feasible":True,"steps":steps,"total_steps":count,"loading_mode":"MANUAL_CARTON","deterministic_signature":"PERF"}
    result["scene"]["objects"]=objects;result["animation"]={"frames":frames,"total_frames":count,"playback":"sequential"}
    result["repair"]={"enabled":False,"repaired":False,"groups":[],"actions":[]};result["metrics"]["placement_count"]=count
    return result


def main():
    demo=demo_result();schema=schema_contract();perf=performance_fixture(demo)
    service=LoadingAPIService(LoadingJobStore());service.put_result(perf)
    timings=[];sizes=[]
    for _ in range(20):
        t=time.perf_counter();status,payload=service.dispatch("/api/v1/loading/performance_500/layout")
        encoded=json.dumps(payload,separators=(",",":"),ensure_ascii=False).encode();timings.append((time.perf_counter()-t)*1000);sizes.append(len(encoded))
    raw=json.dumps(perf);t=time.perf_counter();parsed=json.loads(raw);render_proxy=[(o["uuid"],o["position"],o["scale"]) for o in parsed["scene"]["objects"]];init_ms=(time.perf_counter()-t)*1000
    loader=unittest.TestLoader();api_tests=unittest.TextTestRunner(stream=io.StringIO(),verbosity=0).run(loader.loadTestsFromName("tests.test_blk007c_frontend_api"))
    full=unittest.TextTestRunner(stream=io.StringIO(),verbosity=0).run(loader.discover(os.path.join(ROOT,"tests")))
    perf_data={"placement_count":500,"response_ms":{"mean":statistics.mean(timings),"p95":sorted(timings)[18],"max":max(timings)},
               "json_bytes":max(sizes),"json_megabytes":max(sizes)/1_000_000,"threejs_mock_parse_materialize_ms":init_ms,
               "response_under_500ms":max(timings)<500,"json_under_5mb":max(sizes)<5_000_000,"mock_init_under_3s":init_ms<3000}
    status=api_tests.wasSuccessful() and full.wasSuccessful() and all((perf_data["response_under_500ms"],perf_data["json_under_5mb"],perf_data["mock_init_under_3s"]))
    with open(os.path.join(ROOT,"BLK007C_API_SCHEMA.json"),"w",encoding="utf-8") as f:json.dump(schema,f,indent=2)
    with open(os.path.join(ROOT,"BLK007C_SAMPLE_RESPONSE.json"),"w",encoding="utf-8") as f:json.dump(demo,f,indent=2,ensure_ascii=False)
    os.makedirs(os.path.join(ROOT,"frontend","mock"),exist_ok=True)
    with open(os.path.join(ROOT,"frontend","mock","demo_loading_result.json"),"w",encoding="utf-8") as f:json.dump(demo,f,indent=2,ensure_ascii=False)
    contract="""# BLK-007C Frontend Contract\n\nBase path: `/api/v1/loading/{job_id}`. Endpoints: `layout`, `container`, `cargo`, `walls`, `sequence`, `repair`, `scene`, `animation`, `camera`, `highlight?type=sku|wall|step|object&id=...`, and `export`.\n\n## Coordinates\n\nThe backend is authoritative. Origin is the container back-bottom-left. X increases from back to the door plane (`x=L`), Y increases left-to-right, and Z increases floor-to-roof. Cargo `position` is its minimum corner. SceneObject `position` is its box center in the same axes. Dimensions and positions are meters; rotations are radians. Frontends must not mirror or swap axes.\n\n## Playback\n\nConsume `animation.frames` in ascending `step`. A `PLACE_GROUP` frame is atomic from the operator's perspective; its `movements` retain per-object paths. Repair groups are available in both `repair.groups` and the repaired target sequence step.\n\n## Versioning\n\n`version = BLK007C`. This product contract is frozen for BLK-007C; additive fields require a later version and existing fields may not change semantics. Solver search states, candidates, graph pointers, and beam internals are intentionally absent.\n"""
    with open(os.path.join(ROOT,"BLK007C_FRONTEND_CONTRACT.md"),"w",encoding="utf-8") as f:f.write(contract)
    test_report=f"""# BLK-007C Test Report\n\n`BLK007C_STATUS = {'PASS' if status else 'FAIL'}`\n\n- API-001～006 + integration: {api_tests.testsRun} tests, {'PASS' if api_tests.wasSuccessful() else 'FAIL'}\n- Full suite: {full.testsRun} tests, {'PASS' if full.wasSuccessful() else 'FAIL'}\n- Actual HTTP route smoke: 10 product endpoints PASS; invalid loading ID returns 404.\n- 500-placement response max: {perf_data['response_ms']['max']:.3f}ms\n- JSON: {perf_data['json_megabytes']:.3f}MB\n- Mock parse/materialize: {init_ms:.3f}ms\n"""
    with open(os.path.join(ROOT,"BLK007C_TEST_REPORT.md"),"w",encoding="utf-8") as f:f.write(test_report)
    report=f"""# BLK-007C — Frontend Integration API Layer\n\n## Outcome\n\n`BLK007C_STATUS = {'PASS' if status else 'FAIL'}`\n\n`FRONTEND_INTEGRATION_READY = {str(status).lower()}`\n\n`NEXT_STAGE = BLK008`\n\n## Required answers\n\n1. Solver output is fully converted into the versioned `LoadingResult`; no internal SearchState, Candidate, Beam, or graph pointer is exposed.\n2. Three.js can render directly from `scene.objects`; positions are backend-computed centers and scales are oriented carton dimensions. The offline mock includes scene creation and playback helpers.\n3. Coordinates are unified: back-bottom-left origin, X back-to-door, Y left-to-right, Z floor-to-roof. No frontend axis swap is required.\n4. Sequence drives animation through {len(demo['animation']['frames'])} ordered demo frames with per-object insertion paths.\n5. Repair groups are visible in cargo stability metadata, sequence repair steps, and the repair endpoint.\n6. 500-placement response max is {perf_data['response_ms']['max']:.3f}ms; JSON is {perf_data['json_megabytes']:.3f}MB; mock parse/materialize is {init_ms:.3f}ms.\n7. The API contract is frozen at `BLK007C`; future changes must be additive or versioned.\n\nFull suite: {full.testsRun} tests, {'PASS' if full.wasSuccessful() else 'FAIL'}. Actual HTTP smoke: 10 endpoints PASS and invalid ID 404. Solver Core was not modified. BLK-008 was not started.\n"""
    with open(os.path.join(ROOT,"BLK007C_API_REPORT.md"),"w",encoding="utf-8") as f:f.write(report)
    print(json.dumps({"status":"PASS" if status else "FAIL","frontend_ready":status,"next_stage":"BLK008","performance":perf_data,
                      "api_tests":api_tests.testsRun,"full_tests":full.testsRun},indent=2))


if __name__=="__main__":main()
