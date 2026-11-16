"""虚拟货单验收：按"产品真实交付默认"跑模拟货单，输出可用性报告。

与 benchmark/regression_guard 的区别：
- benchmark 用算法默认选项，关注算法回归；
- 本脚本用 server/UI 的产品默认（策略档 + 门区安全），关注"实际交付是否可用"。

验收维度：
- 硬约束：0 违规 / 0 碰撞 / 无刚性饥饿
- 门禁：非预期 REJECT（meta.expected_reject 允许载重类预期拒绝）
- 安全：含刚性封门件时门面 SF≥1.5（无门面货堆视为不适用）
- 履约：刚性履行 ≥99%
- 装载率：低于"请求体积比 × 0.85"给 WARN（只提示，不判死）

运行：
  python scripts/run_acceptance.py --quick 3
  python scripts/run_acceptance.py --time-budget 25
被谁调用：人工/CI 验收；dashboard 可读取 acceptance_report.json。
"""

import argparse
import glob
import json
import os
import statistics
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.api.adapter import InputAdapter  # noqa: E402
from backend.solver_v2.evaluation import detect_scenario, evaluate_plan  # noqa: E402
from backend.solver_v2.evaluation.product import (  # noqa: E402
    build_product_options, has_rigid_door)
from backend.solver_v2.solver.unified_solver import UnifiedSolver  # noqa: E402

DEFAULT_DIR = os.path.join(PROJECT_ROOT, "tests", "cases", "virtual")
DEFAULT_OUT = os.path.join(PROJECT_ROOT, "tests", "harness_reports", "acceptance_report.json")


def _load_cases(case_dir: str):
    cases = []
    for path in sorted(glob.glob(os.path.join(case_dir, "*.json"))):
        with open(path, "r", encoding="utf-8") as f:
            cases.append((path, json.load(f)))
    return cases


def _requested_volume_ratio(cargo, container) -> float:
    req_vol = sum(s.box.x * s.box.y * s.box.z * s.quantity.required for s in cargo)
    return req_vol / max(1e-9, container.volume)


def _evaluate_case(case, time_budget: float, policy_override: str = "auto",
                   deferred_tipping_audit: bool = False):
    container = InputAdapter.parse_container(case["container"])
    cargo = InputAdapter.parse_cargo_list(case["cargo"])
    scenario = detect_scenario(
        cargo, container,
        requested_policy=None if policy_override == "auto" else policy_override)
    options = build_product_options(cargo, policy=scenario["policy"])
    meta = case.get("meta") or {}
    if deferred_tipping_audit or meta.get("deferred_tipping_audit"):
        options["deferred_tipping_audit"] = True
    expected_error = set(meta.get("expected_error") or [])

    # 预检与 server 一致：配置不可行时不应继续求解/静默饥饿
    from backend.solver_v2.validation.config_precheck import precheck_manifest
    pre = precheck_manifest(cargo, container, options=options)
    if pre["errors"]:
        error_codes = [e.get("code", "CONFIG_UNSATISFIABLE") for e in pre["errors"]]
        expected = bool(set(error_codes) & expected_error)
        return {
            "case_id": case["case_id"],
            "case_name": case.get("case_name", case["case_id"]),
            "synthetic": bool(meta.get("synthetic")),
            "policy": scenario["policy"],
            "scenario": scenario["scenario"],
            "options": options,
            "status": "EXPECTED_REJECT" if expected else "FAIL",
            "score": None, "grade": None,
            "utilization_pct": None, "placed_count": None,
            "rigid_ratio": None, "door_min_sf": None,
            "unstable_volume_m3": None, "plan_quality_score": None,
            "gate": {"verdict": "PRECHECK_REJECT", "blocked_by": sorted(set(error_codes))},
            "time_budget_s": time_budget,
            "floor_limited": bool(meta.get("floor_limited")),
            "known_issue": meta.get("known_issue"),
            "runtime_s": 0.0,
            "checks": {"precheck": {
                "passed": expected,
                "detail": "；".join(e.get("message", "") for e in pre["errors"][:3]),
            }},
            "deductions": [e.get("message", "") for e in pre["errors"][:3]],
        }

    t0 = time.perf_counter()
    sol = UnifiedSolver(container).solve(
        cargo, time_budget=time_budget, options=options)
    runtime = time.perf_counter() - t0
    ev = evaluate_plan(sol, cargo, container, scenario=scenario)
    gate = ev.get("gate") or {}
    metrics = ev.get("metrics") or {}
    expected_reject = set(meta.get("expected_reject") or [])
    req_weight = sum(float(getattr(s, "weight_kg", 0.0) or 0.0) * s.quantity.required
                     for s in cargo)
    payload_limited = bool(
        getattr(container, "max_payload_kg", 0)
        and req_weight > float(container.max_payload_kg))
    # 载重受限/预期拒绝的货单：履约与装载率不设硬门槛（物理上装不完）
    exempt_fulfillment = bool(expected_reject or payload_limited)
    floor_limited = bool(meta.get("floor_limited"))
    known_issue = meta.get("known_issue")

    checks = {}

    def add(name, passed, detail=""):
        checks[name] = {"passed": bool(passed), "detail": detail}

    add("no_violations", not sol.validation_result.violations,
        f"{len(sol.validation_result.violations)} violations")
    add("no_collision", int(getattr(sol.validation_result, "overlap_pair_count", 0) or 0) == 0)
    starved = list(metrics.get("starved_rigid_skus") or [])
    add("no_starvation", not starved, f"starved={starved[:5]}")

    blocked = set(gate.get("blocked_by") or [])
    unexpected = blocked - expected_reject
    add("gate_not_rejected", not unexpected,
        f"blocked={sorted(blocked)}" + (f"（预期 {sorted(expected_reject)}）" if expected_reject else ""))

    if has_rigid_door(cargo):
        sf = metrics.get("door_min_sf")
        add("door_open_safe", sf is None or float(sf) >= 1.5, f"min_sf={sf}")
    else:
        add("door_open_safe", True, "无刚性封门件（不适用）")
    # 无封门件但门面仍有货堆：不作为硬失败，但必须提示开门风险
    face_sf = metrics.get("door_min_sf")
    if not has_rigid_door(cargo) and face_sf is not None:
        add("door_face_risk", float(face_sf) >= 1.5,
            f"门面无刚性封门件但 SF={face_sf}（开门风险，建议加固/调整）")

    add("rigid_fulfillment", exempt_fulfillment
        or float(metrics.get("rigid_ratio", 0.0)) >= 0.99,
        ("载重受限/预期拒绝，不设硬门槛；" if exempt_fulfillment else "")
        + f"{float(metrics.get('rigid_ratio', 0.0)) * 100:.2f}%")

    ratio = _requested_volume_ratio(cargo, container)
    util_floor = min(75.0, 100.0 * ratio * 0.85)
    add("utilization", exempt_fulfillment or floor_limited
        or float(metrics.get("utilization_pct", 0.0)) >= util_floor,
        ("载重受限/预期拒绝/仅落地件，不设利用率门槛；" if (exempt_fulfillment or floor_limited) else "")
        + f"{metrics.get('utilization_pct')}% (参考下限 {util_floor:.1f}%, 请求体积比 {ratio*100:.1f}%)")

    warn_checks = {"utilization", "door_face_risk"}
    failed = [k for k, v in checks.items() if not v["passed"] and k not in warn_checks]
    warn = [k for k, v in checks.items() if not v["passed"] and k in warn_checks]
    status = "FAIL" if failed else ("WARN" if warn else "PASS")
    if status == "FAIL" and known_issue:
        status = "KNOWN"

    return {
        "case_id": case["case_id"],
        "case_name": case.get("case_name", case["case_id"]),
        "synthetic": bool((case.get("meta") or {}).get("synthetic")),
        "policy": ev.get("policy"),
        "scenario": scenario["scenario"],
        "options": options,
        "status": status,
        "score": ev.get("score"),
        "grade": ev.get("grade"),
        "utilization_pct": metrics.get("utilization_pct"),
        "placed_count": metrics.get("placed_count"),
        "rigid_ratio": metrics.get("rigid_ratio"),
        "door_min_sf": metrics.get("door_min_sf"),
        "unstable_volume_m3": metrics.get("transport_unstable_volume_m3"),
        "plan_quality_score": metrics.get("plan_quality_score"),
        "gate": {"verdict": gate.get("verdict"), "blocked_by": sorted(blocked)},
        "time_budget_s": time_budget,
        "floor_limited": floor_limited,
        "known_issue": known_issue,
        "runtime_s": round(runtime, 2),
        "checks": checks,
        "deductions": ev.get("deductions") or [],
    }


def main():
    parser = argparse.ArgumentParser(description="虚拟货单验收（产品默认口径）")
    parser.add_argument("--dir", default=DEFAULT_DIR)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--quick", type=int, default=0, help="只跑前 N 个用例")
    parser.add_argument("--time-budget", type=float, default=0.0,
                        help="全局预算；0 = 使用每个用例 meta.time_budget_s")
    parser.add_argument("--policy", default="auto",
                        choices=["auto", "SAFETY_FIRST", "BALANCED", "VOLUME_FIRST"])
    parser.add_argument("--deferred-tipping-audit", action="store_true",
                        help="全量开启低稳定纸箱前向支撑墙（A/B 用）")
    args = parser.parse_args()

    cases = _load_cases(args.dir)
    if args.quick and args.quick > 0:
        cases = cases[:args.quick]
    if not cases:
        raise SystemExit(f"No cases found in {args.dir}")

    results = []
    budget_label = f"{args.time_budget}s" if args.time_budget else "按用例 meta"
    print("=" * 96)
    print(f"虚拟货单验收 | {len(cases)} 例 | 预算 {budget_label} | 策略 {args.policy}")
    print("=" * 96)
    for idx, (path, case) in enumerate(cases, 1):
        budget = args.time_budget or float((case.get("meta") or {}).get("time_budget_s") or 25)
        res = _evaluate_case(case, budget, args.policy,
                             deferred_tipping_audit=args.deferred_tipping_audit)
        results.append(res)
        print(f"[{idx}/{len(cases)}] {res['status']:<4} {res['case_id']:<32} "
              f"util={res['utilization_pct']}% rigid={res['rigid_ratio']} "
              f"sf={res['door_min_sf']} score={res['score']} ({res['grade']}) "
              f"budget={budget:g}s {res['runtime_s']}s")
        if res["status"] != "PASS":
            bad = [f"{k}:{v['detail']}" for k, v in res["checks"].items() if not v["passed"]]
            print("        " + "；".join(bad[:4]))

    scores = [r["score"] for r in results if isinstance(r["score"], (int, float))]
    summary = {
        "case_count": len(results),
        "pass": sum(1 for r in results if r["status"] == "PASS"),
        "warn": sum(1 for r in results if r["status"] == "WARN"),
        "known": sum(1 for r in results if r["status"] == "KNOWN"),
        "expected_reject": sum(1 for r in results if r["status"] == "EXPECTED_REJECT"),
        "fail": sum(1 for r in results if r["status"] == "FAIL"),
        "median_score": round(statistics.median(scores), 1) if scores else None,
        "policy_counts": {},
    }
    for r in results:
        summary["policy_counts"][r["policy"]] = summary["policy_counts"].get(r["policy"], 0) + 1

    report = {
        "schema": 1,
        "suite": "virtual_acceptance",
        "time_budget_s": args.time_budget,
        "policy_override": args.policy,
        "summary": summary,
        "cases": results,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("=" * 96)
    print(f"PASS {summary['pass']} / WARN {summary['warn']} / KNOWN {summary['known']} / "
          f"EXPECTED_REJECT {summary['expected_reject']} / "
          f"FAIL {summary['fail']} | PlanScore 中位 {summary['median_score']}")
    print(f"报告: {args.out}")


if __name__ == "__main__":
    main()
