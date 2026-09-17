"""
3D-AICIVS 故障归因与聚类引擎

用途：读取测试结果，对失败用例进行故障分类和聚类，提取共性特征，输出修复建议。
输入：tests/harness_reports/latest_results.json (runner 输出)
输出：tests/harness_reports/latest_analysis.json

核心能力：
  1. 15 种故障分类（碰撞、支撑、倾覆、朝向、层数、承重等）
  2. 按主故障类型聚类，提取共性模式
  3. 每个聚类附带代码位置和 Agent 角色建议
  4. 与历史运行对比（新增失败 / 已修复 / 稳定失败 / 趋势）

被调用方：命令行直接调用, reporter.py
"""

import os
import sys
import json
import glob
import argparse
from collections import defaultdict
from typing import Dict, Any, List, Optional

# 确保 UTF-8 输出（Windows 兼容）
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "tests", "harness_reports")

# ═══════════════════ 故障分类规则 ═══════════════════

FAULT_RULES = [
    ("COLLISION",          lambda r: r.get("collisions", 0) > 0),
    ("SUPPORT_FAIL",       lambda r: r.get("constraint_audit", {}).get("support_floating_violations", 0) > 0),
    ("TIPPING_RISK",       lambda r: any("tipping" in str(i).lower() or "倾覆" in str(i)
                                         for i in r.get("health_issues", []))),
    ("ORIENTATION_FAIL",   lambda r: r.get("constraint_audit", {}).get("orientation_violations", 0) > 0),
    ("STACK_LIMIT_FAIL",   lambda r: r.get("constraint_audit", {}).get("stack_layer_violations", 0) > 0),
    ("BEARING_FAIL",       lambda r: r.get("constraint_audit", {}).get("bearing_violations", 0) > 0),
    ("FLOOR_FAIL",         lambda r: r.get("constraint_audit", {}).get("floor_only_violations", 0) > 0),
    ("NOTOP_FAIL",         lambda r: r.get("constraint_audit", {}).get("top_stack_violations", 0) > 0),
    ("DOOR_FAIL",          lambda r: r.get("constraint_audit", {}).get("door_lockout_violations", 0) > 0),
    ("ZONE_FAIL",          lambda r: r.get("constraint_audit", {}).get("zone_violations", 0) > 0),
    ("OVERWEIGHT",         lambda r: r.get("constraint_audit", {}).get("payload_violations", 0) > 0),
    ("RIGID_STARVATION",   lambda r: (r.get("sku_fulfillment", {}).get("rigid_completion_pct", 100) < 99
                                       and len(r.get("sku_fulfillment", {}).get("starved_skus", [])) > 0)),
    ("PRIORITY_INVERSION", lambda r: r.get("sku_fulfillment", {}).get("priority_inversion", False)),
    ("HIGH_HOLLOW_RATIO",  lambda r: r.get("quality_metrics", {}).get("hollow_ratio_pct", 0.0) > 15.0),
    ("COG_UNBALANCED",     lambda r: r.get("quality_metrics", {}).get("cog_offset_y_pct", 0.0) > 12.0),
    ("LOW_UTILIZATION",    lambda r: (r.get("utilization", 100) < 60
                                       and r.get("violations", 0) == 0
                                       and r.get("collisions", 0) == 0)),
    ("TIMEOUT",            lambda r: r.get("status") == "TIMEOUT" or r.get("health_status") == "TIMEOUT"),
]

# ═══════════════════ 修复建议映射 ═══════════════════

FIX_SUGGESTIONS = {
    "COLLISION": {
        "code_location": "unified_solver.py 放置逻辑, spatial_index.py",
        "agent_role": "A",
        "description": "空间索引存在碰撞/穿透重叠，需检查坐标相交逻辑"
    },
    "SUPPORT_FAIL": {
        "code_location": "stability/ 目录, _has_sufficient_support",
        "agent_role": "B",
        "description": "物品悬空/支撑面积不足，需检查支撑率计算逻辑"
    },
    "TIPPING_RISK": {
        "code_location": "stability/ 目录, tipping_moment.py",
        "agent_role": "B",
        "description": "刹车/侧倾工况下倾覆安全系数不足"
    },
    "ORIENTATION_FAIL": {
        "code_location": "unified_solver.py _generate_orientations",
        "agent_role": "A",
        "description": "物品朝向违反 OrientationPolicy 约束"
    },
    "STACK_LIMIT_FAIL": {
        "code_location": "unified_solver.py 堆叠检查, independent_validator.py",
        "agent_role": "A",
        "description": "违反 max_stack_layers 层数上限"
    },
    "BEARING_FAIL": {
        "code_location": "unified_solver.py PASS2/3 顶填承重预检",
        "agent_role": "A",
        "description": "顶填时未充分检查下层承重余量"
    },
    "FLOOR_FAIL": {
        "code_location": "unified_solver.py 放置过滤器",
        "agent_role": "A",
        "description": "mustBeOnFloor 物品被放在了上层"
    },
    "NOTOP_FAIL": {
        "code_location": "unified_solver.py 放置过滤器",
        "agent_role": "A",
        "description": "allowStackingOnTop=false 物品上方被压"
    },
    "DOOR_FAIL": {
        "code_location": "unified_solver.py 门区保留/封门逻辑",
        "agent_role": "A",
        "description": "非封门件侵入门区或封门件未被分配到门区"
    },
    "ZONE_FAIL": {
        "code_location": "unified_solver.py 区位约束检查",
        "agent_role": "A",
        "description": "物品放置位置超出指定区域限制"
    },
    "OVERWEIGHT": {
        "code_location": "unified_solver.py 载重检查",
        "agent_role": "A",
        "description": "超过集装箱最大载重量"
    },
    "RIGID_STARVATION": {
        "code_location": "composite_strip.py 刚性优先分配",
        "agent_role": "A",
        "description": "刚性 SKU 饥饿/弃装，弹性件可能抢占了截面配额"
    },
    "PRIORITY_INVERSION": {
        "code_location": "composite_strip.py 排序逻辑",
        "agent_role": "A",
        "description": "刚性未满 99% 时弹性件已被放入，存在优先级倒挂"
    },
    "HIGH_HOLLOW_RATIO": {
        "code_location": "unified_solver.py 间隙填充 (gap_filler.py) 与排砖连通性",
        "agent_role": "A",
        "description": "内部封闭中空死腔率偏高 (>15%)，需强化小件内部填充或截面连续贴合"
    },
    "COG_UNBALANCED": {
        "code_location": "unified_solver.py _balance_cog / 重量侧分配逻辑",
        "agent_role": "B",
        "description": "横向重心偏载 (>12%)，存在单侧偏重安全隐患，需调整对称配载"
    },
    "LOW_UTILIZATION": {
        "code_location": "unified_solver.py 墙体构建 + gap_filler.py",
        "agent_role": "A",
        "description": "空间利用率低于 60%，需优化墙体效率和间隙填充"
    },
    "TIMEOUT": {
        "code_location": "unified_solver.py 搜索循环",
        "agent_role": "A",
        "description": "算法执行超时，可能存在计算爆炸或死循环"
    },
}


def classify_faults(case_res: Dict[str, Any]) -> List[str]:
    """对单个用例结果进行多标签故障分类"""
    return [name for name, rule in FAULT_RULES if rule(case_res)]


def analyze_results(results_data: Dict[str, Any],
                    history_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    分析测试结果，产出故障聚类报告。

    参数：
      results_data: runner.py 输出的 JSON（包含 "results" 字段，值为 {case_id: result_dict}）
      history_data: 可选的历史运行数据，用于 diff 对比
    """
    case_results = results_data.get("results", {})
    if not isinstance(case_results, dict):
        case_results = {}

    # ── 汇总统计 ──
    total = len(case_results)
    total_util = 0.0
    total_rigid = 0.0
    total_cols = 0
    total_viols = 0
    n_pass = n_fail = n_warn = 0
    current_status = {}  # case_id -> PASS/FAIL/WARN

    fault_map = defaultdict(list)  # fault_type -> [case_info]

    for cid, res in case_results.items():
        status = res.get("status", "FAIL")
        util = res.get("utilization", 0.0)
        cols = res.get("collisions", 0)
        viols = res.get("violations", 0)
        rigid_pct = res.get("sku_fulfillment", {}).get("rigid_completion_pct", 0.0)

        total_util += util
        total_rigid += rigid_pct
        total_cols += cols
        total_viols += viols
        current_status[cid] = status

        if status == "PASS":
            n_pass += 1
        elif status == "WARN":
            n_warn += 1
        else:
            n_fail += 1

        # 故障分类
        if status != "PASS":
            faults = classify_faults(res)
            if not faults:
                faults = ["UNKNOWN_FAIL"]
            primary = faults[0]
            fault_map[primary].append({
                "case_id": cid,
                "all_faults": faults,
                "utilization": util,
                "rigid_pct": rigid_pct,
                "violations": viols,
                "collisions": cols,
            })

    summary = {
        "total": total,
        "passed": n_pass,
        "failed": n_fail,
        "warned": n_warn,
        "avg_utilization": round(total_util / max(1, total), 2),
        "avg_rigid_completion": round(total_rigid / max(1, total), 2),
        "total_collisions": total_cols,
        "total_violations": total_viols,
    }

    # ── 聚类 ──
    clusters = []
    for idx, (fault_type, items) in enumerate(sorted(fault_map.items(), key=lambda x: -len(x[1])), 1):
        case_ids = [it["case_id"] for it in items]
        avg_util = round(sum(it["utilization"] for it in items) / len(items), 1)
        avg_rigid = round(sum(it["rigid_pct"] for it in items) / len(items), 1)

        clusters.append({
            "cluster_id": f"CLUSTER-{idx}",
            "fault_type": fault_type,
            "count": len(items),
            "case_ids": case_ids,
            "common_patterns": {
                "avg_utilization": avg_util,
                "avg_rigid_completion": avg_rigid,
            },
            "suggested_fix": FIX_SUGGESTIONS.get(fault_type, {
                "code_location": "需进一步分析",
                "agent_role": "A",
                "description": "未知故障类型",
            }),
        })

    # ── 历史 diff ──
    diff = {
        "new_failures": [],
        "fixed_cases": [],
        "stable_failures": [],
        "utilization_trend": {"previous": 0.0, "current": summary["avg_utilization"], "delta": 0.0},
    }

    if history_data:
        hist_results = history_data.get("results", {})
        hist_status = {}
        hist_util_sum = 0.0
        for hid, hres in hist_results.items():
            hist_status[hid] = hres.get("status", "FAIL")
            hist_util_sum += hres.get("utilization", 0.0)

        if hist_results:
            prev_avg = round(hist_util_sum / len(hist_results), 2)
            diff["utilization_trend"]["previous"] = prev_avg
            diff["utilization_trend"]["delta"] = round(summary["avg_utilization"] - prev_avg, 2)

        for cid, cur_st in current_status.items():
            prev_st = hist_status.get(cid)
            if prev_st is None:
                continue
            if prev_st == "PASS" and cur_st != "PASS":
                diff["new_failures"].append(cid)
            elif prev_st != "PASS" and cur_st == "PASS":
                diff["fixed_cases"].append(cid)
            elif prev_st != "PASS" and cur_st != "PASS":
                diff["stable_failures"].append(cid)

    return {"summary": summary, "fault_clusters": clusters, "diff": diff}


def _find_latest_history(exclude_path: str = "") -> Optional[Dict]:
    """自动查找最近一次历史运行数据"""
    hist_dir = os.path.join(REPORTS_DIR, "history")
    if not os.path.isdir(hist_dir):
        return None
    files = sorted(glob.glob(os.path.join(hist_dir, "run_*.json")), reverse=True)
    for f in files:
        if os.path.abspath(f) == os.path.abspath(exclude_path):
            continue
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            print(f"  自动加载历史对比: {os.path.basename(f)}")
            return data
        except Exception:
            continue
    return None


def main():
    parser = argparse.ArgumentParser(description="3D-AICIVS 故障归因与聚类引擎")
    parser.add_argument("--input", type=str, default="tests/harness_reports/latest_results.json",
                        help="测试结果 JSON 文件路径")
    parser.add_argument("--compare", type=str, default=None,
                        help="历史结果 JSON 文件路径（可选，自动查找最近记录）")
    parser.add_argument("--output", type=str, default="tests/harness_reports/latest_analysis.json",
                        help="分析报告输出路径")
    args = parser.parse_args()

    def abs_path(p):
        return p if os.path.isabs(p) else os.path.join(PROJECT_ROOT, p)

    input_path = abs_path(args.input)
    output_path = abs_path(args.output)

    if not os.path.exists(input_path):
        print(f"❌ 未找到测试结果文件: {input_path}")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        results = json.load(f)

    history = None
    if args.compare:
        cp = abs_path(args.compare)
        if os.path.exists(cp):
            with open(cp, "r", encoding="utf-8") as f:
                history = json.load(f)
    else:
        history = _find_latest_history(input_path)

    analysis = analyze_results(results, history)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)

    # 控制台摘要
    s = analysis["summary"]
    clusters = analysis["fault_clusters"]
    print(f"\n{'='*70}")
    print(f" 📊 故障归因分析完成 | 总计 {s['total']} 用例 | 失败 {s['failed']}")
    print(f"{'='*70}")
    if clusters:
        print(f" 发现 {len(clusters)} 个故障聚类:")
        for c in clusters[:5]:
            print(f"   {c['cluster_id']}: {c['fault_type']} ({c['count']} 用例) → {c['suggested_fix']['description']}")
    else:
        print(" ✨ 无故障聚类（全部通过）")
    d = analysis["diff"]
    if d["new_failures"]:
        print(f" ⚠️  新增失败: {len(d['new_failures'])} 个")
    if d["fixed_cases"]:
        print(f" ✅ 已修复: {len(d['fixed_cases'])} 个")
    print(f" 📁 报告: {output_path}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
