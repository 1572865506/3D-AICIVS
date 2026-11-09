"""
单用例全维诊断脚本（确定性调试入口）。

用途：对指定货单夹具跑一次求解并输出"算法 + 门禁"契合度全景：
利用率/履约、逐 SKU 装缺、门禁逐条裁决、几何观感、空腔 Top、拒绝原因分布。
供算法调试与门禁政策复核使用，不参与 CI。

用法：
    python scripts/diagnose_case.py tests/fixtures/production_15sku.json
    python scripts/diagnose_case.py tests/fixtures/production_15sku.json --lns
"""
import argparse
import json
import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.solver.unified_solver import UnifiedSolver
from backend.solver_v2.validation.delivery_gate import evaluate_delivery


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture", help="用例 JSON 路径（container/cargo/case_id）")
    ap.add_argument("--lns", action="store_true", help="启用 LNS 批处理改进")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非可读报告")
    args = ap.parse_args()

    with open(args.fixture, "r", encoding="utf-8") as f:
        case = json.load(f)

    container = InputAdapter.parse_container(case["container"])
    cargo = InputAdapter.parse_cargo_list(case["cargo"])
    solver = UnifiedSolver(container)
    options = {"lns_enabled": True, "lns_budget_s": 8.0, "lns_rounds": 12} if args.lns else None

    t0 = time.perf_counter()
    sol = solver.solve(cargo, options=options)
    wall = time.perf_counter() - t0
    gate = evaluate_delivery(sol, cargo, container)
    qa = sol.telemetry.geometry_qa or {}

    req_total = sum(c["quantity"] for c in case["cargo"])
    req_vol = sum(c["w"] * c["d"] * c["h"] * c["quantity"] for c in case["cargo"])
    placed_by_sku = {}
    for p in sol.placements:
        placed_by_sku[p.sku_id] = placed_by_sku.get(p.sku_id, 0) + 1

    report = {
        "case_id": case.get("case_id"),
        "wall_s": round(wall, 1),
        "volume": {
            "requested_m3": round(req_vol, 2),
            "container_m3": round(container.volume, 2),
            "requested_ratio_pct": round(100.0 * req_vol / container.volume, 1),
        },
        "result": {
            "placed": sol.placed_count,
            "requested": req_total,
            "utilization_pct": round(sol.volume_utilization_pct, 2),
            "status": sol.status,
            "violations": len(sol.validation_result.violations),
        },
        "fulfillment": [
            {
                "sku": c["sku"],
                "name": c.get("name", ""),
                "placed": placed_by_sku.get(c["sku"], 0),
                "requested": c["quantity"],
                "short": max(0, c["quantity"] - placed_by_sku.get(c["sku"], 0)),
                "requirement": c.get("requirement", ""),
            }
            for c in case["cargo"]
        ],
        "delivery_gate": {
            "verdict": gate["verdict"],
            "blocked_by": gate["blocked_by"],
            "warnings": gate["warnings"],
            "cog": gate["cog"],
            "checks": [
                {k: ch[k] for k in ("id", "severity", "measured", "limit", "passed", "detail")}
                for ch in gate["checks"]
            ],
        },
        "geometry_qa": {
            "verdict": qa.get("verdict"),
            "penalty": qa.get("penalty_score"),
            "bbox_void_pct": qa.get("bbox_void_ratio_pct"),
            "hidden_void_pct": (qa.get("cavities") or {}).get("hidden_void_pct_of_bbox"),
            "skyline_void_pct": (qa.get("cavities") or {}).get("skyline_void_pct_of_bbox"),
            "steep_step_pct": (qa.get("top_surface") or {}).get("steep_step_ratio_pct"),
            "partial_support_pct": (qa.get("support") or {}).get("partial_support_ratio_pct"),
            "islands": qa.get("islands"),
        },
        "cavities_top": (qa.get("cavities") or {}).get("top", [])[:5],
        "rejections_top": dict(sorted(
            (sol.telemetry.candidates_rejected_by_reason or {}).items(),
            key=lambda kv: -kv[1])[:8]),
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0

    print("=" * 78)
    print(f"用例: {report['case_id']} | 耗时 {report['wall_s']}s")
    v = report["volume"]
    r = report["result"]
    print(f"体积: 请求 {v['requested_m3']} m3 = 柜容 {v['container_m3']} m3 的 {v['requested_ratio_pct']}%")
    print(f"结果: 装 {r['placed']}/{r['requested']} | 利用率 {r['utilization_pct']}% | 违规 {r['violations']} | {r['status']}")
    print("-" * 78)
    print("逐 SKU 装缺:")
    for f in report["fulfillment"]:
        flag = "❌缺" if f["short"] else "✅"
        print(f"  {flag} {f['sku']:<7} {f['placed']:>4}/{f['requested']:<4} 缺 {f['short']:<4} "
              f"[{f['requirement'] or '—'}] {f['name'][:22]}")
    print("-" * 78)
    g = report["delivery_gate"]
    print(f"交付门禁: {g['verdict']} | 拦截 {g['blocked_by']} | 告警 {g['warnings']}")
    cog = g["cog"]
    print(f"  重心偏移: 纵 {cog.get('long_offset_pct')}% 横 {cog.get('lat_offset_pct')}%")
    print("  逐条:")
    for ch in g["checks"]:
        mark = "✅" if ch["passed"] else ("⛔" if ch["severity"] == "BLOCK" else "⚠")
        print(f"    {mark} {ch['id']} {ch['severity']:<5} 实测={ch['measured']} 阈值={ch['limit']}"
              + (f" | {ch['detail']}" if ch["detail"] else ""))
    print("-" * 78)
    q = report["geometry_qa"]
    print(f"几何观感: {q['verdict']} (penalty {q['penalty']}) | bbox 空洞 {q['bbox_void_pct']}% "
          f"= 隐蔽 {q['hidden_void_pct']}% + 天窗 {q['skyline_void_pct']}%")
    print(f"  顶面硬台阶 {q['steep_step_pct']}% | 半悬空 {q['partial_support_pct']}% | 孤立箱 {q['islands']}")
    print("  空腔 Top5:")
    for c in report["cavities_top"]:
        print(f"    {c['volume_m3']:>7.3f} m3 {c['dims']} {c['category']} open={c['open']}")
    print(f"拒绝原因 Top: {report['rejections_top']}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
