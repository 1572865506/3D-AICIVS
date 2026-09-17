"""
3D-AICIVS 结构化报告生成器

用途：将 runner 结果 + analyzer 分析合并生成 Agent 可消费的紧凑报告。
输入：tests/harness_reports/latest_results.json + latest_analysis.json
输出：tests/harness_reports/latest_report.md (< 150 行) + latest_report.json

报告结构：
  1. 运行概览（一行摘要）
  2. 健康概览表
  3. 故障聚类摘要（核心价值区）
  4. 回归对比 (diff)
  5. 用例明细表（>30 时折叠）
  6. 行动建议（按 Agent 角色分组）

被调用方：命令行直接调用
"""

import os
import sys
import json
import glob
import argparse
from datetime import datetime
from typing import Dict, Any, List

# 确保 UTF-8 输出（Windows 兼容）
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "tests", "harness_reports")


def _load_json(filepath: str) -> Dict:
    """加载 JSON 文件"""
    if not os.path.exists(filepath):
        return {}
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_trend(history_dir: str, limit: int = 10) -> str:
    """从历史数据构建 ASCII 趋势文本"""
    if not os.path.isdir(history_dir):
        return ""
    files = sorted(glob.glob(os.path.join(history_dir, "run_*.json")))[-limit:]
    if len(files) < 2:
        return ""

    utils = []
    pass_rates = []
    for f in files:
        try:
            data = _load_json(f)
            results = data.get("results", {})
            if not results:
                continue
            avg_u = sum(r.get("utilization", 0) for r in results.values()) / max(1, len(results))
            n_pass = sum(1 for r in results.values() if r.get("status") == "PASS")
            rate = round(n_pass / max(1, len(results)) * 100)
            utils.append(round(avg_u, 1))
            pass_rates.append(rate)
        except Exception:
            continue

    if len(utils) < 2:
        return ""

    u_delta = round(utils[-1] - utils[0], 1)
    p_delta = pass_rates[-1] - pass_rates[0]
    u_arrow = "↑" if u_delta > 0 else ("↓" if u_delta < 0 else "→")
    p_arrow = "↑" if p_delta > 0 else ("↓" if p_delta < 0 else "→")

    lines = [f"趋势 (最近 {len(utils)} 次运行):"]
    lines.append(f"利用率: {' → '.join(str(u) for u in utils)} [{u_arrow} {u_delta:+.1f}]")
    lines.append(f"通过率: {' → '.join(str(p)+'%' for p in pass_rates)} [{p_arrow} {p_delta:+d}%]")
    return "\n".join(lines)


def generate_md_report(results: Dict, analysis: Dict, trend_text: str = "") -> str:
    """生成紧凑 Markdown 报告（目标 < 150 行）"""
    lines = []
    run_time = results.get("timestamp", datetime.now().isoformat())[:19]
    total = results.get("total_cases", 0)
    passed = results.get("passed", 0)
    failed = results.get("failed", 0)
    warned = results.get("warned", 0)
    runtime_s = results.get("total_runtime_s", 0)

    lines.append(f"# 🧪 测试报告 | {run_time}")
    lines.append(f"**总计 {total} 用例 | ✅ {passed} 通过 | ❌ {failed} 失败 | ⚠️ {warned} 警告 | ⏱️ {runtime_s:.0f}s**")
    lines.append("")

    # ── 健康概览 ──
    s = analysis.get("summary", {})
    lines.append("## 健康概览")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|:---|:---|")
    lines.append(f"| 平均利用率 | **{s.get('avg_utilization', 0):.1f}%** |")
    lines.append(f"| 平均刚性完成率 | **{s.get('avg_rigid_completion', 0):.1f}%** |")
    lines.append(f"| 总碰撞 | {s.get('total_collisions', 0)} |")
    lines.append(f"| 总约束违规 | {s.get('total_violations', 0)} |")
    lines.append("")

    # ── 故障聚类 ──
    clusters = analysis.get("fault_clusters", [])
    if clusters:
        lines.append("## 故障聚类摘要")
        for c in clusters:
            fix = c.get("suggested_fix", {})
            case_ids = c.get("case_ids", [])
            typical = ", ".join(case_ids[:4])
            if len(case_ids) > 4:
                typical += f" (+{len(case_ids)-4})"
            lines.append(f"### {c['cluster_id']}: {c['fault_type']} ({c['count']} 用例)")
            lines.append(f"- **典型用例**: {typical}")
            pats = c.get("common_patterns", {})
            lines.append(f"- **共性**: 平均利用率 {pats.get('avg_utilization', 0)}%, "
                         f"平均刚性 {pats.get('avg_rigid_completion', 0)}%")
            lines.append(f"- **归因**: {fix.get('description', 'N/A')}")
            lines.append(f"- **代码位置**: `{fix.get('code_location', 'N/A')}`")
            lines.append(f"- **建议角色**: 角色 {fix.get('agent_role', 'A')}")
            lines.append("")
    else:
        lines.append("## ✨ 无故障聚类 — 全部通过！")
        lines.append("")

    # ── 回归对比 ──
    diff = analysis.get("diff", {})
    new_f = diff.get("new_failures", [])
    fixed = diff.get("fixed_cases", [])
    trend = diff.get("utilization_trend", {})
    if new_f or fixed or trend.get("delta", 0) != 0:
        lines.append("## 回归对比")
        if new_f:
            lines.append(f"- 🔴 **新增失败** ({len(new_f)}): {', '.join(new_f[:5])}")
        if fixed:
            lines.append(f"- 🟢 **已修复** ({len(fixed)}): {', '.join(fixed[:5])}")
        if trend.get("previous"):
            d = trend.get("delta", 0)
            arrow = "↑" if d > 0 else ("↓" if d < 0 else "→")
            lines.append(f"- 利用率趋势: {trend['previous']}% → {trend['current']}% [{arrow} {d:+.1f}]")
        lines.append("")

    # ── 趋势 ──
    if trend_text:
        lines.append("## 历史趋势")
        lines.append("```")
        lines.append(trend_text)
        lines.append("```")
        lines.append("")

    # ── 用例明细表 ──
    case_results = results.get("results", {})
    if case_results:
        lines.append("## 用例明细表")
        items = sorted(case_results.items(), key=lambda x: x[1].get("status", "Z"))
        if len(items) > 30:
            lines.append(f"<details><summary>点击展开全部 {len(items)} 个用例</summary>")
            lines.append("")
        lines.append("| Case ID | 利用率 | 刚性% | 违规 | 碰撞 | 状态 |")
        lines.append("|:---|---:|---:|---:|---:|:---|")
        for cid, res in items:
            util = res.get("utilization", 0)
            rigid = res.get("sku_fulfillment", {}).get("rigid_completion_pct", 0)
            viols = res.get("violations", 0)
            cols = res.get("collisions", 0)
            st = res.get("status", "?")
            icon = "✅" if st == "PASS" else ("⚠️" if st == "WARN" else "❌")
            lines.append(f"| {cid} | {util:.1f}% | {rigid:.1f}% | {viols} | {cols} | {icon} {st} |")
        if len(items) > 30:
            lines.append("")
            lines.append("</details>")
        lines.append("")

    # ── 行动建议 ──
    if clusters:
        lines.append("## 行动建议")
        by_role = {}
        for c in clusters:
            role = c.get("suggested_fix", {}).get("agent_role", "A")
            by_role.setdefault(role, []).append(c)
        for role in sorted(by_role.keys()):
            lines.append(f"### 角色 {role}")
            for c in by_role[role]:
                fix = c.get("suggested_fix", {})
                lines.append(f"- [{c['fault_type']}] {fix.get('description', '')} → `{fix.get('code_location', '')}`")
            lines.append("")

    return "\n".join(lines)


def generate_reports(results_path: str, analysis_path: str,
                     md_path: str, json_path: str, show_trend: bool = False):
    """生成 Markdown + JSON 报告"""
    results = _load_json(results_path)
    analysis = _load_json(analysis_path)

    if not results:
        print(f"❌ 未找到测试结果: {results_path}")
        return
    if not analysis:
        print(f"⚠️ 未找到分析数据: {analysis_path}，将生成简化报告")
        analysis = {"summary": {}, "fault_clusters": [], "diff": {}}

    trend_text = ""
    if show_trend:
        trend_text = _build_trend(os.path.join(REPORTS_DIR, "history"))

    # Markdown 报告
    md_content = generate_md_report(results, analysis, trend_text)
    os.makedirs(os.path.dirname(md_path), exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    # JSON 报告
    combined = {
        "generated_at": datetime.now().isoformat(),
        "results": results,
        "analysis": analysis,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)

    # 控制台摘要
    s = analysis.get("summary", {})
    clusters = analysis.get("fault_clusters", [])
    print(f"\n{'='*60}")
    print(f" 📋 3D-AICIVS 测试报告已生成")
    print(f"{'='*60}")
    print(f" 用例: {s.get('total', 0)} | 通过 {s.get('passed', 0)} | 失败 {s.get('failed', 0)}")
    print(f" 平均利用率: {s.get('avg_utilization', 0):.1f}%")
    if clusters:
        print(f" Top 故障:")
        for c in clusters[:3]:
            print(f"   • {c['fault_type']} ({c['count']}) → {c['suggested_fix']['description']}")
    print(f" 📁 Markdown: {md_path}")
    print(f" 📁 JSON: {json_path}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="3D-AICIVS 结构化报告生成器")
    parser.add_argument("--input", default="tests/harness_reports/latest_results.json")
    parser.add_argument("--analysis", default="tests/harness_reports/latest_analysis.json")
    parser.add_argument("--out-md", default="tests/harness_reports/latest_report.md")
    parser.add_argument("--out-json", default="tests/harness_reports/latest_report.json")
    parser.add_argument("--trend", action="store_true", help="包含历史趋势")
    parser.add_argument("--last", type=int, default=10, help="趋势回溯次数")
    args = parser.parse_args()

    def abs_p(p):
        return p if os.path.isabs(p) else os.path.join(PROJECT_ROOT, p)

    generate_reports(abs_p(args.input), abs_p(args.analysis),
                     abs_p(args.out_md), abs_p(args.out_json), args.trend)


if __name__ == "__main__":
    main()
