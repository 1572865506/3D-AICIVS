"""Thread-safe in-memory loading-job API and product adapter orchestration."""
import threading
from urllib.parse import parse_qs,urlparse

from backend.api.adapters import LayoutAdapter,RepairAdapter,SceneAdapter,SequenceAdapter
from backend.api.routes import (get_animation,get_camera,get_cargo,get_container,get_export,
                                get_highlight,get_layout,get_repair,get_scene,get_sequence,get_walls)
from backend.api.schemas import ResponseValidator
from backend.solver_v2.loading import LoadingSequencePlanner,SequenceRepairEngine


class LoadingJobStore:
    def __init__(self):self._records={};self._lock=threading.RLock()
    def put(self,job_id,result):
        with self._lock:self._records[job_id]=result
    def get(self,job_id):
        with self._lock:return self._records.get(job_id)
    def clear(self):
        with self._lock:self._records.clear()


def build_loading_result(job_id,container,cargo,placements,plan,repair_result=None,solver_metrics=None,recomposition=None):
    final_plan=repair_result.updated_loading_plan if repair_result and repair_result.repaired else plan
    repair_groups=repair_result.groups if repair_result and repair_result.repaired else []
    cargo_model=LayoutAdapter.cargo(placements,cargo,container,final_plan,repair_groups,recomposition)
    walls=LayoutAdapter.walls(placements,container)
    sequence=SequenceAdapter.sequence(final_plan,repair_groups)
    placement_map={p.placement_id:p for p in placements}
    result={"id":job_id,"container":LayoutAdapter.container(container),"cargo":cargo_model,
            "walls":walls,"sequence":sequence,"repair":RepairAdapter.adapt(repair_result),
            "scene":SceneAdapter.scene(cargo_model,container),
            "animation":SequenceAdapter.animation(final_plan,placement_map,container),
            "camera":SceneAdapter.camera(container),
            "metrics":{"placement_count":len(placements),"wall_count":len(walls),
                       "sequence_steps":len(sequence["steps"]),"sequence_feasible":final_plan.sequence_feasible,
                       **(solver_metrics or {})},"version":"BLK007C"}
    ResponseValidator.validate_result(result)
    return result


class LoadingAPIService:
    def __init__(self,store=None):self.store=store or LoadingJobStore()

    def register_solver_output(self,job_id,solution,container,cargo):
        planner=LoadingSequencePlanner(container,cargo);plan=planner.plan(solution.placements);repair=None
        if not plan.sequence_feasible and plan.infeasible_reasons and plan.infeasible_reasons[0].get("reason")=="TEMPORARY_INSTABILITY":
            repair=SequenceRepairEngine(container,cargo).repair(
                plan,plan.infeasible_reasons[0],plan.graph,solution.placements)
        recomposition=(solution.telemetry.wall_plan_search_metrics or {}).get("cargo_recomposition")
        result=build_loading_result(job_id,container,cargo,solution.placements,plan,repair,
            {"utilization_pct":solution.volume_utilization_pct,"total_weight_kg":solution.total_weight_kg},recomposition)
        self.store.put(job_id,result);return result

    def put_result(self,result):
        ResponseValidator.validate_result(result);self.store.put(result["id"],result)

    def dispatch(self,path):
        parsed=urlparse(path);parts=[p for p in parsed.path.split("/") if p]
        if len(parts)<4 or parts[:3] != ["api","v1","loading"]:
            return None
        job_id=parts[3];record=self.store.get(job_id)
        if record is None:return 404,{"error":"LOADING_JOB_NOT_FOUND","id":job_id,"version":"BLK007C"}
        if len(parts)==4:return 200,record
        endpoint=parts[4]
        routes={"layout":get_layout,"container":get_container,"cargo":get_cargo,"walls":get_walls,
                "sequence":get_sequence,"repair":get_repair,"scene":get_scene,"animation":get_animation,
                "camera":get_camera,"export":get_export}
        if endpoint=="highlight":
            query=parse_qs(parsed.query);kind=(query.get("type") or ["object"])[0];value=(query.get("id") or [""])[0]
            return 200,get_highlight(record,kind,value)
        handler=routes.get(endpoint)
        if handler is None:return 404,{"error":"LOADING_ENDPOINT_NOT_FOUND","endpoint":endpoint,"version":"BLK007C"}
        return 200,handler(record)


DEFAULT_LOADING_API=LoadingAPIService()
