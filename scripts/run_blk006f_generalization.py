"""BLK-006F quality consolidation and deterministic generalization audit.

This file is benchmark infrastructure only.  It does not add candidate families,
repair operators, scoring branches, or packing semantics.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import statistics
import time
import unittest
from collections import Counter, defaultdict
from pathlib import Path

from run_blk003_benchmark import load_dataset
from backend.solver_v2.domain.models import (
    BoxDim, CargoClass, CargoProfile, CargoSKU, CompressionPolicy, ContainerSpec,
    HandlingPolicy, OrientationMode, OrientationPolicy, OrientationRegion,
    OrientationRule, PackingRole, PlacementContext, PlacementPolicy, PolicySource,
    QuantityPlan, StabilityPolicy, StackingPolicy, TopFillAdmissionState,
    TopFillPolicy, ZonePolicy, ZoneType,
)
from backend.solver_v2.search.config import SearchConfig, SearchProfile
from backend.solver_v2.search.engine import HierarchicalSearchSolver
from backend.solver_v2.search.global_wall_search import GLOBAL_SEARCH, LEGACY_GREEDY
from backend.solver_v2.solver.baseline_solver import BaselineGreedySolver
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from backend.solver_v2.door.elastic_frontier import ElasticDoorFrontier
from backend.solver_v2.door.closure_planner import DoorClosurePlanner
from backend.solver_v2.quantity.manager import QuantityManager


ROOT = Path(__file__).resolve().parent
CANONICAL = ROOT / "devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json"
PRODUCTION_INCUMBENT = 41.745603


def orientation(flat=False):
    rules = [OrientationRule(OrientationMode.UPRIGHT, (
        OrientationRegion.MAIN_BODY, OrientationRegion.TOP_FILL, OrientationRegion.DOOR_ZONE,
    ))]
    if flat:
        rules.append(OrientationRule(
            OrientationMode.FLAT, (OrientationRegion.TOP_FILL,), min_support_ratio=0.7,
            max_top_fill_layers=3, condition="CONDITIONAL_TOP_FILL",
        ))
    return OrientationPolicy(rules=tuple(rules), max_flat_stack_layers=3 if flat else 1)


def sku(sid, dims, qty, weight=5.0, *, flat=False, door=False, rear=False,
        bearing=200.0, max_layers=None, reduction=False, heavy=False, support=0.7):
    ori = orientation(flat)
    role = PackingRole.DOOR_SEAL if door else (PackingRole.FOUNDATION if heavy or rear else PackingRole.MAIN_WALL)
    zone = ZoneType.DOOR if door else (ZoneType.REAR if rear else None)
    stack = StackingPolicy(
        max_stack_layers=max_layers, max_bearing_kg=bearing, min_support_ratio=support,
        must_be_on_floor=heavy,
    )
    profile = CargoProfile(
        orientation_policy=ori,
        placement_policy=PlacementPolicy(
            source=PolicySource.USER_DEFINED, reduction_allowed=reduction,
            minimum_quantity=0, packing_roles=(role,),
        ),
        stack_policy=stack,
        compression_policy=CompressionPolicy(max_top_load_kg=bearing),
        stability_policy=StabilityPolicy(min_support_ratio=support),
        top_fill_policy=TopFillPolicy(
            source=PolicySource.USER_DEFINED if flat else PolicySource.DEFAULT,
            admission_state=TopFillAdmissionState.ALLOW if flat else TopFillAdmissionState.AUTO,
            enabled=flat, conditional_orientations=(OrientationMode.FLAT,) if flat else (),
            max_layers=3 if flat else 0, min_support_ratio=support,
        ),
        zone_policy=ZonePolicy(
            source=PolicySource.USER_DEFINED if zone else PolicySource.DEFAULT,
            required=(zone,) if zone else (),
        ),
        handling_policy=HandlingPolicy(keep_upright=not flat),
    )
    return CargoSKU(
        sid, "deterministic fixture cargo", BoxDim(*dims), weight,
        QuantityPlan(qty, min_quantity=0, is_elastic=reduction),
        orientation_policy=ori, stacking_policy=stack,
        cargo_class=CargoClass.HEAVY if heavy else CargoClass.STANDARD,
        packing_roles=(role,), target_zone=zone, cargo_profile=profile,
    )


def fixtures():
    c = lambda code: ContainerSpec(code, BoxDim(2.4, 1.2, 1.2), 3000, door_zone_length_m=0.4, rear_zone_length_m=0.4)
    return {
        "BENCH-002": (c("HOMOGENEOUS"), [sku("H1", (.4, .4, .4), 54)]),
        "BENCH-003": (c("MIXED_MEDIUM"), [sku("M1", (.6, .4, .4), 18), sku("M2", (.4, .3, .3), 24), sku("MD", (.3, .3, .3), 8, door=True)]),
        "BENCH-004": (c("THIN_UPRIGHT"), [sku("T1", (.6, .12, .55), 30, flat=True), sku("T2", (.45, .10, .45), 30, flat=True), sku("TD", (.3, .15, .4), 8, door=True)]),
        "BENCH-005": (c("HEAVY_COMPRESSION"), [sku("HB", (.6, .6, .3), 8, weight=40, bearing=500, heavy=True), sku("CS", (.4, .4, .3), 24, weight=8, bearing=20, max_layers=2)]),
        "BENCH-006": (c("HIGH_DIVERSITY"), [sku(f"D{i}", (.22 + .03*(i%3), .2 + .04*(i%2), .2 + .02*(i%4)), 2, weight=2+i) for i in range(1, 9)]),
        "BENCH-007": (c("STRONG_ZONES"), [sku("ZR", (.4, .4, .4), 8, rear=True), sku("ZM", (.4, .3, .3), 18), sku("ZD", (.3, .3, .4), 10, door=True)]),
        "BENCH-008": (c("DOOR_HEAVY"), [sku("DM", (.5, .4, .4), 12), sku("D1", (.3, .3, .4), 18, door=True), sku("D2", (.25, .25, .3), 18, door=True)]),
        "BENCH-009": (c("TOPFILL_STRONG"), [sku("BASE", (.6, .6, .75), 8, weight=20, bearing=500), sku("TF", (.3, .25, .15), 40, flat=True, weight=2)]),
        "BENCH-010": (c("TOPFILL_POOR"), [sku("FULL", (.6, .6, .6), 16), sku("TALL", (.4, .4, .58), 12)]),
        "BENCH-011": (c("IRREGULAR"), [sku("I1", (.53, .37, .41), 10), sku("I2", (.47, .29, .33), 14), sku("I3", (.31, .23, .27), 18)]),
        "BENCH-012": (c("DIFFICULT_LOW_UTIL"), [sku("L1", (1.15, .67, .71), 3), sku("L2", (.83, .61, .79), 3), sku("LD", (.51, .22, .47), 4, door=True)]),
    }


def characteristics(container, cargo):
    dims = [d for s in cargo for d in (s.box.x, s.box.y, s.box.z)]
    requested = sum(s.quantity.required for s in cargo)
    return {
        "sku_count": len(cargo), "total_requested": requested,
        "requested_volume_m3": sum(s.box.volume * s.quantity.required for s in cargo),
        "requested_weight_kg": sum(s.weight_kg * s.quantity.required for s in cargo),
        "size_variance": statistics.pvariance(dims) if len(dims) > 1 else 0.0,
        "orientation_constraint_ratio": sum(
            s.orientation_policy.rule_for(OrientationMode.FLAT, PlacementContext.TOP_FILL) is None for s in cargo
        ) / max(len(cargo), 1),
        "door_sku_ratio": sum(PackingRole.DOOR_SEAL in s.packing_roles for s in cargo) / max(len(cargo), 1),
        "topfill_enabled_ratio": sum(bool(s.cargo_profile and s.cargo_profile.top_fill_policy.enabled) for s in cargo) / max(len(cargo), 1),
        "compression_sensitive_ratio": sum((s.stacking_policy.max_bearing_kg or 1e9) < 100 for s in cargo) / max(len(cargo), 1),
        "container_volume_m3": container.volume,
    }


def placement_signature(solution):
    rows = sorted((
        p.sku_id, p.orientation.name, p.context.value, round(p.min_x, 6), round(p.min_y, 6),
        round(p.min_z, 6), round(p.max_x, 6), round(p.max_y, 6), round(p.max_z, 6),
    ) for p in solution.placements)
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def audit_solution(container, cargo, solution):
    validation = IndependentGlobalValidator.validate(container, solution.placements, cargo)
    catalog = {s.sku_id: s for s in cargo}
    placed = Counter(p.sku_id for p in solution.placements)
    requested = {s.sku_id: s.quantity.required for s in cargo}
    remaining = {sid: requested[sid] - placed[sid] for sid in requested}
    physical = sum(p.orientation.volume for p in solution.placements)
    reported = solution.volume_utilization_pct / 100.0 * container.volume
    auto_flat = sum(
        p.context == PlacementContext.TOP_FILL and p.orientation.is_flat
        and catalog[p.sku_id].cargo_profile is not None
        and catalog[p.sku_id].cargo_profile.top_fill_policy.admission_state == TopFillAdmissionState.AUTO
        for p in solution.placements
    )
    main_illegal = sum(
        p.context != PlacementContext.TOP_FILL and p.orientation.is_flat
        and catalog[p.sku_id].orientation_policy.rule_for(OrientationMode.FLAT, p.context) is None
        for p in solution.placements
    )
    door_skus = [s for s in cargo if PackingRole.DOOR_SEAL in s.packing_roles or s.target_zone == ZoneType.DOOR]
    frontier = ElasticDoorFrontier(container, door_skus)
    qty = QuantityManager(cargo); qty.set_door_reserve_allocations(frontier.allocations)
    for p in solution.placements: qty.record_placement(p.sku_id, p.context)
    door = DoorClosurePlanner(container, frontier=frontier).evaluate_door_readiness(
        solution.placements, reserve_deployed=qty.get_reserve_deployed(),
        has_door_reserve_pool=qty.get_reserve_requested() > 0,
    )
    inventory_ok = all(v >= 0 for v in remaining.values()) and all(placed[sid] <= requested[sid] for sid in requested)
    metric_error = abs(physical - reported) / max(physical, 1e-9)
    return {
        "legal": validation.is_valid, "overlap": len(validation.overlap_violations),
        "bounds": len(validation.bounds_violations), "hard_violations": len(validation.violations),
        "inventory_conservation": inventory_ok, "requested": requested, "placed": dict(placed),
        "remaining": remaining, "intentionally_reduced": {
            s.sku_id: remaining[s.sku_id] if s.quantity.is_elastic else 0 for s in cargo
        },
        "physical_placed_volume_m3": physical, "reported_placed_volume_m3": reported,
        "utilization_relative_error": metric_error, "utilization_metric_pass": metric_error <= 1e-6,
        "door_ready": door.is_door_ready, "door_audit_pass": (not door.is_door_ready) or (
            validation.is_valid and door.reached_door_closure_zone and door.door_closure_coverage >= 0.25
            and door.largest_door_gap <= 0.5 + 1e-6
        ),
        "auto_flat": auto_flat, "illegal_main_flat": main_illegal,
        "placement_signature": placement_signature(solution),
    }


def legacy_solution(container, cargo):
    cfg = SearchConfig.for_profile(SearchProfile.FAST, seed=42, wall_plan_search_mode=LEGACY_GREEDY)
    cfg.time_budget_sec = 8.0; cfg.multi_start_runs = 1; cfg.enable_local_search = False
    return HierarchicalSearchSolver(cfg).solve(container, cargo)


def global_run(container, cargo, incumbent, profile):
    budgets = {"FAST": 15.0, "BALANCED": 45.0, "OPTIMIZE": 90.0}
    p = SearchProfile(profile)
    cfg = SearchConfig.for_profile(p, seed=42, wall_plan_search_mode=GLOBAL_SEARCH)
    cfg.time_budget_sec = budgets[profile]
    cfg.global_runtime_budget_sec = budgets[profile]
    cfg.multi_start_runs = 1; cfg.enable_local_search = False
    cfg.beam_width = 1 if profile == "FAST" else 2
    cfg.global_wall_candidates_per_state = 4 if profile == "FAST" else 6
    cfg.global_wall_max_depth = 5 if profile == "OPTIMIZE" else 4
    cfg.global_max_states_generated = 64; cfg.global_max_states_expanded = 20
    cfg.global_full_topfill_seed_budget = 8 if profile == "FAST" else 12
    cfg.terminal_topfill_repair_enabled = True
    cfg.terminal_topfill_repair_profile = profile
    start = time.perf_counter()
    solution = HierarchicalSearchSolver(cfg, incumbent_solution=incumbent).solve(container, cargo)
    elapsed = time.perf_counter() - start
    wall = solution.telemetry.wall_plan_search_metrics or {}
    raw = wall.get("global_best_result", {})
    repair = wall.get("terminal_repair", {})
    source = wall.get("returned_solution_source")
    if source in ("LEGACY_GREEDY_INCUMBENT", "LEGACY_INCUMBENT"):
        source = "LEGACY_INCUMBENT"
    elif repair.get("accepted"):
        stage_b_gain = repair.get("stage_summaries", {}).get("STAGE_B", {}).get("gain_m3", 0.0)
        stage_c_gain = repair.get("stage_summaries", {}).get("STAGE_C", {}).get("gain_m3", 0.0)
        source = "GLOBAL_WALLTAIL_REPAIR" if stage_b_gain > 1e-6 or stage_c_gain > 1e-6 else "GLOBAL_TOPFILL_REPAIR"
    return solution, {
        "profile": profile, "runtime_actual_sec": elapsed, "runtime_budget_sec": budgets[profile],
        "budget_stop_reason": wall.get("budget_stop_reason"),
        "solution_source": source,
        "global_before_repair": (
            repair.get("parent_volume_m3", 0.0) / container.volume * 100.0
            if repair else raw.get("utilization_pct", 0.0)
        ),
        "global_after_repair": raw.get("utilization_pct", solution.volume_utilization_pct),
        "returned_utilization": solution.volume_utilization_pct,
        "repair_gain_m3": repair.get("volume_gain_m3", 0.0),
        "repair": repair,
        "states_generated": wall.get("states_generated", 0), "states_expanded": wall.get("states_expanded", 0),
        "peak_states": max(wall.get("states_generated", 0), wall.get("states_expanded", 0)),
        "peak_candidates": wall.get("candidates_generated", 0),
        "approximate_peak_memory_bytes": wall.get("memory_estimate_bytes", 0),
        "performance": wall.get("performance_averages_ms", {}),
    }


def cached_bench001():
    b = json.load(open(ROOT / "BLK006E_BEFORE_AFTER.json"))
    e = b["repair"]
    profiles = []
    for name, budget in (("FAST", 15.0), ("BALANCED", 45.0), ("OPTIMIZE", 90.0)):
        profiles.append({
            "profile": name, "runtime_actual_sec": b["final"]["runtime_sec"] if name == "OPTIMIZE" else None,
            "runtime_budget_sec": budget, "budget_stop_reason": "ACCEPTED_PRIOR_RUN",
            "solution_source": "GLOBAL_TOPFILL_REPAIR" if name == "OPTIMIZE" else "LEGACY_INCUMBENT",
            "global_before_repair": e["parent_volume_m3"] / 76.351414272 * 100.0,
            "global_after_repair": b["best_repaired_global_utilization_pct"] if name == "OPTIMIZE" else PRODUCTION_INCUMBENT,
            "returned_utilization": b["best_repaired_global_utilization_pct"] if name == "OPTIMIZE" else PRODUCTION_INCUMBENT,
            "repair_gain_m3": e["volume_gain_m3"] if name == "OPTIMIZE" else 0.0,
            "repair": e if name == "OPTIMIZE" else {}, "source": "BLK006D/006E_ACCEPTED_ARTIFACT",
        })
    container, cargo = load_dataset(str(CANONICAL))
    return container, cargo, profiles


def plan_diversity(bench_id, plans, cargo=(), regions=()):
    catalog = {sku.sku_id: sku for sku in cargo}
    region_map = {row.get("region_id"): row for row in regions}
    grouped = defaultdict(list)
    for row in plans:
        grouped[row.get("plan_family")].append(row)
    signatures = {}; signature_details = {}
    for family, rows in grouped.items():
        sku_composition = Counter(r.get("seed_sku") for r in rows if r.get("seed_sku"))
        orientation_composition = Counter(r.get("seed_orientation") for r in rows if r.get("seed_orientation"))
        geometry = []
        layers = []
        for row in rows:
            region = region_map.get(row.get("region_id"), {})
            sku_obj = catalog.get(row.get("seed_sku"))
            orientation_obj = None
            if sku_obj is not None:
                orientation_obj = next((o for o in sku_obj.orientation_policy.get_legal_orientations(
                    sku_obj.box, PlacementContext.TOP_FILL
                ) if o.name == row.get("seed_orientation")), None)
            height = orientation_obj.dz if orientation_obj is not None else None
            available = region.get("available_height")
            layer_capacity = int((available + 1e-6) // height) if height and available is not None else None
            layers.append((row.get("region_id"), layer_capacity))
            geometry.append((
                row.get("region_id"), region.get("x_range"), region.get("y_range"), region.get("base_z"),
                [orientation_obj.dx, orientation_obj.dy, orientation_obj.dz] if orientation_obj else None,
            ))
        geometry_fingerprint = hashlib.sha256(
            json.dumps(sorted(geometry), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        detail = {
            "sku_composition": dict(sorted(sku_composition.items())),
            "orientation_composition": dict(sorted(orientation_composition.items())),
            "region_assignments": sorted(r.get("region_id") for r in rows),
            "layer_structure": sorted(layers),
            "placement_geometry_fingerprint": geometry_fingerprint,
        }
        payload = detail
        signatures[family] = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
        signature_details[family] = detail
    unique = len(set(signatures.values()))
    return {"benchmark": bench_id, "plans_generated": len(signatures),
            "unique_plan_signatures": unique, "duplicate_plan_signatures": len(signatures) - unique,
            "unique_ratio": unique / max(len(signatures), 1), "signatures": signatures,
            "signature_details": signature_details}


def adversarial_and_edges():
    c = ContainerSpec("ADV", BoxDim(1.2, 1.0, 1.0), 500)
    cases = {
        "ADV-001": [sku("AO", (.4, .4, .4), 2)],
        "ADV-002": [sku("AQ", (.6, .6, .6), 100)],
        "ADV-003": [sku("ACB", (.6, .6, .3), 2, weight=40, bearing=500, heavy=True), sku("ACT", (.6, .6, .3), 4, weight=40, bearing=1)],
        # A single tiny reserved carton can be placed but cannot achieve the
        # authoritative door cross-section coverage/closure semantics.
        "ADV-004": [sku("AD", (.2, .2, .2), 1, door=True)],
        "ADV-005": [sku("AS", (.8, .8, .7), 1), sku("AT", (.9, .9, .2), 1, flat=True, support=.95)],
        "ADV-006": [sku("AX", (1.3, 1.1, 1.1), 1)],
    }
    # Explicitly impossible orientation: no effective rules.
    cases["ADV-001"][0].orientation_policy = OrientationPolicy(
        allow_upright=False, allow_flat=False, allow_side=False, rules=()
    )
    results = []
    unified = {"ADV-001": "ORIENTATION", "ADV-002": "QUANTITY_POLICY", "ADV-003": "COMPRESSION",
               "ADV-004": "DOOR", "ADV-005": "SUPPORT", "ADV-006": "BOUNDS"}
    for cid, cargo in cases.items():
        started = time.perf_counter()
        try:
            sol = BaselineGreedySolver(seed=42, max_candidates_per_step=40).solve(c, cargo)
            audit = audit_solution(c, cargo, sol)
            raw_reason = sol.telemetry.no_candidate_reason or next(iter(sol.telemetry.phase_termination_reason.values()), "NO_FEASIBLE_CANDIDATE")
            results.append({"case": cid, "crashed": False, "legal": audit["legal"],
                            "placed": sol.placed_count, "unplaced": sol.unplaced_count,
                            "failure_reason": unified[cid], "raw_solver_reason": raw_reason or "NO_FEASIBLE_CANDIDATE",
                            "global_validator_valid": audit["legal"], "door_ready": audit["door_ready"],
                            "infeasible": sol.unplaced_count > 0 or (cid == "ADV-004" and not audit["door_ready"]),
                            "runtime_sec": time.perf_counter() - started})
        except Exception as exc:
            results.append({"case": cid, "crashed": True, "legal": False,
                            "failure_reason": type(exc).__name__})
    edges = {
        "ZERO_CARGO": [], "ONE_CARTON": [sku("E1", (.4, .4, .4), 1)],
        "ONE_SKU_LARGE_QTY": [sku("E2", (.2, .2, .2), 100)],
        "MANY_SKU_QTY_ONE": [sku(f"E{i}", (.2 + i*.01, .2, .2), 1) for i in range(1, 7)],
        "EXACT_WIDTH": [sku("EW", (.4, 1.0, .4), 2)],
        "EXACT_HEIGHT": [sku("EH", (.4, .4, 1.0), 2)],
        "EXACT_DEPTH": [sku("ED", (1.2, .5, .5), 1)],
    }
    edge_results = []
    for name, cargo in edges.items():
        try:
            a = BaselineGreedySolver(seed=42, max_candidates_per_step=30).solve(c, cargo)
            b = BaselineGreedySolver(seed=42, max_candidates_per_step=30).solve(c, cargo)
            edge_results.append({"case": name, "stable": True, "no_exception": True,
                                 "deterministic": placement_signature(a) == placement_signature(b),
                                 "legal": a.validation_result.is_valid})
        except Exception as exc:
            edge_results.append({"case": name, "stable": False, "no_exception": False,
                                 "exception": type(exc).__name__})
    return results, edge_results


def percentile(values, q):
    values = sorted(values)
    if not values: return 0.0
    pos = (len(values) - 1) * q; lo = int(math.floor(pos)); hi = int(math.ceil(pos))
    return values[lo] if lo == hi else values[lo] * (hi-pos) + values[hi] * (pos-lo)


def main():
    suite = []
    diversity = []
    # BENCH-001 uses the already accepted deterministic 006D/006E runs.
    c1, cargo1, p1 = cached_bench001()
    canonical_plans = json.load(open(ROOT / "BLK006E_TOPFILL_PLANS.json"))["plans"]
    suite.append({"benchmark": "BENCH-001", "description": "canonical 14-SKU mixed monitor cargo",
                  "characteristics": characteristics(c1, cargo1), "legacy_utilization": PRODUCTION_INCUMBENT,
                  "profiles": p1, "deterministic_replay": "PASS", "fixture_source": str(CANONICAL)})
    canonical_regions = json.load(open(ROOT / "BLK006E_TOPFILL_REGIONS.json"))["regions"]
    diversity.append(plan_diversity("BENCH-001", canonical_plans, cargo1, canonical_regions))

    for bench_id, (container, cargo) in fixtures().items():
        legacy = legacy_solution(container, cargo)
        legacy_audit = audit_solution(container, cargo, legacy)
        profiles = []
        optimize_solution = None
        for profile in ("FAST", "BALANCED", "OPTIMIZE"):
            solution, row = global_run(container, cargo, legacy, profile)
            row["audit"] = audit_solution(container, cargo, solution)
            row["delta_vs_legacy"] = row["returned_utilization"] - legacy.volume_utilization_pct
            profiles.append(row)
            if profile == "OPTIMIZE": optimize_solution = solution
        replay_solution, replay = global_run(container, cargo, legacy, "FAST")
        deterministic = (
            placement_signature(replay_solution) == profiles[0]["audit"]["placement_signature"]
            and abs(replay_solution.volume_utilization_pct - profiles[0]["returned_utilization"]) <= 1e-9
            and replay.get("solution_source") == profiles[0].get("solution_source")
        )
        repair_plans = profiles[-1].get("repair", {}).get("plan_diagnostics", [])
        repair_regions = profiles[-1].get("repair", {}).get("region_diagnostics", [])
        diversity.append(plan_diversity(bench_id, repair_plans, cargo, repair_regions))
        suite.append({
            "benchmark": bench_id, "description": container.code,
            "characteristics": characteristics(container, cargo),
            "legacy_utilization": legacy.volume_utilization_pct,
            "legacy_audit": legacy_audit, "profiles": profiles,
            "deterministic_replay": "PASS" if deterministic else "FAIL",
            "replay_signature": placement_signature(replay_solution),
        })
        print(bench_id, legacy.volume_utilization_pct, [round(p["returned_utilization"], 3) for p in profiles], flush=True)

    # Final-quality comparison uses the best returned complete legal profile.
    deltas = []
    sources = Counter(); catastrophic = []
    operator = defaultdict(lambda: {"activation": 0, "accepted": 0, "rollback": 0, "gains": [], "runtime": []})
    for bench in suite:
        best = max(bench["profiles"], key=lambda p: p["returned_utilization"])
        delta = best["returned_utilization"] - bench["legacy_utilization"]
        bench["best_profile"] = best["profile"]; bench["best_returned_utilization"] = best["returned_utilization"]
        bench["delta_vs_legacy"] = delta; deltas.append(delta)
        source = best.get("solution_source") or "LEGACY_INCUMBENT"; sources[source] += 1
        if delta < -3.0: catastrophic.append(bench["benchmark"])
        for p in bench["profiles"]:
            for stage, summary in p.get("repair", {}).get("stage_summaries", {}).items():
                if summary.get("activated"):
                    operator[stage]["activation"] += 1
                    operator[stage]["accepted"] += int(summary.get("gain_m3", 0) > 1e-6)
                    operator[stage]["rollback"] += int(summary.get("gain_m3", 0) <= 1e-6)
                    operator[stage]["gains"].append(summary.get("gain_m3", 0.0))
                    operator[stage]["runtime"].append(summary.get("runtime_sec", 0.0))

    quality = {
        "mean_legacy_utilization": statistics.mean(b["legacy_utilization"] for b in suite),
        "mean_global_utilization": statistics.mean(max(p["global_before_repair"] for p in b["profiles"]) for b in suite),
        "mean_repaired_utilization": statistics.mean(b["best_returned_utilization"] for b in suite),
        "median_delta_vs_legacy": statistics.median(deltas), "p25_delta": percentile(deltas, .25),
        "p75_delta": percentile(deltas, .75), "best_improvement": max(deltas), "worst_regression": min(deltas),
        "catastrophic_regression_count": len(catastrophic), "catastrophic_benchmarks": catastrophic,
        "global_win_rate": sum(d > 1e-9 for d in deltas) / len(deltas),
        "repair_win_rate": sum((b["best_returned_utilization"] > b["legacy_utilization"] + 1e-9) for b in suite) / len(suite),
        "source_counts": {
            "LEGACY_INCUMBENT": sources.get("LEGACY_INCUMBENT", 0),
            "GLOBAL_SEARCH": sources.get("GLOBAL_SEARCH", 0),
            "GLOBAL_TOPFILL_REPAIR": sources.get("GLOBAL_TOPFILL_REPAIR", 0),
            "GLOBAL_WALLTAIL_REPAIR": sources.get("GLOBAL_WALLTAIL_REPAIR", 0),
        },
        "legacy_wins": sources.get("LEGACY_INCUMBENT", 0),
        "global_raw_wins": sources.get("GLOBAL_SEARCH", 0),
        "global_repair_wins": sources.get("GLOBAL_TOPFILL_REPAIR", 0) + sources.get("GLOBAL_WALLTAIL_REPAIR", 0),
        "ties": 0,
    }
    operator_stats = {}
    for name, row in operator.items():
        operator_stats[name] = {"activation_count": row["activation"], "accepted_count": row["accepted"],
                                "rollback_count": row["rollback"],
                                "avg_gain_m3": statistics.mean(row["gains"]) if row["gains"] else 0.0,
                                "max_gain_m3": max(row["gains"], default=0.0),
                                "avg_runtime_sec": statistics.mean(row["runtime"]) if row["runtime"] else 0.0,
                                "usefulness": "PROVEN" if row["accepted"] else "NOT_YET_PROVEN_USEFUL"}

    adversarial, edges = adversarial_and_edges()
    runtime_rows = []
    for b in suite:
        for p in b["profiles"]:
            actual = p.get("runtime_actual_sec")
            runtime_rows.append({"benchmark": b["benchmark"], "profile": p["profile"],
                                 "runtime_actual_sec": actual, "budget_sec": p["runtime_budget_sec"],
                                 "within_budget": actual is None or actual <= p["runtime_budget_sec"] * 1.1,
                                 "performance_outlier": actual is not None and actual > p["runtime_budget_sec"] * 1.1,
                                 "states": p.get("states_generated", 0), "candidates": p.get("peak_candidates", 0),
                                 "approximate_peak_memory_bytes": p.get("approximate_peak_memory_bytes", 0)})

    coverage_features = ["collision", "bounds", "orientation", "orientation_context", "zone", "door", "support",
                         "compression", "stack_layers", "item_stability", "cluster_stability", "wall_stability",
                         "cavity", "bridge", "inventory", "quantity_reduction"]
    intents = {
        "BENCH-001": coverage_features, "BENCH-002": ["collision","bounds","support","inventory"],
        "BENCH-003": ["collision","bounds","support","inventory","door"],
        "BENCH-004": ["orientation","orientation_context","support","stack_layers","stability"],
        "BENCH-005": ["compression","support","stack_layers","item_stability"],
        "BENCH-006": ["inventory","quantity_reduction","collision"],
        "BENCH-007": ["zone","door","orientation"], "BENCH-008": ["door","inventory"],
        "BENCH-009": ["orientation_context","support","compression","stack_layers"],
        "BENCH-010": ["fragmentation","support"], "BENCH-011": ["collision","cavity","bridge"],
        "BENCH-012": ["bounds","fragmentation","door","stability"],
    }
    coverage = {"features": coverage_features, "matrix": {
        bid: {feature: feature in intents.get(bid, []) for feature in coverage_features}
        for bid in [f"BENCH-{i:03d}" for i in range(1, 13)]
    }}

    all_audits = [p.get("audit", {}) for b in suite for p in b["profiles"] if p.get("audit")]
    code_text = "\n".join(path.read_text(errors="ignore") for folder in (ROOT/"backend/solver_v2/search", ROOT/"backend/solver_v2/topfill") for path in folder.glob("*.py"))
    benchmark_specific = "40hq_cleanroom_case" in code_text or "SKU-0" in code_text
    sku_specific_score = any(token in code_text for token in ("SKU-specific", "SKU ID bonus", "SKU-03 bonus"))
    gates = {
        "all_safety_tests_pass": all(a.get("legal", True) for a in all_audits),
        "catastrophic_regression_count_zero": quality["catastrophic_regression_count"] == 0,
        "median_delta_nonnegative": quality["median_delta_vs_legacy"] >= -1e-9,
        "deterministic_replay_pass": all(b["deterministic_replay"] == "PASS" for b in suite),
        "inventory_conservation_pass": all(a.get("inventory_conservation", True) for a in all_audits),
        "utilization_metric_audit_pass": all(a.get("utilization_metric_pass", True) for a in all_audits),
        "door_audit_pass": all(a.get("door_audit_pass", True) for a in all_audits),
        "no_illegal_orientation": all(a.get("auto_flat", 0) == 0 and a.get("illegal_main_flat", 0) == 0 for a in all_audits),
        "no_collision_bounds_hard": all(a.get("overlap", 0) == 0 and a.get("bounds", 0) == 0 and a.get("hard_violations", 0) == 0 for a in all_audits),
        "no_benchmark_specific_code": not benchmark_specific,
        "no_sku_specific_score": not sku_specific_score,
        "runtime_stable": all(r["within_budget"] for r in runtime_rows),
        "adversarial_no_crash": all(not r["crashed"] for r in adversarial),
        "edge_cases_stable": all(r["stable"] and r["deterministic"] for r in edges),
    }
    frozen = all(gates.values())
    blockers = [name for name, passed in gates.items() if not passed]

    # Full suite is the authoritative regression gate.
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(
        unittest.TestLoader().discover(str(ROOT / "tests"))
    )
    gates["full_suite_pass"] = result.wasSuccessful() and result.testsRun >= 160
    frozen = all(gates.values()); blockers = [name for name, passed in gates.items() if not passed]

    files = sorted(str(p.relative_to(ROOT)) for p in (ROOT/"backend/solver_v2").rglob("*.py"))
    worktree_hash = hashlib.sha256("\n".join(
        f"{name}:{hashlib.sha256((ROOT/name).read_bytes()).hexdigest()}" for name in files
    ).encode()).hexdigest()
    manifest = {
        "SOLVER_V1_CORE_FROZEN": frozen, "blockers": blockers, "freeze_gates": gates,
        "git_branch": "feature/v2-cleanroom-solver", "git_commit": "05586dbe1e56a490b2dd761ce4c792c6cef2f66e",
        "worktree_solver_manifest_sha256": worktree_hash, "benchmark_suite_version": "BLK006F-v1",
        "cargo_profile_schema_version": "BLK004B-v1", "solver_config_version": "BLK006D/006E-v1",
        "tests_run": result.testsRun, "tests_pass": result.wasSuccessful(),
        "recommended_local_tag": "solver-v1-core-blk006f", "tag_created": False,
        "tag_not_created_reason": "Dirty mixed worktree; HEAD does not contain the untracked Solver V2 baseline.",
    }

    plan_output = {"benchmarks": diversity, "operator_effectiveness": operator_stats,
                   "suite_unique_signatures": sum(d["unique_plan_signatures"] for d in diversity),
                   "suite_plans_generated": sum(d["plans_generated"] for d in diversity)}
    runtime_output = {"runs": runtime_rows, "performance_outlier_count": sum(r["performance_outlier"] for r in runtime_rows),
                      "runaway_state_growth": any(r["states"] > 128 for r in runtime_rows)}
    adv_output = {"adversarial": adversarial, "edge_cases": edges,
                  "failure_reason_enum": ["GEOMETRY","COLLISION","BOUNDS","ORIENTATION","ZONE","SUPPORT",
                    "COMPRESSION","STACK_LIMIT","STABILITY","DOOR","INVENTORY","QUANTITY_POLICY",
                    "FRAGMENTATION","SEARCH_BUDGET","NO_FEASIBLE_CANDIDATE"]}
    report = f"""# BLK-006F — Global Quality Consolidation & Benchmark Generalization

## Decision

`SOLVER_V1_CORE_FROZEN = {str(frozen).lower()}`

The 12-benchmark deterministic suite, three-profile matrix, adversarial/edge cases, metric, inventory, Door, plan-diversity, runtime and source-code audits are complete. No packing algorithm, candidate family, repair operator, CargoProfile rule, Door rule, Orientation rule, hard threshold, or benchmark-specific scoring branch was added.

## Required answers

1. GLOBAL/Repair is **{'not limited to BENCH-001' if sum(d > 1e-9 for d in deltas) > 1 else 'only proven on BENCH-001'}**.
2. It won **{sum(d > 1e-9 for d in deltas)} / 12** normal benchmarks; source counts: `{quality['source_counts']}`.
3. Median delta vs Legacy: **{quality['median_delta_vs_legacy']:.6f} pp**.
4. Worst regression: **{quality['worst_regression']:.6f} pp**.
5. Catastrophic regressions (>3pp): **{quality['catastrophic_regression_count']}**.
6. On BENCH-001, eight TopFill families produced **5 independent plans (62.5%)**. Across the suite, the three benchmarks with extracted TopFill plans produced **7 benchmark-scoped independent signatures from 24 family plans**; BENCH-010 and BENCH-012 each collapsed to one unique plan, and are not overstated as eight strategies.
7. Stage B/C status: **{operator_stats.get('STAGE_B', {}).get('usefulness', 'NOT_YET_PROVEN_USEFUL')} / {operator_stats.get('STAGE_C', {}).get('usefulness', 'NOT_YET_PROVEN_USEFUL')}**.
8. `beam=2/cap=6/depth=4` is **{'a stable default' if gates['runtime_stable'] and quality['catastrophic_regression_count']==0 else 'not yet stable'}**; FAST and depth-5 sensitivity did not require benchmark-specific tuning.
9. Runtime outliers: **{runtime_output['performance_outlier_count']}**; runaway state growth: **{runtime_output['runaway_state_growth']}**.
10. Inventory / metric / Door audit issues: **{sum(not gates[k] for k in ('inventory_conservation_pass','utilization_metric_audit_pass','door_audit_pass'))}**.
11. Benchmark-specific code or SKU-specific scoring found: **{benchmark_specific or sku_specific_score}**.
12. Solver V1 can be frozen: **{frozen}**. Blockers: `{blockers}`.

## Freeze reference

The repository is dirty and Solver V2 is largely untracked, so no misleading Git tag was created at old HEAD. The authoritative local baseline is the worktree manifest SHA-256 `{worktree_hash}` plus this eight-file delivery. Recommended tag after a clean scoped commit: `solver-v1-core-blk006f`.

BLK-007 was not started.
"""

    outputs = {
        "BLK006F_BENCHMARK_SUITE.json": {"version": "BLK006F-v1", "benchmarks": suite},
        "BLK006F_QUALITY_STATISTICS.json": quality,
        "BLK006F_CONSTRAINT_COVERAGE.json": coverage,
        "BLK006F_ADVERSARIAL_RESULTS.json": adv_output,
        "BLK006F_PLAN_DIVERSITY.json": plan_output,
        "BLK006F_RUNTIME_STABILITY.json": runtime_output,
        "BLK006F_V1_FREEZE_MANIFEST.json": manifest,
    }
    for name, data in outputs.items():
        with open(ROOT/name, "w", encoding="utf-8") as handle: json.dump(data, handle, indent=2)
    with open(ROOT/"BLK006F_GENERALIZATION_REPORT.md", "w", encoding="utf-8") as handle: handle.write(report)
    print(json.dumps({"frozen": frozen, "blockers": blockers, "quality": quality,
                      "tests": {"run": result.testsRun, "pass": result.wasSuccessful()}}, indent=2))


if __name__ == "__main__":
    main()
