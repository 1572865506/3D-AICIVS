"""3D-AICIVS 独立无状态算柜 Worker 进程。

用途：
    将 CPU 密集型的 UnifiedSolver 装柜求解任务从 HTTP API 网关进程中解耦出来，
    通过本地 SQLite 任务队列（或直接函数调用 / HTTP 回调）实现无状态异步执行，
    便于后续在云端横向扩展多节点 Worker。

输入 / 输出：
    - 输入：标准装柜请求 payload（包含 container/containerSpec、manifest/cargo/sku、
      mode、randomSeed、timeBudgetSec、policy、alternatives 等字段）。
    - 输出：与 `POST /api/v2/pack` 兼容的完整求解结果字典（含 placedBoxes、
      metrics、planScore、plans、scenario 等），并支持写入 SQLite 结果表或推送到 callback_url。

调用方：
    - 独立进程运行：`python -m backend.solver_worker` 或 `python backend/solver_worker.py`
    - 可由 `backend/server.py` 入队任务或由外部调度器/容器编排拉起。
"""

import json
import os
import sqlite3
import sys
import time
import traceback
import urllib.request
from typing import Any, Dict, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from backend.api.request_limits import (
    validate_alternative_budget,
    validate_alternative_profiles,
    validate_alternatives,
    validate_manifest_size,
    validate_seed,
    validate_time_budget,
)
from backend.solver_v2.api.adapter import InputAdapter, OutputAdapter
from backend.solver_v2.evaluation import compare_plans, detect_scenario, evaluate_plan, rank_plans
from backend.solver_v2.evaluation.product import build_product_options
from backend.solver_v2.learning import suggest_policy
from backend.solver_v2.loading.sequence_planner import compute_loading_order
from backend.solver_v2.solver.unified_solver import UnifiedSolver
from backend.solver_v2.validation.config_precheck import precheck_manifest

DEFAULT_WORKER_DB = os.path.join(BASE_DIR, "data", "worker_jobs.db")


def _get_db_path(db_path: Optional[str] = None) -> str:
    return db_path or os.environ.get("AICIVS_WORKER_DB") or DEFAULT_WORKER_DB


def init_worker_db(db_path: Optional[str] = None) -> str:
    """初始化本地 SQLite 任务队列表。"""
    path = _get_db_path(db_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with sqlite3.connect(path, timeout=10.0) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS solver_jobs ("
            "job_id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'pending', "
            "payload_json TEXT NOT NULL, result_json TEXT, error_text TEXT, "
            "callback_url TEXT, worker_id TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_solver_jobs_status ON solver_jobs(status, created_at)")
    return path


def enqueue_solve_job(
    payload: Dict[str, Any], job_id: Optional[str] = None,
    callback_url: Optional[str] = None, db_path: Optional[str] = None,
) -> str:
    """向 SQLite 队列提交一个无状态算柜任务，返回 job_id。"""
    path = init_worker_db(db_path)
    jid = job_id or f"job_{int(time.time() * 1000)}_{os.urandom(4).hex()}"
    now = time.time()
    with sqlite3.connect(path, timeout=10.0) as conn:
        conn.execute(
            "INSERT INTO solver_jobs (job_id, status, payload_json, callback_url, created_at, updated_at) "
            "VALUES (?, 'pending', ?, ?, ?, ?)",
            (jid, json.dumps(payload, ensure_ascii=False), callback_url, now, now),
        )
    return jid


def get_solve_job(job_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """查询队列任务状态及结果。"""
    path = init_worker_db(db_path)
    with sqlite3.connect(path, timeout=10.0) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM solver_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            return None
        return {
            "job_id": row["job_id"], "status": row["status"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": row["error_text"], "worker_id": row["worker_id"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }


def run_solve_task(payload: Dict[str, Any]) -> Dict[str, Any]:
    """无状态执行单次 UnifiedSolver 求解任务（纯计算，不依赖 HTTP 上下文）。"""
    t_start = time.perf_counter()
    raw_container = payload.get("container") or payload.get("containerSpec", {})
    raw_manifest = payload.get("manifest") or payload.get("cargo") or payload.get("sku", [])
    container_spec = InputAdapter.parse_container(raw_container)
    cargo_skus = InputAdapter.parse_cargo_list(raw_manifest)
    validate_manifest_size(cargo_skus)

    mode_str = str(payload.get("mode", "BALANCED")).upper()
    seed = validate_seed(payload.get("randomSeed", 42))
    time_budget = validate_time_budget(payload.get("timeBudgetSec", 20.0))
    version_num = int(payload.get("version", 1))
    solution_id = payload.get("solutionId") or f"sol_{int(time.time() * 1000)}_{os.urandom(4).hex()}"

    scenario = detect_scenario(
        cargo_skus, container_spec, requested_policy=payload.get("policy") or payload.get("planStrategy")
    )
    policy = scenario["policy"]
    solve_options = build_product_options(cargo_skus, policy=policy, payload=payload)
    algo_mode = str(payload.get("algorithmMode") or payload.get("algorithm_mode") or "unified").strip().lower()
    if algo_mode in ("unified", "proto_ems", "proto_ems_flex6"):
        solve_options["algorithm_mode"] = algo_mode

    pre = precheck_manifest(cargo_skus, container_spec, options=solve_options)
    if pre["errors"]:
        code = pre["errors"][0].get("code", "CONFIG_UNSATISFIABLE")
        if code not in ("DOOR_SEAL_CAPACITY_UNSATISFIABLE", "MULTISTOP_UNSATISFIABLE"):
            code = "CONFIG_UNSATISFIABLE"
        raise ValueError(f"{code}: " + "；".join(e["message"] for e in pre["errors"][:5]))

    learning = suggest_policy(cargo_skus, container_spec)
    solution = UnifiedSolver(container_spec).solve(
        cargo_skus, mode=mode_str, seed=seed, time_budget=time_budget, options=solve_options
    )
    seq_report = compute_loading_order(solution.placements, container_spec)
    main_eval = evaluate_plan(solution, cargo_skus, container_spec, scenario=scenario, policy=policy)
    main_label = "安全优先" if (solve_options["door_step_depth"] > 0 or solve_options["door_seal_confine"]) else "主方案"
    plan_entries = [{
        "key": "main", "label": main_label,
        "profile": "SAFETY_FIRST" if solve_options["door_step_depth"] > 0 else "BALANCED",
        "solution": solution, "evaluation": main_eval, "sequence_report": seq_report,
    }]

    alt_profiles = ["VOLUME_FIRST", "BALANCED", "SAFETY_FIRST"]
    alt_labels = {
        "VOLUME_FIRST": "装载率优先（无门端安全约束）",
        "BALANCED": "均衡（封门件归位、不做门端台阶）",
        "SAFETY_FIRST": "安全优先（门端台阶）",
    }
    alt_count = validate_alternatives(payload.get("alternatives", 0) or 0)
    alt_budget = validate_alternative_budget(
        payload.get("alternativeBudgetSec", max(1.0, min(60.0, time_budget))), time_budget
    )
    req_profiles = validate_alternative_profiles(payload.get("alternativeProfiles"))
    alt_skip_notes = []
    while alt_count > 0 and time_budget + alt_count * alt_budget > 240.0:
        alt_count -= 1
        alt_skip_notes.append("备选数量因单请求总预算上限被缩减")

    seen_sigs = {(solution.placed_count, round(solution.volume_utilization_pct, 1), main_eval.get("score"))}
    for i in range(alt_count):
        prof = req_profiles[i] if i < len(req_profiles) else alt_profiles[i % len(alt_profiles)]
        try:
            alt_sol = UnifiedSolver(container_spec).solve(
                cargo_skus, mode=mode_str, seed=seed + i + 1,
                time_budget=alt_budget, options=build_product_options(cargo_skus, policy=prof),
            )
            alt_seq = compute_loading_order(alt_sol.placements, container_spec)
            alt_eval = evaluate_plan(alt_sol, cargo_skus, container_spec, scenario=scenario, policy=policy)
            sig = (alt_sol.placed_count, round(alt_sol.volume_utilization_pct, 1), alt_eval.get("score"))
            if sig not in seen_sigs:
                seen_sigs.add(sig)
                plan_entries.append({
                    "key": f"alt-{i}", "label": alt_labels.get(prof, prof), "profile": prof,
                    "solution": alt_sol, "evaluation": alt_eval, "sequence_report": alt_seq,
                })
        except Exception:
            continue

    rank = rank_plans([{"key": e["key"], "label": e["label"], "evaluation": e["evaluation"]} for e in plan_entries])
    chosen = {e["key"]: e for e in plan_entries}.get(rank.get("recommended_key")) or plan_entries[0]
    chosen_eval = chosen["evaluation"]
    result = OutputAdapter.to_legacy_response(
        solution=chosen["solution"], container=container_spec,
        cargo_list=cargo_skus, version=version_num, elapsed_ms=(time.perf_counter() - t_start) * 1000.0,
    )
    result.update({
        "solutionId": solution_id,
        "planScore": {k: v for k, v in (chosen_eval or {}).items() if k != "qa"},
        "recommendedPlanKey": chosen["key"],
        "scenario": scenario,
        "selectionNotes": (rank.get("notes") or []) + alt_skip_notes,
        "learningSuggestion": learning,
        "plans": [{
            "key": e["key"], "label": e["label"], "profile": e["profile"],
            "recommended": e["key"] == chosen["key"],
            "score": e["evaluation"].get("score"), "grade": e["evaluation"].get("grade"),
            "utilization": (e["evaluation"].get("metrics") or {}).get("utilization_pct"),
            "placedCount": (e["evaluation"].get("metrics") or {}).get("placed_count"),
            "gateVerdict": (e["evaluation"].get("gate") or {}).get("verdict"),
            "tradeoffs": [] if e["key"] == chosen["key"] else compare_plans(chosen_eval, e["evaluation"]),
        } for e in plan_entries],
    })
    return result


def _post_callback(callback_url: str, data: Dict[str, Any]) -> None:
    req = urllib.request.Request(
        callback_url,
        data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10.0) as resp:
        resp.read()


def poll_once(worker_id: str = "worker-1", db_path: Optional[str] = None) -> bool:
    """从 SQLite 队列原子认领并执行一个 pending 任务。返回是否处理了任务。"""
    path = init_worker_db(db_path)
    now = time.time()
    job_row = None
    with sqlite3.connect(path, timeout=10.0) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM solver_jobs WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE solver_jobs SET status = 'running', worker_id = ?, updated_at = ? WHERE job_id = ?",
                (worker_id, now, row["job_id"]),
            )
            job_row = dict(row)
        conn.commit()

    if not job_row:
        return False

    job_id = job_row["job_id"]
    callback_url = job_row.get("callback_url")
    try:
        payload = json.loads(job_row["payload_json"])
        result = run_solve_task(payload)
        with sqlite3.connect(path, timeout=10.0) as conn:
            conn.execute(
                "UPDATE solver_jobs SET status = 'completed', result_json = ?, updated_at = ? WHERE job_id = ?",
                (json.dumps(result, ensure_ascii=False), time.time(), job_id),
            )
        if callback_url:
            _post_callback(callback_url, {"job_id": job_id, "status": "completed", "result": result})
    except Exception as exc:
        err_msg = f"{exc}\n{traceback.format_exc()}"
        with sqlite3.connect(path, timeout=10.0) as conn:
            conn.execute(
                "UPDATE solver_jobs SET status = 'failed', error_text = ?, updated_at = ? WHERE job_id = ?",
                (err_msg, time.time(), job_id),
            )
        if callback_url:
            try:
                _post_callback(callback_url, {"job_id": job_id, "status": "failed", "error": str(exc)})
            except Exception:
                pass
    return True


def run_worker_loop(poll_interval: float = 0.5, worker_id: Optional[str] = None) -> None:
    """持续轮询 SQLite 队列的独立无状态 Worker 主循环。"""
    wid = worker_id or f"worker-{os.getpid()}"
    db_path = init_worker_db()
    print(f"[SOLVER-WORKER] {wid} started, queue={db_path}")
    try:
        while True:
            handled = poll_once(worker_id=wid, db_path=db_path)
            if not handled:
                time.sleep(poll_interval)
    except KeyboardInterrupt:
        print(f"[SOLVER-WORKER] {wid} stopped.")


if __name__ == "__main__":
    run_worker_loop()
