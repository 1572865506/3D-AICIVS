"""从全量基准结果生成 PlanScore 基准（tests/plan_score_baseline.json）。

用途：给后续"自测试 + 评分棘轮 + 自我学习"提供统一的方案质量参照。
数据源必须是 tests/benchmark_results.json（由 tests/benchmark_suite.py --run 生成）；
基准使用算法默认选项，产品安全默认（server/UI 层）不在基准口径内。

运行：python scripts/build_plan_score_baseline.py
被谁调用：人工/CI 在基准重跑后更新评分基准。
"""

import json
import os
from datetime import date

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(PROJECT_ROOT, "tests", "benchmark_results.json")
TARGET = os.path.join(PROJECT_ROOT, "tests", "plan_score_baseline.json")


def main() -> None:
    with open(SOURCE, "r", encoding="utf-8") as f:
        data = json.load(f)

    results = data.get("results") or {}
    cases = {}
    for case_id, res in results.items():
        ps = (res or {}).get("plan_score") or {}
        score = ps.get("score")
        if not isinstance(score, (int, float)):
            continue
        cases[case_id] = {
            "score": score,
            "grade": ps.get("grade"),
            "hard_fail": bool(ps.get("hard_fail")),
            "policy": ps.get("policy"),
            "scenario": ps.get("scenario"),
            "tiers": ps.get("tiers") or {},
            "metrics": ps.get("metrics") or {},
        }

    scores = sorted(float(c["score"]) for c in cases.values())
    median = ""
    if scores:
        mid = len(scores) // 2
        median = round(scores[mid] if len(scores) % 2 else (scores[mid - 1] + scores[mid]) / 2.0, 1)

    policy_counts = {}
    for c in cases.values():
        key = c.get("policy") or "UNKNOWN"
        policy_counts[key] = policy_counts.get(key, 0) + 1

    grades = {g: 0 for g in ("A", "B", "C", "D", "F")}
    for c in cases.values():
        g = c.get("grade")
        if g in grades:
            grades[g] += 1

    payload = {
        "schema": 1,
        "generated_at": date.today().isoformat(),
        "source": "tests/benchmark_results.json (算法默认选项；产品安全默认在 server/UI 层)",
        "note": "PlanScore 参照基准，供自测试/棘轮/自我学习使用；重跑基准后需重新生成本文件。",
        "case_count": len(cases),
        "stats": {
            "median": median,
            "min": round(scores[0], 1) if scores else "",
            "max": round(scores[-1], 1) if scores else "",
            "grades": grades,
        },
        "policy_counts": policy_counts,
        "cases": cases,
    }
    with open(TARGET, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"PlanScore baseline written: {TARGET} ({len(cases)} cases, median={median})")


if __name__ == "__main__":
    main()
