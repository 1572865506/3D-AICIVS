"""
3D-AICIVS 测试执行引擎

用途：发现、过滤、执行测试用例，产出结构化 JSON 结果。
输入：tests/cases/ 及子目录中的 JSON 用例文件 + 5 个硬编码基准用例
输出：tests/harness_reports/latest_results.json + 历史快照

核心特性：
  - 多目录用例发现 (cases/, generated/, random/, production/)
  - 标签/柜型/ID 过滤
  - 单用例超时保护 (默认 120s)
  - 增量运行 (基于文件 hash)
  - 分层执行 (Tier 1/2/3)
  - 复用 benchmark_suite.execute_benchmark_case() 确保结果一致性

被调用方：命令行直接调用
"""

import os
import sys
import json
import time
import hashlib
import argparse
import traceback
import threading
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

# 确保 UTF-8 输出
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.benchmark_suite import (
    execute_benchmark_case,
    get_benchmark_case_1_14sku,
    get_benchmark_case_2_single_large,
    get_benchmark_case_3_all_elastic,
    get_benchmark_case_4_door_dense,
    get_benchmark_case_5_mixed_heterogeneous,
    DEFAULT_40HQ_SPEC,
)

REPORTS_DIR = os.path.join(PROJECT_ROOT, "tests", "harness_reports")
HISTORY_DIR = os.path.join(REPORTS_DIR, "history")
HASH_FILE = os.path.join(REPORTS_DIR, ".case_hashes.json")

# 用例搜索目录（相对于 PROJECT_ROOT）
CASE_DIRS = [
    "tests/cases",
    "tests/cases/generated",
    "tests/cases/random",
    "tests/cases/production",
]


def _get_hardcoded_cases() -> List[Tuple[Dict, List, str, str, str]]:
    """获取 5 个硬编码基准用例（与 benchmark_suite 一致）"""
    return [
        get_benchmark_case_1_14sku(),
        get_benchmark_case_2_single_large(),
        get_benchmark_case_3_all_elastic(),
        get_benchmark_case_4_door_dense(),
        get_benchmark_case_5_mixed_heterogeneous(),
    ]


def _load_json_case(filepath: str) -> Optional[Tuple[Dict, List, str, str, str]]:
    """加载并解析单个 JSON 用例文件，返回与 execute_benchmark_case 兼容的五元组"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        case_id = data["case_id"]
        case_name = data.get("case_name", case_id)
        description = data.get("description", "")

        container_raw = data.get("container", {})
        if isinstance(container_raw, str) and container_raw.upper() in ("40HQ", "40HC"):
            container_spec = DEFAULT_40HQ_SPEC
        else:
            usable = container_raw.get("usable", container_raw)
            container_spec = {
                "usable": {
                    "L": float(usable.get("L", 12.032)),
                    "W": float(usable.get("W", 2.352)),
                    "H": float(usable.get("H", 2.698)),
                },
                "maxPayloadTons": float(container_raw.get("maxPayloadTons", 26.5)),
            }

        cargo_list = []
        for item in data.get("cargo", []):
            entry = {
                "sku": item.get("sku", ""),
                "name": item.get("name", ""),
                "w": float(item.get("w", 0.0)),
                "d": float(item.get("d", 0.0)),
                "h": float(item.get("h", 0.0)),
                "weight": float(item.get("weight", 0.0)),
                "quantity": int(item.get("quantity", 0)),
                "requirement": item.get("requirement", ""),
            }
            for key in ("isElastic", "allowDoorZone", "mustBeOnFloor",
                        "allowStackingOnTop", "allowFlat", "allowSide",
                        "allowedOrientation", "orientationRules",
                        "max_stack_layers", "maxBearingKg", "maxFlatLayers"):
                if key in item:
                    entry[key] = item[key]
            cargo_list.append(entry)

        return (container_spec, cargo_list, case_id, case_name, description)
    except Exception as e:
        print(f"  [WARN] 跳过无效用例: {filepath}: {e}")
        return None


def _discover_json_cases(dirs: List[str]) -> List[Tuple[Dict, List, str, str, str]]:
    """从多个目录发现并加载 JSON 用例"""
    cases = []
    seen_ids = set()
    for rel_dir in dirs:
        abs_dir = os.path.join(PROJECT_ROOT, rel_dir)
        if not os.path.isdir(abs_dir):
            continue
        for fname in sorted(os.listdir(abs_dir)):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(abs_dir, fname)
            result = _load_json_case(fpath)
            if result and result[2] not in seen_ids:
                seen_ids.add(result[2])
                cases.append(result)
    return cases


def _infer_tags(case_id: str, description: str) -> List[str]:
    """从 case_id 和 description 推断标签"""
    tags = []
    text = (case_id + " " + description).lower()
    for keyword in ("door", "bearing", "stack", "floor", "elastic", "rigid",
                    "tipping", "orientation", "20gp", "40gp", "40hq", "45hq", "53hq",
                    "overweight", "zone", "topstack"):
        if keyword in text:
            tags.append(keyword)
    return tags


def _file_hash(filepath: str) -> str:
    """计算文件 MD5"""
    if not os.path.exists(filepath):
        return ""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def _solver_hash() -> str:
    """计算求解器核心文件哈希"""
    solver_path = os.path.join(PROJECT_ROOT, "backend", "solver_v2", "solver", "unified_solver.py")
    return _file_hash(solver_path)


def _run_with_timeout(func, args, timeout: int) -> Dict[str, Any]:
    """带超时保护的用例执行（使用线程）"""
    result = [None]
    error = [None]

    def target():
        try:
            result[0] = func(*args)
        except Exception as e:
            error[0] = e

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        return {"case_id": args[2] if len(args) > 2 else "unknown",
                "health_status": "TIMEOUT", "status": "TIMEOUT",
                "utilization": 0.0, "collisions": 0, "violations": 0,
                "error": f"执行超时 (>{timeout}s)"}
    if error[0]:
        return {"case_id": args[2] if len(args) > 2 else "unknown",
                "health_status": "ERROR", "status": "ERROR",
                "utilization": 0.0, "collisions": 0, "violations": 0,
                "error": str(error[0]), "traceback": traceback.format_exc()}
    return result[0] or {"case_id": "unknown", "health_status": "ERROR", "status": "ERROR"}


def run_harness(args) -> Dict[str, Any]:
    """执行测试平台主流程"""
    tier = args.tier or (2 if args.all else 1)

    # ── 1. 发现用例 ──
    cases = list(_get_hardcoded_cases())
    search_dirs = ["tests/cases"]
    if tier >= 2:
        search_dirs.extend(["tests/cases/generated", "tests/cases/random", "tests/cases/production"])
    json_cases = _discover_json_cases(search_dirs)
    cases.extend(json_cases)

    # 去重
    seen = set()
    unique = []
    for c in cases:
        cid = c[2]
        if cid not in seen:
            seen.add(cid)
            unique.append(c)
    cases = unique

    if tier == 1:
        cases = cases[:100]

    # 限制最大运行用例数（如快速抽样）
    if getattr(args, "limit", None) and args.limit > 0:
        cases = cases[:args.limit]

    # ── 2. 过滤 ──
    if args.ids:
        id_set = set(args.ids.split(","))
        cases = [c for c in cases if c[2] in id_set]
    if args.exclude:
        ex_set = set(args.exclude.split(","))
        cases = [c for c in cases if not any(ex in c[2] for ex in ex_set)]
    if args.tags:
        tag_set = set(t.lower() for t in args.tags.split(","))
        filtered = []
        for c in cases:
            inferred = _infer_tags(c[2], c[4])
            if tag_set.intersection(set(inferred)):
                filtered.append(c)
        cases = filtered
    if args.container:
        ct_set = set(t.upper() for t in args.container.split(","))
        filtered = []
        for c in cases:
            tags = _infer_tags(c[2], c[4])
            if ct_set.intersection(set(t.upper() for t in tags)):
                filtered.append(c)
        cases = filtered

    # ── 3. 增量检查 ──
    prev_hashes = {}
    if args.incremental and os.path.exists(HASH_FILE):
        try:
            with open(HASH_FILE, "r", encoding="utf-8") as f:
                prev_hashes = json.load(f)
        except Exception:
            pass

    s_hash = _solver_hash()
    solver_changed = prev_hashes.get("_solver") != s_hash

    # ── 4. 执行 ──
    total = len(cases)
    print(f"\n{'='*80}")
    print(f" 3D-AICIVS 测试平台 | Tier {tier} | {total} 用例 | 超时 {args.timeout}s")
    print(f"{'='*80}\n")

    results = {}
    passed = failed = warned = 0
    t_start = time.time()
    new_hashes = {"_solver": s_hash}

    for i, (spec, cargo, cid, name, desc) in enumerate(cases, 1):
        # 增量跳过
        if args.incremental and not solver_changed:
            case_key = cid
            if prev_hashes.get(case_key) and prev_hashes.get(case_key) == new_hashes.get(case_key, ""):
                continue

        t0 = time.time()
        res = _run_with_timeout(execute_benchmark_case, (spec, cargo, cid, name, desc), args.timeout)
        dt = time.time() - t0

        status = res.get("health_status", "UNKNOWN")
        viols = res.get("violations", 0)
        cols = res.get("collisions", 0)

        if status == "HEALTHY" and viols == 0 and cols == 0:
            passed += 1
            tag = "PASS"
        elif status in ("TIMEOUT", "ERROR"):
            failed += 1
            tag = "FAIL"
        elif viols > 0 or cols > 0:
            failed += 1
            tag = "FAIL"
        else:
            warned += 1
            tag = "WARN"

        res["status"] = tag
        util = res.get("utilization", 0.0)
        print(f"  [{i:3d}/{total}] {tag:4s} {cid:<35s} | 利用率 {util:5.1f}% | 违规 {viols} | 碰撞 {cols} | {dt:.1f}s")
        results[cid] = res

    total_time = time.time() - t_start

    # ── 5. 保存结果 ──
    os.makedirs(HISTORY_DIR, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(),
        "tier": tier,
        "total_cases": len(results),
        "passed": passed,
        "failed": failed,
        "warned": warned,
        "total_runtime_s": round(total_time, 1),
        "results": results,
    }

    latest_path = os.path.join(REPORTS_DIR, "latest_results.json")
    history_path = os.path.join(HISTORY_DIR, f"run_{run_id}.json")
    for path in (latest_path, history_path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

    if args.incremental:
        new_hashes.update(prev_hashes)
        with open(HASH_FILE, "w", encoding="utf-8") as f:
            json.dump(new_hashes, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*80}")
    print(f" ✅ 执行完成 | 通过 {passed} | 失败 {failed} | 警告 {warned} | 耗时 {total_time:.1f}s")
    print(f" 📁 结果已保存: {latest_path}")
    print(f"{'='*80}\n")

    # ── 6. 自动调用归因分析与报告生成 ──
    if not getattr(args, "no_report", False):
        try:
            from scripts.test_harness.analyzer import analyze_results, _find_latest_history
            from scripts.test_harness.reporter import generate_reports

            analysis_path = os.path.join(REPORTS_DIR, "latest_analysis.json")
            history = _find_latest_history(latest_path)
            analysis = analyze_results(report, history)
            with open(analysis_path, "w", encoding="utf-8") as f:
                json.dump(analysis, f, indent=2, ensure_ascii=False)

            md_path = os.path.join(REPORTS_DIR, "latest_report.md")
            json_report_path = os.path.join(REPORTS_DIR, "latest_report.json")
            generate_reports(latest_path, analysis_path, md_path, json_report_path, show_trend=True)
        except Exception as e:
            print(f"  [WARN] 自动生成分析报告时出错: {e}")

    return report


def main():
    parser = argparse.ArgumentParser(description="3D-AICIVS 测试执行引擎")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3], help="分层: 1(核心100), 2(全部), 3(全部+动态随机)")
    parser.add_argument("--all", action="store_true", help="等同于 --tier 2")
    parser.add_argument("--tags", type=str, help="标签过滤 (逗号分隔, 如: door,bearing)")
    parser.add_argument("--container", type=str, help="柜型过滤 (逗号分隔, 如: 20GP,45HQ)")
    parser.add_argument("--ids", type=str, help="指定运行的 case_id (逗号分隔)")
    parser.add_argument("--exclude", type=str, help="排除的 case_id (逗号分隔)")
    parser.add_argument("--incremental", action="store_true", help="增量模式（跳过未变更用例）")
    parser.add_argument("--timeout", type=int, default=120, help="单用例超时秒数 (默认 120)")
    parser.add_argument("--limit", type=int, default=None, help="限制执行的最大用例数 (调试/采样用)")
    parser.add_argument("--no-report", action="store_true", help="禁用自动归因与报告生成")
    args = parser.parse_args()
    run_harness(args)


if __name__ == "__main__":
    main()
