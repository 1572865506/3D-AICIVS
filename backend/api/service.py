"""Thread-safe in-memory loading-job API and product adapter orchestration."""
import threading
import time
from collections import OrderedDict
from typing import Any, List, Optional, Tuple
from urllib.parse import parse_qs,urlparse

from backend.api.adapters import LayoutAdapter,RepairAdapter,SceneAdapter,SequenceAdapter
from backend.api.routes import (get_animation,get_camera,get_cargo,get_container,get_export,
                                get_highlight,get_layout,get_repair,get_scene,get_sequence,get_walls)
from backend.api.schemas import ResponseValidator
from backend.solver_v2.loading import LoadingSequencePlanner,SequenceRepairEngine


class LoadingJobStore:
    """有界 Job 存储：LRU（max_jobs）+ 空闲 TTL；淘汰时返回被清理的 job_id。

    注意：淘汰回调不能在 store 锁内调用 service 的 plan 锁（会形成 ABBA 死锁），
    因此所有 put/get/clear 都返回 evicted ids，由 LoadingAPIService 在锁外清理。
    """

    def __init__(self, max_jobs: int = 32, ttl_s: float = 3600.0, clock=None):
        self._records = OrderedDict()
        self._lock = threading.RLock()
        self._max_jobs = max(1, int(max_jobs))
        self._ttl_s = max(1.0, float(ttl_s))
        self._clock = clock or time.monotonic

    def put(self, job_id: str, result: Any) -> List[str]:
        with self._lock:
            now = self._clock()
            self._records[job_id] = {
                "result": result,
                "created_at": now,
                "last_access": now,
            }
            self._records.move_to_end(job_id)
            return self._evict_locked(now, protect=job_id)

    def get(self, job_id: str) -> Tuple[Optional[Any], List[str]]:
        with self._lock:
            now = self._clock()
            evicted = self._evict_locked(now, protect=None)
            entry = self._records.get(job_id)
            if entry is None:
                return None, evicted
            if now - float(entry["last_access"]) > self._ttl_s:
                self._records.pop(job_id, None)
                evicted.append(job_id)
                return None, evicted
            entry["last_access"] = now
            self._records.move_to_end(job_id)
            return entry["result"], evicted

    def clear(self) -> List[str]:
        with self._lock:
            ids = list(self._records.keys())
            self._records.clear()
            return ids

    def __len__(self):
        with self._lock:
            return len(self._records)

    def _evict_locked(self, now: float, protect: Optional[str]) -> List[str]:
        evicted: List[str] = []
        for job_id, entry in list(self._records.items()):
            if now - float(entry["last_access"]) > self._ttl_s:
                self._records.pop(job_id, None)
                evicted.append(job_id)
        while len(self._records) > self._max_jobs:
            oldest = next(iter(self._records))
            if protect is not None and oldest == protect:
                break
            self._records.popitem(last=False)
            evicted.append(oldest)
        return evicted


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
    def __init__(self,store=None):
        self.store=store or LoadingJobStore()
        # 多方案：job_id -> {container, cargo, entries:[{key,label,recommended,evaluation,solution,loading_result}]}
        # 按需构建备选的完整 LoadingResult（切换方案时才付序列化成本）。
        self._plans={}
        self._plan_lock=threading.RLock()

    def register_solver_output(self,job_id,solution,container,cargo,
                               plan_score=None,plans=None,recommended_plan=None,
                               plan_group_id=None,learning_suggestion=None,
                               store_result: bool = True,sequence_report=None):
        from backend.solver_v2.loading.planner import LoadingStep, LoadingPlan, LoadingDependencyGraph
        if sequence_report is None:
            # 物理可执行装载顺序（拓扑排序）：替换此前"按 placements 枚举下标"的假顺序
            from backend.solver_v2.loading.sequence_planner import compute_loading_order
            seq_report = compute_loading_order(solution.placements, container)
        else:
            seq_report = sequence_report
        by_id = {p.placement_id: p for p in solution.placements}
        ordered = [by_id[pid] for pid in seq_report["order"] if pid in by_id]
        solution_placements_ordered = ordered if ordered else list(solution.placements)
        steps = [
            LoadingStep(
                step_index=idx + 1,
                placement_ids=(p.placement_id,),
                action="LOAD",
                insertion_paths=[{"start_x": container.Lx, "accessible": True}],
                required_clearance={},
                blocking_check={},
                support_after_step={},
                stability_after_step={},
                wall_id="WALL_0",
                row_id="ROW_0",
                layer_id="LAYER_0",
                phase=str(p.context.value if hasattr(p.context, 'value') else p.context)
            )
            for idx, p in enumerate(solution_placements_ordered)
        ]
        plan = LoadingPlan(
            static_feasible=solution.validation_result.is_valid if solution.validation_result is not None else True,
            sequence_feasible=bool(seq_report["feasible"]),
            steps=steps,
            graph=LoadingDependencyGraph(nodes={p.placement_id: p for p in solution.placements}, edges=[]),
            groups=[],
            infeasible_reasons=[],
            debts=[],
            metrics={"sequence_signature": f"sig_{job_id}", "total_steps": len(steps)},
            repair_requests=[],
            runtime_sec=0.01
        )
        repair = None
        recomposition = (solution.telemetry.wall_plan_search_metrics or {}).get("cargo_recomposition")
        braking = (solution.telemetry.wall_plan_search_metrics or {}).get("braking_stability")
        from backend.solver_v2.validation.delivery_gate import evaluate_delivery
        delivery_gate = evaluate_delivery(solution, cargo, container, sequence_report=seq_report)
        result = build_loading_result(
            job_id, container, cargo, solution.placements, plan, repair,
            {"utilization_pct": solution.volume_utilization_pct, "total_weight_kg": solution.total_weight_kg,
             "loading_order_feasible": bool(seq_report["feasible"]),
             "loading_order_edges": seq_report["edge_count"],
             "blocked_in_naive_order": seq_report["blocked_in_naive_order"],
             "sequence_cycles": len(seq_report["cycles"]),
             "braking_stability": braking,
             "geometry_qa": solution.telemetry.geometry_qa,
             # 归一化空腔清单（box/volume_m3/dims/open/category），供前端叠加渲染
             "cavities": ((solution.telemetry.geometry_qa or {}).get("cavities") or {}).get("top") or [],
            "lns_metrics": solution.telemetry.lns_metrics,
            "plan_score": plan_score,
            "plans": plans or [],
            "recommended_plan": recommended_plan,
            "plan_group_id": plan_group_id or job_id,
            "learning_suggestion": learning_suggestion,
            "delivery_gate": delivery_gate},
            recomposition
        )
        if store_result:
            evicted = self.store.put(job_id, result)
            self._drop_plans(evicted)
        return result

    def _drop_plans(self, job_ids: List[str]) -> None:
        if not job_ids:
            return
        with self._plan_lock:
            for job_id in job_ids:
                self._plans.pop(job_id, None)

    def clear(self) -> None:
        """清空 job 与备选方案缓存（测试/运维用）。"""
        evicted = self.store.clear()
        self._drop_plans(evicted)
        with self._plan_lock:
            self._plans.clear()

    def register_alternatives(self,job_id,entries,container,cargo):
        """登记同一货单的候选方案，供 GET /loading/{id}/plans/{idx} 按需构建。

        entries: [{key,label,recommended,evaluation,solution}]；solution 必须已带
        telemetry.geometry_qa（求解器产出时已计算），避免切换方案时重算几何。
        单方案（<=1 entry）不保留备选包，避免每个 job 都常驻一份完整 solution。
        """
        normalized = [{
            "key":e.get("key"),
            "label":e.get("label"),
            "recommended":bool(e.get("recommended")),
            "evaluation":e.get("evaluation"),
            "solution":e.get("solution"),
            "sequence_report":e.get("sequence_report"),
            "loading_result":None,
            "lock":threading.Lock(),
        } for e in (entries or [])]
        with self._plan_lock:
            if not normalized or (len(normalized) <= 1 and normalized[0]["recommended"]):
                self._plans.pop(job_id, None)
                return
            self._plans[job_id]={
                "container":container,
                "cargo":cargo,
                "entries":normalized,
            }

    def _handle_plans(self,job_id,record,rest):
        """GET /loading/{job}/plans 与 /loading/{job}/plans/{idx}。"""
        with self._plan_lock:
            bundle=self._plans.get(job_id)
        if bundle is None:
            return 404,{"error":"LOADING_PLANS_NOT_FOUND","id":job_id,"version":"BLK007C"}
        entries=bundle["entries"]
        if not rest:
            return 200,{"id":job_id,"plans":[{
                "key":e["key"],"label":e["label"],"recommended":e["recommended"],
                "score":(e.get("evaluation") or {}).get("score"),
                "grade":(e.get("evaluation") or {}).get("grade"),
                "metrics":(e.get("evaluation") or {}).get("metrics"),
                "deductions":(e.get("evaluation") or {}).get("deductions") or [],
            } for e in entries]}
        try:
            idx=int(rest[0])
        except (TypeError,ValueError):
            return 400,{"error":"INVALID_PLAN_INDEX","id":job_id,"version":"BLK007C"}
        if idx<0 or idx>=len(entries):
            return 404,{"error":"PLAN_NOT_FOUND","id":job_id,"index":idx,"version":"BLK007C"}
        entry=entries[idx]
        # 推荐方案与主记录是同一份结果，直接复用，切换回推荐方案不重算。
        if entry["recommended"]:
            return 200,record
        if entry["loading_result"] is not None:
            return 200,entry["loading_result"]
        lock=entry.get("lock") or threading.Lock()
        with lock:
            # 双检：并发请求只构建一次
            if entry["loading_result"] is None:
                evaluation=entry.get("evaluation") or {}
                public={k:v for k,v in evaluation.items() if k!="qa"}
                try:
                    entry["loading_result"]=self.register_solver_output(
                        f"{job_id}__plan_{idx}", entry["solution"],
                        bundle["container"], bundle["cargo"],
                        plan_score=public,
                        plans=(record.get("metrics") or {}).get("plans") or [],
                        recommended_plan=(record.get("metrics") or {}).get("recommended_plan"),
                        plan_group_id=job_id,
                        learning_suggestion=(record.get("metrics") or {}).get("learning_suggestion"),
                        store_result=False,
                        sequence_report=entry.get("sequence_report"),
                    )
                except Exception as exc:
                    return 500,{"error":"PLAN_BUILD_FAILED","id":job_id,
                                "index":idx,"detail":str(exc),"version":"BLK007C"}
        return 200,entry["loading_result"]

    def put_result(self,result):
        ResponseValidator.validate_result(result)
        evicted=self.store.put(result["id"],result)
        self._drop_plans(evicted)

    def dispatch(self,path):
        parsed=urlparse(path);parts=[p for p in parsed.path.split("/") if p]
        if len(parts)<4 or parts[:3] != ["api","v1","loading"]:
            return None
        job_id=parts[3];record,evicted=self.store.get(job_id)
        self._drop_plans(evicted)
        if record is None:return 404,{"error":"LOADING_JOB_NOT_FOUND","id":job_id,"version":"BLK007C"}
        if len(parts)==4:return 200,record
        endpoint=parts[4]
        if endpoint=="plans":return self._handle_plans(job_id,record,parts[5:])
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
