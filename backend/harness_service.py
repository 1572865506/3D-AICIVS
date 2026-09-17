"""
3D-AICIVS 测试平台后台异步调度服务 (HarnessService)

职责：
  - 管理测试套件的后台执行线程生命周期（启动、进度追踪、停止）
  - 维持内存级实时进度与用例状态流，供 Web 前端高频轮询 (1s)
  - 自动生成结构化报表与专供 Agent 对话消费的 <30 行纯文本诊断
"""

import os
import sys
import json
import time
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts.test_harness.runner import (
    _get_hardcoded_cases,
    _discover_json_cases,
    _infer_tags,
    _run_with_timeout,
    _solver_hash,
    _file_hash,
    execute_benchmark_case,
    REPORTS_DIR,
    HISTORY_DIR,
    HASH_FILE,
)
from scripts.test_harness.analyzer import analyze_results, _find_latest_history
from scripts.test_harness.reporter import generate_reports


class HarnessTaskManager:
    """测试任务状态与调度管理器 (线程安全单例)"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_state()
            return cls._instance

    def _init_state(self):
        self.state_lock = threading.Lock()
        self.is_running = False
        self.stop_requested = False
        self.thread: Optional[threading.Thread] = None

        self.current_task: Dict[str, Any] = {
            "task_id": None,
            "status": "IDLE",  # IDLE | RUNNING | COMPLETED | STOPPED | FAILED
            "tier": 1,
            "start_time": None,
            "elapsed_s": 0,
            "total_cases": 0,
            "current_index": 0,
            "current_case_id": None,
            "current_case_name": None,
            "current_case_start": None,
            "passed_count": 0,
            "failed_count": 0,
            "warned_count": 0,
            "avg_utilization": 0.0,
            "completed_cases": [],  # 实时已完成用例摘要列表
            "error": None,
        }

    def get_status(self) -> Dict[str, Any]:
        """获取当前执行状态快照 (线程安全)"""
        with self.state_lock:
            data = dict(self.current_task)
            if self.is_running and data.get("start_time"):
                data["elapsed_s"] = round(time.time() - data["start_time"], 1)
            # 浅拷贝已完成列表，防止迭代过程中被修改
            data["completed_cases"] = list(self.current_task["completed_cases"])
            return data

    def stop_test(self) -> bool:
        """请求中止当前测试"""
        with self.state_lock:
            if not self.is_running:
                return False
            self.stop_requested = True
            return True

    def start_test(self, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """启动后台测试任务"""
        with self.state_lock:
            if self.is_running:
                return {"error": "测试任务已在运行中，请勿重复触发", "task_id": self.current_task["task_id"]}

            opts = options or {}
            task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.is_running = True
            self.stop_requested = False

            self.current_task = {
                "task_id": task_id,
                "status": "RUNNING",
                "tier": opts.get("tier", 1),
                "options": opts,
                "start_time": time.time(),
                "elapsed_s": 0,
                "total_cases": 0,
                "current_index": 0,
                "current_case_id": "Initializing...",
                "current_case_name": "正在加载测试用例库",
                "current_case_start": time.time(),
                "passed_count": 0,
                "failed_count": 0,
                "warned_count": 0,
                "avg_utilization": 0.0,
                "completed_cases": [],
                "error": None,
            }

            self.thread = threading.Thread(target=self._run_worker, args=(opts, task_id), daemon=True)
            self.thread.start()
            return {"status": "started", "task_id": task_id}

    def _run_worker(self, opts: Dict[str, Any], task_id: str):
        """后台工作线程：执行用例、更新状态并输出报表"""
        try:
            tier = int(opts.get("tier", 1))
            limit = opts.get("limit")
            if limit:
                limit = int(limit)
            tags = opts.get("tags", "")
            container = opts.get("container", "")
            ids = opts.get("ids", [])
            timeout = int(opts.get("timeout", 120))
            incremental = bool(opts.get("incremental", False))

            # 1. 发现用例
            cases = list(_get_hardcoded_cases())
            search_dirs = ["tests/cases"]
            if tier >= 2:
                search_dirs.extend(["tests/cases/generated", "tests/cases/random", "tests/cases/production"])
            cases.extend(_discover_json_cases(search_dirs))

            # 去重
            seen = set()
            unique = []
            for c in cases:
                if c[2] not in seen:
                    seen.add(c[2])
                    unique.append(c)
            cases = unique

            if tier == 1 and not ids:
                cases = cases[:100]

            # 2. 过滤
            if ids:
                id_set = set(ids if isinstance(ids, list) else [x.strip() for x in ids.split(",")])
                cases = [c for c in cases if c[2] in id_set]
            if tags:
                tag_set = set(t.strip().lower() for t in tags.split(",") if t.strip())
                filtered = []
                for c in cases:
                    inferred = _infer_tags(c[2], c[4])
                    if tag_set.intersection(set(inferred)):
                        filtered.append(c)
                cases = filtered
            if container:
                ct_set = set(t.strip().upper() for t in container.split(",") if t.strip())
                filtered = []
                for c in cases:
                    inferred = _infer_tags(c[2], c[4])
                    if ct_set.intersection(set(t.upper() for t in inferred)):
                        filtered.append(c)
                cases = filtered

            if limit and limit > 0:
                cases = cases[:limit]

            total_cases = len(cases)
            with self.state_lock:
                self.current_task["total_cases"] = total_cases

            # 3. 增量哈希准备
            prev_hashes = {}
            if incremental and os.path.exists(HASH_FILE):
                try:
                    with open(HASH_FILE, "r", encoding="utf-8") as f:
                        prev_hashes = json.load(f)
                except Exception:
                    pass
            s_hash = _solver_hash()
            solver_changed = prev_hashes.get("_solver") != s_hash
            new_hashes = {"_solver": s_hash}

            # 4. 逐个执行
            results = {}
            total_util_sum = 0.0

            for i, (spec, cargo, cid, name, desc) in enumerate(cases, 1):
                if self.stop_requested:
                    with self.state_lock:
                        self.current_task["status"] = "STOPPED"
                    break

                with self.state_lock:
                    self.current_task["current_index"] = i
                    self.current_task["current_case_id"] = cid
                    self.current_task["current_case_name"] = name
                    self.current_task["current_case_start"] = time.time()

                # 增量跳过检查
                if incremental and not solver_changed:
                    if prev_hashes.get(cid) and prev_hashes.get(cid) == new_hashes.get(cid, ""):
                        continue

                t0 = time.time()
                res = _run_with_timeout(execute_benchmark_case, (spec, cargo, cid, name, desc), timeout)
                dt = time.time() - t0

                status = res.get("health_status", "UNKNOWN")
                viols = res.get("violations", 0)
                cols = res.get("collisions", 0)
                util = res.get("utilization", 0.0)
                rigid_comp = res.get("sku_fulfillment", {}).get("rigid_completion_pct", 0.0)

                if status == "HEALTHY" and viols == 0 and cols == 0:
                    tag = "PASS"
                elif status in ("TIMEOUT", "ERROR") or viols > 0 or cols > 0:
                    tag = "FAIL"
                else:
                    tag = "WARN"

                res["status"] = tag
                results[cid] = res
                total_util_sum += util

                # 更新实时结果
                with self.state_lock:
                    if tag == "PASS":
                        self.current_task["passed_count"] += 1
                    elif tag == "WARN":
                        self.current_task["warned_count"] += 1
                    else:
                        self.current_task["failed_count"] += 1

                    finished_count = len(results)
                    self.current_task["avg_utilization"] = round(total_util_sum / max(1, finished_count), 2)
                    q_met = res.get("quality_metrics", {})
                    self.current_task["completed_cases"].append({
                        "case_id": cid,
                        "case_name": name,
                        "status": tag,
                        "utilization": util,
                        "hollow_ratio": q_met.get("hollow_ratio_pct", 0.0),
                        "cog_offset": q_met.get("cog_offset_y_pct", 0.0),
                        "rigid_pct": rigid_comp,
                        "violations": viols,
                        "collisions": cols,
                        "duration_s": round(dt, 2),
                    })

            # 5. 完成处理与写入报告
            total_time = time.time() - self.current_task["start_time"]
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_data = {
                "run_id": run_id,
                "timestamp": datetime.now().isoformat(),
                "tier": tier,
                "total_cases": len(results),
                "passed": self.current_task["passed_count"],
                "failed": self.current_task["failed_count"],
                "warned": self.current_task["warned_count"],
                "total_runtime_s": round(total_time, 1),
                "results": results,
            }

            os.makedirs(HISTORY_DIR, exist_ok=True)
            latest_path = os.path.join(REPORTS_DIR, "latest_results.json")
            history_path = os.path.join(HISTORY_DIR, f"run_{run_id}.json")
            for path in (latest_path, history_path):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(report_data, f, indent=2, ensure_ascii=False)

            # 6. 生成归因与报告
            try:
                analysis_path = os.path.join(REPORTS_DIR, "latest_analysis.json")
                history = _find_latest_history(latest_path)
                analysis = analyze_results(report_data, history)
                with open(analysis_path, "w", encoding="utf-8") as f:
                    json.dump(analysis, f, indent=2, ensure_ascii=False)

                md_path = os.path.join(REPORTS_DIR, "latest_report.md")
                json_report_path = os.path.join(REPORTS_DIR, "latest_report.json")
                generate_reports(latest_path, analysis_path, md_path, json_report_path, show_trend=True)
            except Exception as e:
                sys.stderr.write(f"生成分析报告异常: {e}\n")

            with self.state_lock:
                if self.current_task["status"] != "STOPPED":
                    self.current_task["status"] = "COMPLETED"
                self.current_task["elapsed_s"] = round(total_time, 1)

        except Exception as e:
            with self.state_lock:
                self.current_task["status"] = "FAILED"
                self.current_task["error"] = str(e)
        finally:
            with self.state_lock:
                self.is_running = False


def generate_agent_summary(report_data: Optional[Dict] = None, analysis_data: Optional[Dict] = None) -> str:
    """生成严格契约化、符合 AGENTS.md 规范的 <30 行 Agent 极简诊断文本"""
    if not report_data:
        res_file = os.path.join(REPORTS_DIR, "latest_results.json")
        if os.path.exists(res_file):
            try:
                with open(res_file, "r", encoding="utf-8") as f:
                    report_data = json.load(f)
            except Exception:
                pass
    if not analysis_data:
        ana_file = os.path.join(REPORTS_DIR, "latest_analysis.json")
        if os.path.exists(ana_file):
            try:
                with open(ana_file, "r", encoding="utf-8") as f:
                    analysis_data = json.load(f)
            except Exception:
                pass

    if not report_data:
        return "⚠️ 暂无可用测试报告，请先在看板中启动测试。"

    total = report_data.get("total_cases", 0)
    passed = report_data.get("passed", 0)
    warned = report_data.get("warned", 0)
    failed = report_data.get("failed", 0)
    dur = report_data.get("total_runtime_s", 0)
    tier = report_data.get("tier", 1)

    summary = (analysis_data or {}).get("summary", {})
    avg_util = summary.get("avg_utilization", 0.0)
    avg_rigid = summary.get("avg_rigid_completion", 0.0)
    total_viols = summary.get("total_violations", 0)
    total_cols = summary.get("total_collisions", 0)

    lines = [
        f"📋 3D-AICIVS 平台测试诊断 (Web 看板一键导出)",
        f"- 运行工况: Tier {tier} | 总用例: {total} | 耗时: {dur:.1f}s",
        f"- 总体状态: {passed} PASS / {warned} WARN / {failed} FAIL | 碰撞: {total_cols} | 违规: {total_viols}",
        f"- 核心指标: 平均利用率: {avg_util:.1f}% | 平均刚性交付: {avg_rigid:.1f}%",
    ]

    clusters = (analysis_data or {}).get("fault_clusters", [])
    if clusters:
        lines.append(f"\n⚠️ 核心故障聚类 (Top {min(3, len(clusters))}):")
        for i, c in enumerate(clusters[:3], 1):
            cases_sample = ", ".join(c.get("case_ids", [])[:3])
            fix = c.get("suggested_fix", {})
            lines.append(f"{i}. [{c.get('fault_type')}] ({c.get('count')} 用例: {cases_sample})")
            lines.append(f"   • 归因: {fix.get('description', 'N/A')}")
            lines.append(f"   • 建议修改: 角色 {fix.get('agent_role', 'A')} -> `{fix.get('code_location', 'N/A')}`")
    else:
        lines.append("\n✨ 所有用例全部合规 PASS，无故障聚类。")

    diff = (analysis_data or {}).get("diff", {})
    new_fails = diff.get("new_failures", [])
    if new_fails:
        lines.append(f"\n🚨 新增回归失败 ({len(new_fails)} 个): {', '.join(new_fails[:4])}")

    return "\n".join(lines)


def generate_single_case_summary(case_id: str) -> Dict[str, Any]:
    """获取单个测试用例的深度结构化数据与精简诊断文本 (专供 Agent 靶向分析)"""
    res_file = os.path.join(REPORTS_DIR, "latest_results.json")
    if not os.path.exists(res_file):
        return {"error": "暂无测试运行数据，请先启动测试"}

    try:
        with open(res_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"error": f"读取测试数据失败: {e}"}

    results = data.get("results", {})
    case_res = results.get(case_id)
    if not case_res:
        return {"error": f"未找到用例 ID [{case_id}] 的执行结果"}

    # 提取关键信息
    name = case_res.get("case_name", case_id)
    desc = case_res.get("description", "")
    placed = case_res.get("placed_count", 0)
    req = case_res.get("requested_cartons", 0)
    util = case_res.get("utilization", 0.0)
    rt = case_res.get("runtime_ms", 0.0)
    cols = case_res.get("collisions", 0)
    viols = case_res.get("violations", 0)
    health = case_res.get("health_status", "UNKNOWN")
    issues = case_res.get("health_issues", [])

    sku_ful = case_res.get("sku_fulfillment", {})
    rigid_req = sku_ful.get("rigid_required", 0)
    rigid_p = sku_ful.get("rigid_placed", 0)
    rigid_pct = sku_ful.get("rigid_completion_pct", 0.0)
    elas_req = sku_ful.get("elastic_required", 0)
    elas_p = sku_ful.get("elastic_placed", 0)
    elas_pct = sku_ful.get("elastic_completion_pct", 0.0)
    inversion = sku_ful.get("priority_inversion", False)
    starved = sku_ful.get("starved_skus", [])
    details = sku_ful.get("sku_details", {})

    missing_skus = []
    for sid, info in details.items():
        if info.get("placed", 0) < info.get("required", 0):
            missing_skus.append({
                "sku_id": sid,
                "name": info.get("name", sid),
                "is_elastic": info.get("is_elastic", False),
                "placed": info.get("placed", 0),
                "required": info.get("required", 0),
                "diff": info.get("required", 0) - info.get("placed", 0),
                "pct": info.get("completion_pct", 0.0)
            })

    quality = case_res.get("quality_metrics", {})
    hollow_pct = quality.get("hollow_ratio_pct", 0.0)
    cavity_vol = quality.get("enclosed_cavity_volume", 0.0)
    cavity_cnt = quality.get("enclosed_cavity_count", 0)
    frag_score = quality.get("fragmentation_score", 0.0)
    cog_x_pct = quality.get("cog_offset_x_pct", 0.0)
    cog_y_pct = quality.get("cog_offset_y_pct", 0.0)

    # 构建发送给 Agent 的精炼纯文本 (<30行)
    text_lines = [
        f"📦 3D-AICIVS 单用例深度诊断: {case_id} ({name})",
        f"- 基础指标: 空间利用率 {util:.2f}% | 放入 {placed}/{req} 箱 | 耗时 {rt:.1f}ms",
        f"- 结构质量: 中空死腔率 {hollow_pct:.2f}% (死穴 {cavity_cnt} 个, 体积 {cavity_vol:.3f}m³) | 碎片化评分 {frag_score:.3f}",
        f"- 重心平衡: 纵向偏移 {cog_x_pct:.1f}% | 横向偏载 {cog_y_pct:.1f}%",
        f"- 履约状态: 刚性履行率 {rigid_pct:.1f}% ({rigid_p}/{rigid_req}) | 弹性完成率 {elas_pct:.1f}% ({elas_p}/{elas_req})",
        f"- 物理审计: 碰撞 {cols} 对 | 约束违规 {viols} 条 | 优先级倒挂: {'⚠️ 存在(弹性件抢占刚性)' if inversion else '否'} | 判定: {health}",
    ]

    if issues:
        text_lines.append(f"- 审计告警: {', '.join(issues)}")

    if starved:
        text_lines.append(f"🚨 严重弃装/饥饿 SKU (放入为0): {', '.join(starved)}")

    if missing_skus:
        text_lines.append(f"- 未满载/漏装 SKU ({len(missing_skus)} 种):")
        for m in missing_skus[:5]:
            t_str = "弹性件" if m["is_elastic"] else "【刚性件漏装】"
            text_lines.append(f"  • {m['sku_id']} ({m['name']}) [{t_str}]: 放入 {m['placed']}/{m['required']} ({m['pct']}%), 漏装 {m['diff']} 件")
        if len(missing_skus) > 5:
            text_lines.append(f"  • ... 另有 {len(missing_skus)-5} 种未满载 SKU")
    else:
        text_lines.append("- SKU 履约: ✨ 全部 SKU 100% 满额装载！")

    audit = case_res.get("constraint_audit", {})
    active_viols = [f"{k}: {v}" for k, v in audit.items() if v > 0]
    if active_viols:
        text_lines.append(f"- 违规分类明细: {', '.join(active_viols)}")

    return {
        "case_id": case_id,
        "case_name": name,
        "description": desc,
        "metrics": {
            "utilization": util,
            "placed_count": placed,
            "requested_cartons": req,
            "runtime_ms": rt,
            "collisions": cols,
            "violations": viols,
            "health_status": health,
            "priority_inversion": inversion,
        },
        "quality_metrics": {
            "hollow_ratio_pct": hollow_pct,
            "enclosed_cavity_volume": cavity_vol,
            "enclosed_cavity_count": cavity_cnt,
            "fragmentation_score": frag_score,
            "cog_offset_x_pct": cog_x_pct,
            "cog_offset_y_pct": cog_y_pct,
        },
        "fulfillment": {
            "rigid_completion_pct": rigid_pct,
            "elastic_completion_pct": elas_pct,
            "starved_skus": starved,
            "missing_skus": missing_skus,
            "sku_details": details,
        },
        "constraint_audit": audit,
        "agent_text": "\n".join(text_lines)
    }

