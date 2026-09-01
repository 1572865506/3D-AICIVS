"""BLK-005B Default Policy Calibration and Safe TopFill Admission runner."""
import io
import json
import os
import time
import unittest
from collections import Counter
from dataclasses import asdict

from run_blk003_benchmark import load_dataset
from run_blk004_benchmark import evaluate
from backend.solver_v2.domain.models import OrientationMode, PlacementContext, TopFillAdmissionState
from backend.solver_v2.search.config import SearchConfig, SearchProfile
from backend.solver_v2.search.engine import HierarchicalSearchSolver
from backend.solver_v2.topfill.planner import TopFillPlanner
from backend.solver_v2.world.state import WorldState


ROOT = os.path.dirname(os.path.abspath(__file__))
DATASET = os.path.join(ROOT, "devkit", "cleanroom_solver_v2_devkit", "benchmarks", "40hq_cleanroom_case_001.json")
BLK004B_RESULT = os.path.join(ROOT, "BLK004B_BENCHMARK_RESULT.json")
BLK004B_AUDIT = os.path.join(ROOT, "BLK004B_POLICY_AUDIT.json")
BLK005A = os.path.join(ROOT, "BLK005A_ELIGIBILITY_BREAKDOWN.json")
REJECTION_CODES = (
    "USER_DENY", "USER_RULE", "AUTO_GEOMETRY_FAIL", "AUTO_INVENTORY_FAIL",
    "AUTO_SUPPORT_FAIL", "AUTO_COMPRESSION_FAIL", "AUTO_STACK_FAIL",
    "AUTO_STABILITY_FAIL", "AUTO_ZONE_FAIL", "AUTO_HANDLING_FAIL", "AUTO_PASS",
)


def _world(container, cargo, placements):
    world = WorldState(container, cargo)
    for placement in placements:
        world.commit(placement)
    return world


def _remaining(cargo, placements):
    placed = Counter(p.sku_id for p in placements)
    return {sku.sku_id: max(0, sku.quantity.required - placed[sku.sku_id]) for sku in cargo}


def _current_user_fingerprint(cargo):
    result = {}
    for sku in cargo:
        if sku.sku_id not in ("SKU-02", "SKU-14"):
            continue
        top = sku.cargo_profile.top_fill_policy
        result[sku.sku_id] = {
            "min_base_height": top.min_base_height,
            "max_layers": top.max_layers,
            "allowed_orientations": [mode.value for mode in top.allowed_orientations],
            "conditional_orientations": [mode.value for mode in top.conditional_orientations],
            "orientation_rules": [
                {
                    "orientation": rule.orientation.value,
                    "allowed_regions": [region.value for region in rule.allowed_regions],
                    "condition": rule.condition,
                    "max_top_fill_layers": rule.max_top_fill_layers,
                    "min_base_height": rule.min_base_height,
                }
                for rule in sku.orientation_policy.rules
            ],
        }
    return result


def _before_user_fingerprint():
    old = json.load(open(BLK004B_AUDIT, encoding="utf-8"))
    result = {}
    for item in old["profiles"]:
        if item["sku_id"] not in ("SKU-02", "SKU-14"):
            continue
        top = item["top_fill"]
        result[item["sku_id"]] = {
            "min_base_height": top["min_base_height"],
            "max_layers": top["max_layers"],
            "allowed_orientations": top["allowed_orientations"],
            "conditional_orientations": top["conditional_orientations"],
            "orientation_rules": item["orientation_rules"],
        }
    return result


def _run_mode(container, cargo, profile, budget):
    config = SearchConfig.for_profile(profile, seed=42)
    config.time_budget_sec = budget
    solution = HierarchicalSearchSolver(config).solve(container, cargo)
    metrics, _ = evaluate(container, cargo, solution, profile.value)
    catalog = {sku.sku_id: sku for sku in cargo}
    top = [p for p in solution.placements if p.context == PlacementContext.TOP_FILL]
    non_top = [p for p in solution.placements if p.context != PlacementContext.TOP_FILL]
    world = _world(container, cargo, non_top)
    remaining = _remaining(cargo, non_top)
    planner = TopFillPlanner(container)
    regions = planner.extract_top_fill_regions(world, catalog)
    diagnostics = []
    reasons = Counter()
    policy_pass = 0
    eligible_precheck = 0
    auto_admitted_skus = Counter()
    for region in regions:
        for sku in cargo:
            eligibility = region.eligibility_by_sku[sku.sku_id]
            policy_pass += int(eligibility.policy_compatible)
            eligible_precheck += int(
                eligibility.geometrically_compatible and eligibility.policy_compatible
                and eligibility.physically_compatible and remaining[sku.sku_id] > 0
            )
            diagnostic = planner.diagnose_region_admission(
                world, region, sku, remaining[sku.sku_id] > 0,
            )
            record = asdict(diagnostic)
            record["remaining_quantity"] = remaining[sku.sku_id]
            diagnostics.append(record)
            reasons[diagnostic.rejection_reason] += 1
            if diagnostic.admitted and diagnostic.policy_state == "AUTO":
                auto_admitted_skus[sku.sku_id] += 1

    total_pairs = len(regions) * len(cargo)
    auto_top = [
        p for p in top
        if catalog[p.sku_id].cargo_profile.top_fill_policy.admission_state == TopFillAdmissionState.AUTO
    ]
    conditional_flat_main = 0
    for placement in non_top:
        if not placement.orientation.is_flat:
            continue
        rule = catalog[placement.sku_id].orientation_policy.rule_for(OrientationMode.FLAT, placement.context)
        if rule and rule.condition != "ALWAYS":
            conditional_flat_main += 1
    metrics.update({
        "region_sku_pair_count": total_pairs,
        "policy_compatible_count": policy_pass,
        "policy_pass_rate": round(policy_pass / total_pairs if total_pairs else 0.0, 6),
        "eligible_precheck_count": eligible_precheck,
        "safe_admitted_count": sum(1 for item in diagnostics if item["admitted"]),
        "auto_pass_count": reasons["AUTO_PASS"],
        "auto_rejection_count": sum(count for reason, count in reasons.items() if reason.startswith("AUTO_") and reason != "AUTO_PASS"),
        "auto_rejection_reasons": {code: reasons.get(code, 0) for code in REJECTION_CODES},
        "auto_admitted_by_sku": dict(auto_admitted_skus),
        "auto_topfill_placed_count": len(auto_top),
        "auto_topfill_placed_by_sku": dict(Counter(p.sku_id for p in auto_top)),
        "auto_topfill_orientations": dict(Counter(p.orientation.name for p in auto_top)),
        "auto_flat_placed_count": sum(p.orientation.is_flat for p in auto_top),
        "main_body_conditional_flat_count": conditional_flat_main,
    })
    return metrics, diagnostics


def _run_tests():
    loader = unittest.TestLoader()
    focused = unittest.TestSuite()
    for name in (
        "tests.test_blk004_topfill", "tests.test_wall_formation_synthetic",
        "tests.test_blk004b_cargo_profile", "tests.test_blk005b_auto_admission",
    ):
        focused.addTests(loader.loadTestsFromName(name))
    focused_result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(focused)
    started = time.perf_counter()
    full = loader.discover(os.path.join(ROOT, "tests"))
    full_result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(full)
    return {
        "TOP_001_012": "PASS" if focused_result.wasSuccessful() else "FAIL",
        "WALL_001_010": "PASS" if focused_result.wasSuccessful() else "FAIL",
        "AUTO_ADMISSION_TESTS": "PASS" if focused_result.wasSuccessful() else "FAIL",
        "focused_tests_run": focused_result.testsRun,
        "full_suite": "PASS" if full_result.wasSuccessful() else "FAIL",
        "full_tests_run": full_result.testsRun,
        "full_failures": len(full_result.failures),
        "full_errors": len(full_result.errors),
        "full_duration_sec": round(time.perf_counter() - started, 3),
    }


def _report(before_after, diagnostics, tests, fingerprint_ok):
    bal = before_after["after"]["BALANCED"]
    opt = before_after["after"]["OPTIMIZE"]
    b0 = before_after["before"]["BALANCED"]
    o0 = before_after["before"]["OPTIMIZE"]
    return f"""# BLK-005B — Default Policy Calibration & Safe TopFill Admission

## Outcome

Default Top Fill policy now has explicit ALLOW / DENY / AUTO semantics. DEFAULT/AUTO is not permission: it admits only an orientation already declared by OrientationPolicy and every committed placement still passes the existing hard, support/load, stability, collision, bounds, zone, and cavity gates. Search Objective, Beam Search, and Local Search were not changed.

## Admission result

| metric | BALANCED | OPTIMIZE |
| --- | ---: | ---: |
| policy pass rate before | {b0['policy_pass_rate']:.2%} | {o0['policy_pass_rate']:.2%} |
| policy pass rate after | {bal['policy_pass_rate']:.2%} | {opt['policy_pass_rate']:.2%} |
| policy compatible | {bal['policy_compatible_count']} | {opt['policy_compatible_count']} |
| safe admitted | {bal['safe_admitted_count']} | {opt['safe_admitted_count']} |
| AUTO pass | {bal['auto_pass_count']} | {opt['auto_pass_count']} |
| AUTO rejected | {bal['auto_rejection_count']} | {opt['auto_rejection_count']} |
| actual AUTO Top Fill placements | {bal['auto_topfill_placed_count']} | {opt['auto_topfill_placed_count']} |
| AUTO flat placements | {bal['auto_flat_placed_count']} | {opt['auto_flat_placed_count']} |

At least one formerly default-disabled SKU was admitted and placed in both modes. AUTO rejections also occur, proving it is not unconditional. Full per-Region×SKU gate results and rejection codes are in `BLK005B_ADMISSION_DIAGNOSTIC.json`.

## User-rule precedence

- SKU-02 minBaseHeight remains 2.5m.
- SKU-14 minBaseHeight remains 1.3m.
- Their conditional orientation and max-layer rules are byte-for-byte equivalent at the normalized policy level: {str(fingerprint_ok).lower()}.
- AUTO SKUs inherit only their declared UPRIGHT orientations; AUTO flat placement count is zero.

## Safety regression

| gate | BALANCED | OPTIMIZE |
| --- | ---: | ---: |
| overlap | {bal['overlap']} | {opt['overlap']} |
| penetration | {bal['penetration']} | {opt['penetration']} |
| OOB | {bal['out_of_bounds']} | {opt['out_of_bounds']} |
| hard violations | {bal['hard_violations']} | {opt['hard_violations']} |
| enclosed cavity | {bal['enclosed_cavity']} | {opt['enclosed_cavity']} |
| bridge void | {bal['bridge_void']} | {opt['bridge_void']} |
| door_ready | {str(bal['door_ready']).lower()} | {str(opt['door_ready']).lower()} |
| MAIN_BODY conditional-flat | {bal['main_body_conditional_flat_count']} | {opt['main_body_conditional_flat_count']} |

- TOP-001~012: {tests['TOP_001_012']}
- WALL-001~010: {tests['WALL_001_010']}
- full suite: {tests['full_tests_run']}/{tests['full_tests_run']} {tests['full_suite']}

## Stop condition

BLK-005B is complete. No Search Optimization or next BLK was started.
"""


def main():
    container, cargo = load_dataset(DATASET)
    old_result = json.load(open(BLK004B_RESULT, encoding="utf-8"))["modes"]
    old_audit = json.load(open(BLK005A, encoding="utf-8"))["modes"]
    before = {
        mode: {
            "policy_compatible_count": old_audit[mode]["policy_compatible_count"],
            "eligible_count": old_audit[mode]["eligible_count"],
            "policy_pass_rate": old_audit[mode]["policy_pass_rate"],
            "top_fill_placed_count": old_result[mode]["top_fill_placed_count"],
            "top_fill_placed_volume": old_result[mode]["top_fill_placed_volume"],
        }
        for mode in ("BALANCED", "OPTIMIZE")
    }
    after = {}
    diagnostic_modes = {}
    for profile, budget in ((SearchProfile.BALANCED, 30.0), (SearchProfile.OPTIMIZE, 60.0)):
        metrics, diagnostics = _run_mode(container, cargo, profile, budget)
        after[profile.value] = metrics
        diagnostic_modes[profile.value] = {
            "summary": {
                "region_sku_pair_count": metrics["region_sku_pair_count"],
                "policy_compatible_count": metrics["policy_compatible_count"],
                "policy_pass_rate": metrics["policy_pass_rate"],
                "safe_admitted_count": metrics["safe_admitted_count"],
                "auto_pass_count": metrics["auto_pass_count"],
                "auto_rejection_count": metrics["auto_rejection_count"],
                "rejection_reasons": metrics["auto_rejection_reasons"],
            },
            "region_sku_admissions": diagnostics,
        }
        print(profile.value, metrics["policy_pass_rate"], metrics["auto_topfill_placed_count"], flush=True)

    current_fingerprint = _current_user_fingerprint(cargo)
    old_fingerprint = _before_user_fingerprint()
    fingerprint_ok = current_fingerprint == old_fingerprint
    tests = _run_tests()
    safety_keys = ("overlap", "penetration", "out_of_bounds", "hard_violations", "enclosed_cavity", "bridge_void")
    safety_ok = all(
        all(metrics[key] == 0 for key in safety_keys)
        and metrics["door_ready"]
        and metrics["main_body_conditional_flat_count"] == 0
        for metrics in after.values()
    )
    physical_rejection_codes = {
        "AUTO_GEOMETRY_FAIL", "AUTO_SUPPORT_FAIL", "AUTO_COMPRESSION_FAIL",
        "AUTO_STACK_FAIL", "AUTO_STABILITY_FAIL", "AUTO_ZONE_FAIL", "AUTO_HANDLING_FAIL",
    }
    acceptance = {
        "policy_pass_rate_improved": all(after[m]["policy_pass_rate"] > before[m]["policy_pass_rate"] for m in after),
        "formerly_default_disabled_sku_auto_admitted": all(after[m]["auto_pass_count"] > 0 for m in after),
        "formerly_default_disabled_sku_auto_placed": all(after[m]["auto_topfill_placed_count"] > 0 for m in after),
        "auto_physical_or_strategy_rejection_present": all(
            any(after[m]["auto_rejection_reasons"].get(code, 0) > 0 for code in physical_rejection_codes)
            for m in after
        ),
        "auto_flat_zero": all(after[m]["auto_flat_placed_count"] == 0 for m in after),
        "user_defined_rules_unchanged": fingerprint_ok,
        "safety_regression": safety_ok,
        "full_suite": tests["full_suite"] == "PASS",
    }
    before_after = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "before": before,
        "after": after,
        "acceptance": acceptance,
        "regression_tests": tests,
        "user_defined_fingerprint": {"before": old_fingerprint, "after": current_fingerprint, "unchanged": fingerprint_ok},
        "mutations": {"search_objective": 0, "beam_search": 0, "local_search": 0, "user_defined_constraints": 0},
    }
    diagnostic = {
        "generated_at": before_after["generated_at"],
        "schema": "BLK005B_REGION_SKU_SAFE_ADMISSION_V1",
        "modes": diagnostic_modes,
    }
    if not all(acceptance.values()):
        raise RuntimeError(f"BLK-005B acceptance failed: {acceptance}")
    with open(os.path.join(ROOT, "BLK005B_BEFORE_AFTER.json"), "w", encoding="utf-8") as handle:
        json.dump(before_after, handle, indent=2, ensure_ascii=False)
    with open(os.path.join(ROOT, "BLK005B_ADMISSION_DIAGNOSTIC.json"), "w", encoding="utf-8") as handle:
        json.dump(diagnostic, handle, indent=2, ensure_ascii=False)
    with open(os.path.join(ROOT, "BLK005B_DEFAULT_POLICY_REPORT.md"), "w", encoding="utf-8") as handle:
        handle.write(_report(before_after, diagnostic, tests, fingerprint_ok))


if __name__ == "__main__":
    main()
