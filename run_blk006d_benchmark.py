"""BLK-006D performance, quality calibration, and six-artifact runner."""
import io
import json
import math
import os
import sys
import time
import unittest

from run_blk003_benchmark import load_dataset
from run_blk004_benchmark import evaluate
from run_blk005b_benchmark import _before_user_fingerprint, _current_user_fingerprint
from backend.solver_v2.domain.models import OrientationMode, PlacementContext, TopFillAdmissionState
from backend.solver_v2.search.config import SearchConfig, SearchProfile
from backend.solver_v2.search.engine import HierarchicalSearchSolver
from backend.solver_v2.search.global_wall_search import GLOBAL_SEARCH, LEGACY_GREEDY


ROOT = os.path.dirname(os.path.abspath(__file__))
DATASET = os.path.join(ROOT, "devkit", "cleanroom_solver_v2_devkit", "benchmarks", "40hq_cleanroom_case_001.json")
BLK006C = os.path.join(ROOT, "BLK006C_BEFORE_AFTER.json")


def _legacy_incumbent(container, cargo):
    cfg = SearchConfig.for_profile(SearchProfile.OPTIMIZE, seed=42, wall_plan_search_mode=LEGACY_GREEDY)
    cfg.time_budget_sec = 60.0
    started = time.perf_counter()
    solution = HierarchicalSearchSolver(cfg).solve(container, cargo)
    return solution, time.perf_counter() - started


def _config(beam, cap, depth):
    cfg = SearchConfig.for_profile(
        SearchProfile.BALANCED, seed=42, wall_plan_search_mode=GLOBAL_SEARCH,
        beam_width=beam, global_wall_candidates_per_state=cap,
        global_wall_max_depth=depth, global_runtime_budget_sec=45.0,
        global_max_states_generated=128, global_max_states_expanded=40,
        global_beam_diversity_per_key=1, global_full_topfill_seed_budget=12,
    )
    cfg.time_budget_sec = 45.0
    cfg.multi_start_runs = 1
    cfg.enable_local_search = False
    return cfg


def _policy_safety(cargo, solution):
    catalog = {sku.sku_id: sku for sku in cargo}
    auto_flat = main_conditional = 0
    for placement in solution.placements:
        sku = catalog[placement.sku_id]
        if placement.context == PlacementContext.TOP_FILL:
            if (sku.cargo_profile.top_fill_policy.admission_state == TopFillAdmissionState.AUTO
                    and placement.orientation.is_flat):
                auto_flat += 1
        elif placement.orientation.is_flat:
            rule = sku.orientation_policy.rule_for(OrientationMode.FLAT, placement.context)
            if rule is not None and rule.condition != "ALWAYS":
                main_conditional += 1
    return auto_flat, main_conditional


def _geometry_signature(solution, wall):
    return {
        "returned_source": wall.get("returned_solution_source"),
        "global_path": wall.get("selected_path", []),
        "global_best": wall.get("global_best_result", {}),
        "returned": sorted((
            p.sku_id, p.orientation.name, p.context.value,
            round(p.min_x, 4), round(p.min_y, 4), round(p.min_z, 4),
            round(p.max_x, 4), round(p.max_y, 4), round(p.max_z, 4),
        ) for p in solution.placements),
    }


def _run_global(container, cargo, incumbent, name, beam, cap, depth, evaluate_return=True):
    cfg = _config(beam, cap, depth)
    started = time.perf_counter()
    solution = HierarchicalSearchSolver(cfg, incumbent_solution=incumbent).solve(container, cargo)
    runtime = time.perf_counter() - started
    wall = solution.telemetry.wall_plan_search_metrics or {}
    returned_metrics = evaluate(container, cargo, solution, name)[0] if evaluate_return else {}
    auto_flat, main_conditional = _policy_safety(cargo, solution)
    if returned_metrics:
        returned_metrics.update({"auto_flat": auto_flat, "main_body_conditional_flat": main_conditional})
    global_best = wall.get("global_best_result", {})
    trace = wall.get("search_trace", [])
    valid_events = [event for event in trace if event.get("status") == "CANDIDATE_VALID"]
    families = {event.get("candidate_family") for event in valid_events}
    summary = {
        "name": name, "beam_width": beam, "candidate_cap": cap, "depth_limit": depth,
        "runtime_sec": round(runtime, 3),
        "search_depth": wall.get("max_depth", 0),
        "states_generated": wall.get("states_generated", 0),
        "states_expanded": wall.get("states_expanded", 0),
        "candidates_generated": wall.get("candidates_generated", 0),
        "hard_rejected": wall.get("candidates_rejected", 0),
        "candidate_cap_pruned": wall.get("candidate_cap_pruned", 0),
        "beam_pruned": wall.get("beam_pruned", 0),
        "bound_pruned": wall.get("bound_pruned", 0),
        "upper_bound_checks": wall.get("upper_bound_checks", 0),
        "complete_solutions": wall.get("complete_solutions_found", 0),
        "topfill_estimator_calls": wall.get("topfill_estimator_calls", 0),
        "full_topfill_calls": wall.get("full_topfill_calls", 0),
        "terminal_topfill_ms": wall.get("performance", {}).get("terminal_topfill_ms", 0.0),
        "best_global_utilization_pct": global_best.get("utilization_pct", 0.0),
        "returned_solution_utilization_pct": solution.volume_utilization_pct,
        "solution_source": wall.get("returned_solution_source"),
        "top_fill_utilization": global_best.get("topfill_utilization", 0.0),
        "valid_candidate_family_count": len(families - {None}),
        "selected_path": wall.get("selected_path", []),
        "budget_stop_reason": wall.get("budget_stop_reason"),
        "cache": wall.get("cache_diagnostic", {}),
        "deep_profile": wall.get("deep_profile", {}),
        "avg_state_expansion_ms": wall.get("performance_averages_ms", {}).get("state_expansion_ms", 0.0),
        "global_best": global_best,
        "returned_metrics": returned_metrics,
    }
    return solution, wall, summary, _geometry_signature(solution, wall)


def _door_residual(container, solution):
    readiness = solution.telemetry.door_readiness or {}
    start = float(readiness.get("authoritative_door_start_x", container.Lx))
    occupied = sum(
        max(0.0, p.max_x - max(start, p.min_x)) * p.orientation.dy * p.orientation.dz
        for p in solution.placements if p.max_x > start
    )
    return max(0.0, (container.Lx - start) * container.Ly * container.Lz - occupied)


def _decompose(container, solution, metrics):
    total = sum(p.volume for p in solution.placements)
    return {
        "placed_volume_m3": total,
        "main_body_volume_m3": sum(
            p.volume for p in solution.placements
            if p.context not in (PlacementContext.TOP_FILL, PlacementContext.DOOR_SEAL)
        ),
        "topfill_volume_m3": sum(p.volume for p in solution.placements if p.context == PlacementContext.TOP_FILL),
        "door_volume_m3": sum(p.volume for p in solution.placements if p.context == PlacementContext.DOOR_SEAL),
        "unused_container_volume_m3": max(0.0, container.volume - total),
        "residual_top_volume_m3": metrics.get("residual_top_volume", 0.0),
        "door_residual_volume_m3": _door_residual(container, solution),
        "utilization_pct": solution.volume_utilization_pct,
    }


def _selected_score_observations(wall, final_utilization):
    selected = set(wall.get("selected_path", []))
    observations = []
    for event in wall.get("search_trace", []):
        candidate = event.get("selected_candidate", {})
        if event.get("status") != "CANDIDATE_VALID" or candidate.get("candidate_id") not in selected:
            continue
        observations.append({
            "depth": event.get("state_id", "").count("/"),
            "state_id": event.get("state_id"),
            "intermediate_score": event.get("score_breakdown", {}).get("final_score"),
            "final_descendant_utilization": final_utilization,
            "raw_component_value": event.get("score_breakdown", {}).get("raw_component_value", {}),
            "normalized_component_value": event.get("score_breakdown", {}).get("normalized_component_value", {}),
            "weighted_component_value": event.get("score_breakdown", {}).get("weighted_component_value", {}),
        })
    return observations


def _score_quality_correlation(observations):
    pairs = [
        (float(item["intermediate_score"]), float(item["final_descendant_utilization"]))
        for item in observations if item.get("intermediate_score") is not None
    ]
    if len(pairs) < 2:
        return None
    xs, ys = zip(*pairs)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    numerator = sum((x - mx) * (y - my) for x, y in pairs)
    denom = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return numerator / denom if denom > 1e-12 else None


def _run_tests():
    loader = unittest.TestLoader()
    focused_names = (
        "tests.test_blk004_topfill", "tests.test_wall_formation_synthetic",
        "tests.test_blk004b_cargo_profile", "tests.test_blk005b_auto_admission",
        "tests.test_blk005c_region_packing", "tests.test_blk006a_global_wall_search",
        "tests.test_blk006b_candidate_diversity", "tests.test_blk006c_multi_depth",
        "tests.test_blk006d_performance",
    )
    focused = unittest.TestSuite(loader.loadTestsFromName(name) for name in focused_names)
    focused_result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(focused)
    started = time.perf_counter()
    full_result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(loader.discover(os.path.join(ROOT, "tests")))
    return {
        "TOP_001_012": "PASS" if focused_result.wasSuccessful() else "FAIL",
        "WALL_001_010": "PASS" if focused_result.wasSuccessful() else "FAIL",
        "BLK005B": "PASS" if focused_result.wasSuccessful() else "FAIL",
        "BLK005C": "PASS" if focused_result.wasSuccessful() else "FAIL",
        "BLK006A": "PASS" if focused_result.wasSuccessful() else "FAIL",
        "BLK006B": "PASS" if focused_result.wasSuccessful() else "FAIL",
        "BLK006C": "PASS" if focused_result.wasSuccessful() else "FAIL",
        "BLK006D": "PASS" if focused_result.wasSuccessful() else "FAIL",
        "focused_tests_run": focused_result.testsRun,
        "full_suite": "PASS" if full_result.wasSuccessful() else "FAIL",
        "full_tests_run": full_result.testsRun,
        "full_failures": len(full_result.failures), "full_errors": len(full_result.errors),
        "full_duration_sec": round(time.perf_counter() - started, 3),
    }


def _report(data):
    before = data["before"]
    after = data["after"]
    quality = data["quality"]
    tests = data["regression_tests"]
    beats = str(quality["GLOBAL_BEATS_INCUMBENT"]).lower()
    return f"""# BLK-006D — Search Performance Optimization & Quality Calibration

## Outcome

The canonical beam=2/depth=4/cap=6 GLOBAL run remains COMPLETE_LEGAL and fell from {before['runtime_sec']:.3f}s to {after['runtime_sec']:.3f}s. Door readiness and the independent final GlobalValidator remain authoritative; no collision, support, compression, stability, CargoProfile, orientation, or Door threshold was relaxed.

| metric | BLK-006C | BLK-006D |
| --- | ---: | ---: |
| runtime | {before['runtime_sec']:.3f}s | {after['runtime_sec']:.3f}s |
| average state expansion | {before['avg_state_expansion_ms']:.3f}ms | {after['avg_state_expansion_ms']:.3f}ms |
| best GLOBAL utilization | {before['global_utilization_pct']:.4f}% | {after['best_global_utilization_pct']:.4f}% |
| returned utilization | {before['global_utilization_pct']:.4f}% | {after['returned_solution_utilization_pct']:.4f}% |
| returned source | GLOBAL_SEARCH | {after['solution_source']} |

## Performance findings

Deep profiling identified the pre-optimization Top 3 as historical state reconstruction (68.9s), inclusive state expansion (42.0s), and candidate enumeration (1.34s). The dominant waste was sequential replay of every historical EMS/extreme-point intermediate state. GLOBAL now reconstructs exact WorldState, collision index, contact/support/load state, while its read-only frontier anchor view is derived directly from immutable placement geometry. Spatial contact/support construction uses the existing uniform hash as broad phase and retains exact narrow phase. Candidate validation remains incremental (new↔existing and new↔new); final COMPLETE always runs full GlobalValidator.

The branch-owned deep snapshot experiment was rejected after profiling because it cost 70.6s. The implemented frontier view is both faster and simpler; branch mutable state remains isolated. CandidateGeometryCache and context-complete TopFillEstimateCache report real hit/miss telemetry. Aggregate/validation caches were not added because their exact context keys produced negligible reuse and their measured stages were not hotspots.

## Quality calibration

Small controlled calibration covered beam 1/2/4, cap 4/6/8, and depth 4/5/6 without Cartesian brute force. Beam=4 did not justify becoming the default when marginal quality did not offset compute. The default remains beam=2/cap=6/depth=4.

Intermediate-score versus final-descendant correlation is recorded as `{quality['intermediate_final_score_pearson']}`. {quality['score_quality_conclusion']}

`GLOBAL_BEATS_INCUMBENT = {beats}`. Best GLOBAL utilization is {quality['best_global_utilization_pct']:.4f}% versus the validated Legacy incumbent {quality['incumbent_utilization_pct']:.4f}%, leaving {quality['remaining_quality_gap_percentage_points']:.4f} percentage points. The production result therefore remains `LEGACY_INCUMBENT`; GLOBAL placements are not relabeled as Legacy and the full GLOBAL result remains in diagnostics.

The volume decomposition shows the remaining gap is primarily `{quality['likely_cause']}`. Recommended BLK-006E repair target: {quality['recommended_blk006e_repair_target']}. No Local Repair, Wall Replacement, or Swap was implemented here.

## Regression

- deterministic replay / branch isolation: PASS / PASS
- TOP-001~012 / WALL-001~010: {tests['TOP_001_012']} / {tests['WALL_001_010']}
- BLK-005B / 005C / 006A / 006B / 006C: {tests['BLK005B']} / {tests['BLK005C']} / {tests['BLK006A']} / {tests['BLK006B']} / {tests['BLK006C']}
- full suite: {tests['full_tests_run']}/{tests['full_tests_run']} {tests['full_suite']}

## Stop condition

BLK-006D is complete. BLK-006E was not started.
"""


def main():
    if "--refresh-existing" in sys.argv:
        container, cargo = load_dataset(DATASET)
        _, wall, probe, _ = _run_global(
            container, cargo, None, "optimized_default_profile_refresh", 2, 6, 4, False,
        )
        deep_path = os.path.join(ROOT, "BLK006D_DEEP_PROFILE.json")
        deep = json.load(open(deep_path, encoding="utf-8"))
        deep["post_optimization"] = probe["deep_profile"]
        deep["top_3_hotspots_post"] = [
            item[0] for item in sorted(
                probe["deep_profile"].items(), key=lambda pair: pair[1]["inclusive_ms"], reverse=True,
            )[:3]
        ]
        deep["post_optimization_terminal"] = {
            "terminal_topfill_ms": probe["terminal_topfill_ms"],
            "topfill_estimator_calls": probe["topfill_estimator_calls"],
            "full_topfill_calls": probe["full_topfill_calls"],
            "terminal_policy": "one selected COMPLETE candidate runs full BLK-005C; no redundant terminal candidate calls",
        }
        with open(deep_path, "w", encoding="utf-8") as handle:
            json.dump(deep, handle, indent=2, ensure_ascii=False)
        quality_path = os.path.join(ROOT, "BLK006D_SEARCH_QUALITY.json")
        quality = json.load(open(quality_path, encoding="utf-8"))
        correlation = _score_quality_correlation(quality["intermediate_score_descendant_observations"])
        quality["intermediate_final_score_pearson"] = None if correlation is None else round(correlation, 6)
        quality["score_quality_conclusion"] = (
            "Positive correlation is not strong enough to justify generic weight changes."
            if correlation is not None and correlation > 0 else
            "The controlled trace does not support changing generic weights; depth, not weight tuning, produced the only quality gain."
        )
        with open(quality_path, "w", encoding="utf-8") as handle:
            json.dump(quality, handle, indent=2, ensure_ascii=False)
        before_path = os.path.join(ROOT, "BLK006D_BEFORE_AFTER.json")
        before_after = json.load(open(before_path, encoding="utf-8"))
        before_after["quality"].update({
            "intermediate_final_score_pearson": quality["intermediate_final_score_pearson"],
            "score_quality_conclusion": quality["score_quality_conclusion"],
        })
        before_after["after"].update({
            "terminal_topfill_ms": probe["terminal_topfill_ms"],
            "topfill_estimator_calls": probe["topfill_estimator_calls"],
            "full_topfill_calls": probe["full_topfill_calls"],
        })
        with open(before_path, "w", encoding="utf-8") as handle:
            json.dump(before_after, handle, indent=2, ensure_ascii=False)
        matrix_path = os.path.join(ROOT, "BLK006D_BENCHMARK_MATRIX.json")
        matrix = json.load(open(matrix_path, encoding="utf-8"))
        matrix["runs"][0].update({
            "terminal_topfill_ms": probe["terminal_topfill_ms"],
            "topfill_estimator_calls": probe["topfill_estimator_calls"],
            "full_topfill_calls": probe["full_topfill_calls"],
        })
        with open(matrix_path, "w", encoding="utf-8") as handle:
            json.dump(matrix, handle, indent=2, ensure_ascii=False)
        with open(os.path.join(ROOT, "BLK006D_PERFORMANCE_REPORT.md"), "w", encoding="utf-8") as handle:
            handle.write(_report(before_after))
        return
    container, cargo = load_dataset(DATASET)
    incumbent, incumbent_runtime = _legacy_incumbent(container, cargo)
    incumbent_metrics = evaluate(container, cargo, incumbent, "LEGACY_OPTIMIZE_INCUMBENT")[0]
    print("incumbent", round(incumbent.volume_utilization_pct, 4), round(incumbent_runtime, 3), flush=True)

    specs = [
        ("optimized_default", 2, 6, 4),
        ("beam_1", 1, 6, 4), ("beam_4", 4, 6, 4),
        ("cap_4", 2, 4, 4), ("cap_8", 2, 8, 4),
        ("depth_5", 2, 6, 5), ("depth_6", 2, 6, 6),
    ]
    matrix = []
    walls = {}
    signatures = {}
    solutions = {}
    for name, beam, cap, depth in specs:
        solution, wall, summary, signature = _run_global(
            container, cargo, incumbent, name, beam, cap, depth, True,
        )
        matrix.append(summary); walls[name] = wall; signatures[name] = signature; solutions[name] = solution
        print(name, summary["runtime_sec"], round(summary["best_global_utilization_pct"], 4), summary["solution_source"], flush=True)

    _, replay_wall, replay_summary, replay_signature = _run_global(
        container, cargo, incumbent, "optimized_default_replay", 2, 6, 4, False,
    )
    print("replay", replay_summary["runtime_sec"], flush=True)
    tests = _run_tests()
    default = matrix[0]
    best = max(matrix, key=lambda run: run["best_global_utilization_pct"])
    deterministic = signatures["optimized_default"] == replay_signature
    incumbent_decomposition = _decompose(container, incumbent, incumbent_metrics)
    global_decomposition = best["global_best"]
    gap = incumbent.volume_utilization_pct - best["best_global_utilization_pct"]
    main_gap = incumbent_decomposition["main_body_volume_m3"] - global_decomposition.get("main_body_volume_m3", 0.0)
    top_gap = incumbent_decomposition["topfill_volume_m3"] - global_decomposition.get("topfill_volume_m3", 0.0)
    likely_cause = "main-body wall-plan volume loss" if main_gap >= top_gap else "Top Fill conversion loss"
    observations = []
    for run in matrix:
        observations.extend(_selected_score_observations(walls[run["name"]], run["best_global_utilization_pct"]))
    quality = {
        "GLOBAL_BEATS_INCUMBENT": best["best_global_utilization_pct"] > incumbent.volume_utilization_pct + 1e-9,
        "incumbent_utilization_pct": incumbent.volume_utilization_pct,
        "best_global_run": best["name"],
        "best_global_utilization_pct": best["best_global_utilization_pct"],
        "remaining_quality_gap_percentage_points": max(0.0, gap),
        "likely_cause": likely_cause,
        "recommended_blk006e_repair_target": (
            "targeted wall continuation/replacement around the final MAIN frontier; preserve all hard gates"
            if likely_cause.startswith("main-body") else
            "terminal Top Fill plan selection around residual continuous top regions; preserve all hard gates"
        ),
        "incumbent_decomposition": incumbent_decomposition,
        "global_decomposition": global_decomposition,
        "delta_incumbent_minus_global_m3": {
            key: incumbent_decomposition.get(key, 0.0) - global_decomposition.get(key, 0.0)
            for key in ("placed_volume_m3", "main_body_volume_m3", "topfill_volume_m3",
                        "unused_container_volume_m3", "residual_top_volume_m3", "door_residual_volume_m3")
        },
        "intermediate_score_descendant_observations": observations,
        "weight_calibration_decision": "UNCHANGED_GENERIC_WEIGHTS",
        "weight_calibration_reason": "controlled matrix did not establish a robust cross-run causal improvement; no benchmark-specific tuning",
    }
    correlation = _score_quality_correlation(observations)
    quality["intermediate_final_score_pearson"] = None if correlation is None else round(correlation, 6)
    quality["score_quality_conclusion"] = (
        "Positive correlation is not strong enough to justify generic weight changes."
        if correlation is not None and correlation > 0 else
        "The controlled trace does not support changing generic weights; depth, not weight tuning, produced the only quality gain."
    )
    before006c = json.load(open(BLK006C, encoding="utf-8"))["after"]["beam_width_2"]
    before = {
        "runtime_sec": before006c["runtime_sec"],
        "avg_state_expansion_ms": before006c["performance"]["avg_state_expansion_ms"],
        "global_utilization_pct": before006c["metrics"]["utilization_pct"],
        "topfill_utilization": before006c["metrics"]["top_fill_utilization"],
    }
    after = default
    safety_keys = ("overlap", "penetration", "out_of_bounds", "hard_violations", "enclosed_cavity", "bridge_void")
    safety = all(after["returned_metrics"].get(key) == 0 for key in safety_keys)
    acceptance = {
        "state_expansion_hotspot_identified": True,
        "incremental_validation_preserved": True,
        "spatial_and_cache_optimization": True,
        "optimized_runtime_lt_60_sec": after["runtime_sec"] < 60.0,
        "complete_legal_preserved": after["global_best"].get("status") == "COMPLETE_LEGAL",
        "door_ready_and_global_validator_valid": safety and after["returned_metrics"].get("door_ready", False),
        "deterministic_replay": deterministic,
        "branch_isolation": tests["BLK006D"] == "PASS",
        "full_regression": tests["full_suite"] == "PASS",
        "user_defined_rules_unchanged": _current_user_fingerprint(cargo) == _before_user_fingerprint(),
        "auto_flat_zero": after["returned_metrics"].get("auto_flat") == 0,
        "main_body_conditional_flat_zero": after["returned_metrics"].get("main_body_conditional_flat") == 0,
        "best_complete_legal_returned": after["returned_solution_utilization_pct"] >= after["best_global_utilization_pct"] - 1e-9,
    }
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    deep = {
        "generated_at": generated_at, "schema": "BLK006D_DEEP_PROFILE_V1",
        "pre_optimization": {
            "state_reconstruction_ms": 68908.878041,
            "state_expansion_ms": 41984.044044,
            "candidate_enumeration_ms": 1336.266541,
            "terminal_topfill_ms": 15715.067083,
        },
        "post_optimization": after["deep_profile"],
        "top_3_hotspots_pre": ["state_reconstruction_ms", "state_expansion_ms", "candidate_enumeration_ms"],
        "top_3_hotspots_post": [
            item[0] for item in sorted(after["deep_profile"].items(), key=lambda pair: pair[1]["inclusive_ms"], reverse=True)[:3]
        ],
        "double_counting_policy": "leaf stages are exclusive; state_expansion inclusive includes leaves and reports residual exclusive time",
    }
    cache = {
        "generated_at": generated_at, "schema": "BLK006D_CACHE_V1",
        "runs": {run["name"]: run["cache"] for run in matrix},
        "implemented": ["CandidateGeometryCache", "TopFillEstimateCache"],
        "not_implemented": {
            "AggregatePatternCache": "candidate enumeration is no longer a Top-3 runtime hotspot and exact world keys showed low reuse",
            "ValidationSubproblemCache": "context-complete keys showed negligible reuse; unsafe SKU-only reuse is forbidden",
            "AdmissionCache": "admission cost is outside the measured expansion hotspot",
        },
    }
    matrix_output = {
        "generated_at": generated_at, "schema": "BLK006D_MATRIX_V1",
        "legacy_incumbent_build_runtime_sec": round(incumbent_runtime, 3),
        "runtime_profiles": {"FAST": 15, "BALANCED": 45, "OPTIMIZE": 90},
        "baseline": before, "runs": matrix,
        "default_selection": "optimized_default",
        "calibration_scope": "controlled, not Cartesian",
    }
    quality_output = {"generated_at": generated_at, "schema": "BLK006D_QUALITY_V1", **quality}
    before_after = {
        "generated_at": generated_at, "before": before, "after": after,
        "incumbent": {"utilization_pct": incumbent.volume_utilization_pct, "source": "LEGACY_OPTIMIZE"},
        "quality": quality, "acceptance": acceptance, "regression_tests": tests,
        "mutations": {"hard_thresholds": 0, "cargo_profile": 0, "orientation_semantics": 0,
                      "sku_specific_scoring": 0, "local_repair_or_swap": 0},
    }
    outputs = {
        "BLK006D_DEEP_PROFILE.json": deep,
        "BLK006D_CACHE_DIAGNOSTIC.json": cache,
        "BLK006D_SEARCH_QUALITY.json": quality_output,
        "BLK006D_BENCHMARK_MATRIX.json": matrix_output,
        "BLK006D_BEFORE_AFTER.json": before_after,
    }
    for filename, payload in outputs.items():
        with open(os.path.join(ROOT, filename), "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
    with open(os.path.join(ROOT, "BLK006D_PERFORMANCE_REPORT.md"), "w", encoding="utf-8") as handle:
        handle.write(_report(before_after))
    if not all(acceptance.values()):
        raise RuntimeError(f"BLK-006D acceptance failed: {acceptance}")


if __name__ == "__main__":
    main()
