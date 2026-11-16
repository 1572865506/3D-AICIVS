"""构建自学习数据集：虚拟货单 × 三个策略档 → JSONL（每行一次求解结果）。

为什么不用人工标价：先用"统一评分"自动生成弱标签（同一货单里 T0/T1 通过且
总分最高的策略），再通过留一验证判断这个选择器是否值得启用；不值得就回退
手工策略。人工专家标注后续可作为加权/纠正信号接入。

运行：
  python scripts/build_learning_dataset.py --time-budget 15
  python scripts/build_learning_dataset.py --quick 3      # 冒烟
被谁调用：人工/CI 数据采集；train_policy_selector.py 消费输出。
"""

import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.api.adapter import InputAdapter  # noqa: E402
from backend.solver_v2.evaluation import detect_scenario, evaluate_plan  # noqa: E402
from backend.solver_v2.evaluation.product import build_product_options  # noqa: E402
from backend.solver_v2.learning.features import extract_features  # noqa: E402
from backend.solver_v2.solver.unified_solver import UnifiedSolver  # noqa: E402

DEFAULT_DIR = os.path.join(PROJECT_ROOT, "tests", "cases", "virtual")
DEFAULT_OUT = os.path.join(PROJECT_ROOT, "tests", "harness_reports", "learning_dataset.jsonl")
DEFAULT_SUMMARY = os.path.join(PROJECT_ROOT, "tests", "harness_reports", "learning_dataset_summary.json")
DEFAULT_POLICIES = "SAFETY_FIRST,BALANCED,VOLUME_FIRST"


def _load_cases(case_dir):
    out = []
    for path in sorted(glob.glob(os.path.join(case_dir, "*.json"))):
        with open(path, "r", encoding="utf-8") as f:
            out.append(json.load(f))
    return out


def _public_eval(ev):
    return {
        "score": ev.get("score"),
        "grade": ev.get("grade"),
        "hard_fail": ev.get("hard_fail"),
        "policy": ev.get("policy"),
        "tiers": ev.get("tiers"),
        "metrics": ev.get("metrics"),
        "gate": ev.get("gate"),
        "deductions": (ev.get("deductions") or [])[:5],
    }


def main():
    parser = argparse.ArgumentParser(description="构建策略选择器训练数据")
    parser.add_argument("--dir", default=DEFAULT_DIR)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--time-budget", type=float, default=15.0)
    parser.add_argument("--policies", default=DEFAULT_POLICIES)
    parser.add_argument("--quick", type=int, default=0)
    args = parser.parse_args()

    cases = _load_cases(args.dir)
    if args.quick:
        cases = cases[:args.quick]
    policies = [p.strip().upper() for p in args.policies.split(",") if p.strip()]
    if not cases:
        raise SystemExit(f"No cases in {args.dir}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    records = []
    print("=" * 96)
    print(f"策略数据集 | {len(cases)} 例 × {len(policies)} 策略 | 预算 {args.time_budget}s")
    print("=" * 96)
    for idx, case in enumerate(cases, 1):
        container = InputAdapter.parse_container(case["container"])
        cargo = InputAdapter.parse_cargo_list(case["cargo"])
        scenario = detect_scenario(cargo, container)
        features = extract_features(cargo, container)
        best = None
        for policy in policies:
            options = build_product_options(cargo, policy=policy)
            t0 = time.perf_counter()
            sol = UnifiedSolver(container).solve(
                cargo, time_budget=args.time_budget, options=options)
            runtime = time.perf_counter() - t0
            ev = evaluate_plan(sol, cargo, container, scenario=scenario,
                               sequence_report=compute_loading_order(sol.placements, container))
            record = {
                "case_id": case["case_id"],
                "case_name": case.get("case_name", ""),
                "scenario": scenario["scenario"],
                "policy": policy,
                "features": features,
                "options": options,
                "evaluation": _public_eval(ev),
                "runtime_s": round(runtime, 2),
                "generated_at": datetime.now().isoformat(timespec="seconds"),
            }
            records.append(record)
            key = (float(ev.get("score") or 0.0),
                   float((ev.get("metrics") or {}).get("rigid_ratio") or 0.0))
            if best is None or key > best[0]:
                best = (key, policy, ev)
        print(f"[{idx}/{len(cases)}] {case['case_id']:<32} 最佳={best[1]:<13} "
              f"score={best[2].get('score')} ({best[2].get('grade')})")

    with open(args.out, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    counts = {}
    for rec in records:
        counts[rec["policy"]] = counts.get(rec["policy"], 0) + 1
    summary = {
        "cases": len(cases),
        "policies": policies,
        "records": len(records),
        "time_budget_s": args.time_budget,
        "record_counts": counts,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    with open(args.summary, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("=" * 96)
    print(f"records={len(records)} -> {args.out}")


if __name__ == "__main__":
    main()
