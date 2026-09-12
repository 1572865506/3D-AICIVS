import sys
import os
import argparse
import time

REPO_ROOT = r"c:\Users\郑\Documents\antigravity\charming-turing"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import tests.benchmark_suite as bs


def run_diagnosis(case_filter=None):
    cases = [
        bs.get_benchmark_case_1_14sku(),
        bs.get_benchmark_case_2_single_large(),
        bs.get_benchmark_case_3_all_elastic(),
        bs.get_benchmark_case_4_door_dense(),
        bs.get_benchmark_case_5_mixed_heterogeneous(),
    ]
    json_cases = bs.load_json_cases()
    if json_cases:
        cases.extend(json_cases)

    if case_filter:
        cases = [c for c in cases if case_filter.lower() in c[3].lower() or case_filter.lower() in c[2].lower()]
        if not cases:
            print(f"[ERROR] No benchmark case matching '{case_filter}' found.")
            return

    print("=" * 100)
    print(f" 📦 3D-AICIVS SKU FULFILLMENT & STARVATION DIAGNOSTIC (Total {len(cases)} cases)")
    print("=" * 100)

    for i, (spec, cargo, cid, name, desc) in enumerate(cases, 1):
        t0 = time.time()
        res = bs.execute_benchmark_case(spec, cargo, cid, name, desc)
        t_cost = time.time() - t0

        util = res["utilization"]
        collisions = res["collisions"]
        violations = res["violations"]
        
        sku_ful = res.get("sku_fulfillment", {})
        rigid_req = sku_ful.get("rigid_required", 0)
        rigid_placed = sku_ful.get("rigid_placed", 0)
        rigid_pct = sku_ful.get("rigid_completion_pct", 0.0)
        elastic_req = sku_ful.get("elastic_required", 0)
        elastic_placed = sku_ful.get("elastic_placed", 0)
        elastic_pct = sku_ful.get("elastic_completion_pct", 0.0)
        starved = sku_ful.get("starved_skus", [])
        inv = sku_ful.get("priority_inversion", False)
        health = res.get("health_status", "UNKNOWN")

        status_icon = "✅ PASS" if (rigid_pct >= 99.0 and violations == 0 and collisions == 0) else "❌ FAIL"

        print(f"\n[{i}/{len(cases)}] {name} ({cid}) -> [{status_icon}] ({t_cost:.2f}s)")
        print(f"  空间利用率: {util:.2f}% | 刚性履行率: {rigid_pct:.1f}% ({rigid_placed}/{rigid_req}) | 弹性完成率: {elastic_pct:.1f}% ({elastic_placed}/{elastic_req})")
        print(f"  物理碰撞: {collisions} | 约束违规: {violations} | 优先级倒挂: {'⚠️ 存在 (弹性件侵占刚性)' if inv else '否'} | 健康状态: {health}")

        # Missing breakdown
        details = sku_ful.get("sku_details", {})
        missing_skus = [
            (sid, info) for sid, info in details.items()
            if info["placed"] < info["required"]
        ]

        if missing_skus:
            print(f"  ⚠️ 未满载 SKU 列表 (共 {len(missing_skus)} 种):")
            for sid, m in missing_skus:
                sku_type = "弹性件" if m["is_elastic"] else "【刚性件漏装】"
                diff = m["required"] - m["placed"]
                print(f"    - {sid} ({m['name']}) [{sku_type}]: 放置 {m['placed']}/{m['required']} ({m['completion_pct']}%), 漏装 {diff} 件")
        else:
            print("  ✨ 所有 SKU 100% 满额装载！")

        if starved:
            print(f"  🚨 严重弃装/饥饿 SKU: {starved}")

    print("\n" + "=" * 100)
    print(" 诊断完成。")
    print("=" * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SKU Diagnostic Tool")
    parser.add_argument("--case", type=str, default=None, help="Filter by case name or ID substring (e.g. 14-SKU)")
    args = parser.parse_args()
    run_diagnosis(args.case)
