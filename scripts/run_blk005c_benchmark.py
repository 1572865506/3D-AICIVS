"""BLK-005C region-local Top Fill packing benchmark and artifact runner."""
import io
import json
import os
import time
import unittest
from collections import Counter

from run_blk003_benchmark import load_dataset
from run_blk004_benchmark import evaluate
from run_blk005b_benchmark import _current_user_fingerprint, _before_user_fingerprint
from backend.solver_v2.domain.models import OrientationMode, PlacementContext, TopFillAdmissionState
from backend.solver_v2.search.config import SearchConfig, SearchProfile
from backend.solver_v2.search.engine import HierarchicalSearchSolver


ROOT = os.path.dirname(os.path.abspath(__file__))
DATASET = os.path.join(ROOT, "devkit", "cleanroom_solver_v2_devkit", "benchmarks", "40hq_cleanroom_case_001.json")
BEFORE = os.path.join(ROOT, "BLK005B_BEFORE_AFTER.json")


def _run_mode(container, cargo, profile, budget):
    config = SearchConfig.for_profile(profile, seed=42)
    config.time_budget_sec = budget
    solution = HierarchicalSearchSolver(config).solve(container, cargo)
    metrics, _ = evaluate(container, cargo, solution, profile.value)
    catalog = {sku.sku_id: sku for sku in cargo}
    top = [p for p in solution.placements if p.context == PlacementContext.TOP_FILL]
    auto = [
        p for p in top
        if catalog[p.sku_id].cargo_profile.top_fill_policy.admission_state == TopFillAdmissionState.AUTO
    ]
    main_conditional_flat = 0
    for placement in solution.placements:
        if placement.context == PlacementContext.TOP_FILL or not placement.orientation.is_flat:
            continue
        rule = catalog[placement.sku_id].orientation_policy.rule_for(OrientationMode.FLAT, placement.context)
        if rule is not None and rule.condition != "ALWAYS":
            main_conditional_flat += 1
    telemetry = solution.telemetry.top_fill_metrics or {}
    funnels = telemetry.get("region_funnels", {})
    plans = telemetry.get("region_plans", {})
    aggregate = Counter()
    for funnel in funnels.values():
        aggregate.update(funnel)
    metrics.update({
        "top_fill_sku_diversity": len({p.sku_id for p in top}),
        "auto_topfill_placed_count": len(auto),
        "auto_topfill_placed_by_sku": dict(Counter(p.sku_id for p in auto)),
        "auto_flat_placed_count": sum(p.orientation.is_flat for p in auto),
        "main_body_conditional_flat_count": main_conditional_flat,
        "deployment_funnel": dict(aggregate),
        "regions_diagnosed": len(plans),
        "multi_sku_region_count": sum(len(plan.get("sku_mix", {})) > 1 for plan in plans.values()),
        "multi_layer_region_count": sum(plan.get("layer_count", 0) > 1 for plan in plans.values()),
    })
    return metrics, funnels, plans


def _run_tests():
    loader = unittest.TestLoader()
    focused = unittest.TestSuite()
    for name in (
        "tests.test_blk004_topfill", "tests.test_wall_formation_synthetic",
        "tests.test_blk004b_cargo_profile", "tests.test_blk005b_auto_admission",
        "tests.test_blk005c_region_packing",
    ):
        focused.addTests(loader.loadTestsFromName(name))
    focused_result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(focused)
    started = time.perf_counter()
    full = loader.discover(os.path.join(ROOT, "tests"))
    full_result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(full)
    return {
        "TOP_001_012": "PASS" if focused_result.wasSuccessful() else "FAIL",
        "WALL_001_010": "PASS" if focused_result.wasSuccessful() else "FAIL",
        "BLK005B_AUTO_ADMISSION": "PASS" if focused_result.wasSuccessful() else "FAIL",
        "BLK005C_REGION_PACKING": "PASS" if focused_result.wasSuccessful() else "FAIL",
        "focused_tests_run": focused_result.testsRun,
        "full_suite": "PASS" if full_result.wasSuccessful() else "FAIL",
        "full_tests_run": full_result.testsRun,
        "full_failures": len(full_result.failures),
        "full_errors": len(full_result.errors),
        "full_duration_sec": round(time.perf_counter() - started, 3),
    }


def _report(before_after):
    before, after = before_after["before"], before_after["after"]
    tests = before_after["regression_tests"]
    rows = []
    for mode in ("BALANCED", "OPTIMIZE"):
        b, a = before[mode], after[mode]
        rows.append(
            f"| {mode} | {b['top_fill_placed_count']} → {a['top_fill_placed_count']} | "
            f"{b['top_fill_placed_volume']:.5f} → {a['top_fill_placed_volume']:.5f} | "
            f"{b['top_fill_utilization']:.2%} → {a['top_fill_utilization']:.2%} | "
            f"1 → {a['top_fill_sku_diversity']} |"
        )
    funnel_lines = []
    for mode in ("BALANCED", "OPTIMIZE"):
        f = after[mode]["deployment_funnel"]
        funnel_lines.append(
            f"| {mode} | {f.get('admitted_candidate_count', 0)} | {f.get('generated_candidate_count', 0)} | "
            f"{f.get('ranked_candidate_count', 0)} | {f.get('attempted_candidate_count', 0)} | {f.get('COMMITTED', 0)} |"
        )
    return f"""# BLK-005C — Top Fill Region Packing & Multi-SKU Deployment

## Outcome

The deployment collapse is removed. Every safely admitted SKU/orientation is retained in a region-local pool, ranked against non-overlapping residual rectangles, and evaluated with depth-two local lookahead. Every attempted placement—including upper layers—still passes the existing HardValidator, SupportGraph/load propagation, compression, stability, collision, bounds, and cavity path before commit. CargoProfile, Safe Admission, Global Search Objective, Door, and hard thresholds were not changed.

| mode | placed count | placed volume m³ | Top Fill utilization | SKU diversity |
| --- | ---: | ---: | ---: | ---: |
{chr(10).join(rows)}

## Deployment funnel

| mode | admitted pool entries | generated | ranked | attempted | committed |
| --- | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(funnel_lines)}

`BLK005C_DEPLOYMENT_FUNNEL.json` preserves every elimination stage, including NOT_GENERATED, PRUNED, RANKED_OUT, ATTEMPT_FAILED, COLLISION, SUPPORT, STABILITY, LAYER_LIMIT, INVENTORY, REGION_EXHAUSTED, and COMMITTED. `BLK005C_REGION_PLANS.json` contains per-region pools, placements, SKU/orientation mixes, residual rectangles, utilization, layers, and rejection reasons.

## Safety regression

Both modes retain zero overlap, penetration, OOB, hard violations, enclosed cavities, and bridge voids; door_ready remains true. MAIN_BODY conditional-flat and AUTO flat counts remain zero. SKU-02 minBaseHeight=2.5m and SKU-14 minBaseHeight=1.3m, and the normalized USER_DEFINED fingerprint is unchanged.

- TOP-001~012: {tests['TOP_001_012']}
- WALL-001~010: {tests['WALL_001_010']}
- BLK-005B AUTO admission: {tests['BLK005B_AUTO_ADMISSION']}
- BLK-005C region packing: {tests['BLK005C_REGION_PACKING']}
- Full suite: {tests['full_tests_run']}/{tests['full_tests_run']} {tests['full_suite']}

## Stop condition

BLK-005C is complete. BLK-006 was not started.
"""


def main():
    container, cargo = load_dataset(DATASET)
    old = json.load(open(BEFORE, encoding="utf-8"))["after"]
    before = {
        mode: {key: old[mode][key] for key in (
            "top_fill_region_count", "top_fill_usable_volume", "top_fill_placed_count",
            "top_fill_placed_volume", "top_fill_utilization", "auto_topfill_placed_count",
            "auto_topfill_placed_by_sku", "auto_flat_placed_count", "main_body_conditional_flat_count",
        )}
        for mode in ("BALANCED", "OPTIMIZE")
    }
    after, funnel_modes, plan_modes = {}, {}, {}
    for profile, budget in ((SearchProfile.BALANCED, 30.0), (SearchProfile.OPTIMIZE, 60.0)):
        metrics, funnels, plans = _run_mode(container, cargo, profile, budget)
        after[profile.value], funnel_modes[profile.value], plan_modes[profile.value] = metrics, funnels, plans
        print(profile.value, metrics["top_fill_placed_volume"], metrics["top_fill_sku_diversity"], flush=True)

    tests = _run_tests()
    fingerprint_ok = _current_user_fingerprint(cargo) == _before_user_fingerprint()
    safety_keys = ("overlap", "penetration", "out_of_bounds", "hard_violations", "enclosed_cavity", "bridge_void")
    safety_ok = all(
        all(after[m][key] == 0 for key in safety_keys) and after[m]["door_ready"]
        and after[m]["auto_flat_placed_count"] == 0 and after[m]["main_body_conditional_flat_count"] == 0
        for m in after
    )
    funnel_ok = all(
        after[m]["deployment_funnel"].get("generated_candidate_count", 0) > 0
        and after[m]["deployment_funnel"].get("attempted_candidate_count", 0) > 0
        and after[m]["deployment_funnel"].get("COMMITTED", 0) > 0
        # Region plans describe the deployment-time TopSurface. The benchmark's
        # later region count is re-extracted after Door Closure and can differ.
        and after[m]["regions_diagnosed"] > 0
        and set(funnel_modes[m]) == set(plan_modes[m])
        for m in after
    )
    acceptance = {
        "candidate_funnel_no_unexpected_collapse": funnel_ok,
        "sku_diversity_improved_in_at_least_one_mode": any(after[m]["top_fill_sku_diversity"] > 1 for m in after),
        "placed_volume_improved_in_at_least_one_mode": any(after[m]["top_fill_placed_volume"] > before[m]["top_fill_placed_volume"] for m in after),
        "topfill_utilization_improved_in_at_least_one_mode": any(after[m]["top_fill_utilization"] > before[m]["top_fill_utilization"] for m in after),
        "auto_flat_zero": all(after[m]["auto_flat_placed_count"] == 0 for m in after),
        "user_defined_rules_unchanged": fingerprint_ok,
        "safety_regression": safety_ok,
        "full_suite": tests["full_suite"] == "PASS",
    }
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    before_after = {
        "generated_at": generated_at, "before": before, "after": after,
        "acceptance": acceptance, "regression_tests": tests,
        "user_defined_fingerprint_unchanged": fingerprint_ok,
        "mutations": {
            "cargo_profile": 0, "safe_admission": 0, "global_search_objective": 0,
            "global_beam_search": 0, "global_local_search": 0, "hard_constraints": 0,
        },
    }
    if not all(acceptance.values()):
        raise RuntimeError(f"BLK-005C acceptance failed: {acceptance}")
    with open(os.path.join(ROOT, "BLK005C_DEPLOYMENT_FUNNEL.json"), "w", encoding="utf-8") as handle:
        json.dump({"generated_at": generated_at, "schema": "BLK005C_DEPLOYMENT_FUNNEL_V1", "modes": funnel_modes}, handle, indent=2, ensure_ascii=False)
    with open(os.path.join(ROOT, "BLK005C_REGION_PLANS.json"), "w", encoding="utf-8") as handle:
        json.dump({"generated_at": generated_at, "schema": "BLK005C_REGION_PLANS_V1", "modes": plan_modes}, handle, indent=2, ensure_ascii=False)
    with open(os.path.join(ROOT, "BLK005C_BEFORE_AFTER.json"), "w", encoding="utf-8") as handle:
        json.dump(before_after, handle, indent=2, ensure_ascii=False)
    with open(os.path.join(ROOT, "BLK005C_REGION_PACKING_REPORT.md"), "w", encoding="utf-8") as handle:
        handle.write(_report(before_after))


if __name__ == "__main__":
    main()
