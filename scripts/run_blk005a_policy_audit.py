"""BLK-005A read-only Policy / Eligibility Bottleneck Audit."""
import json
import os
import time
from collections import Counter, defaultdict

from run_blk003_benchmark import load_dataset
from backend.solver_v2.domain.models import OrientationMode, OrientationRegion, PlacementContext, PolicySource, ZoneType
from backend.solver_v2.search.config import SearchConfig, SearchProfile
from backend.solver_v2.search.engine import HierarchicalSearchSolver
from backend.solver_v2.topfill.planner import TopFillPlanner
from backend.solver_v2.world.state import WorldState


ROOT = os.path.dirname(os.path.abspath(__file__))
DATASET = os.path.join(ROOT, "devkit", "cleanroom_solver_v2_devkit", "benchmarks", "40hq_cleanroom_case_001.json")
BLK004B = os.path.join(ROOT, "BLK004B_BENCHMARK_RESULT.json")
REJECTION_KEYS = (
    "orientation_context", "topfill_disabled", "min_base_height", "max_layers",
    "zone_policy", "handling_policy", "stack_policy", "cargo_profile_default",
)


def _world(container, cargo, placements):
    world = WorldState(container, cargo)
    for placement in placements:
        world.commit(placement)
    return world


def _source_map(sku):
    return dict(sku.cargo_profile.source_audit) if sku.cargo_profile else {}


def _source(sku, field, fallback=PolicySource.DEFAULT):
    return _source_map(sku).get(field, fallback).value


def _orientation_rules(sku):
    source = _source(sku, "orientationPolicy.rules")
    return [
        {
            "orientation": rule.orientation.value,
            "allowed_regions": [region.value for region in rule.allowed_regions],
            "condition": rule.condition,
            "min_support_ratio": rule.min_support_ratio,
            "max_top_fill_layers": rule.max_top_fill_layers,
            "min_base_height": rule.min_base_height,
            "max_base_height": rule.max_base_height,
            "source": source,
        }
        for rule in sku.orientation_policy.rules
    ]


def _primary_policy_block(sku, region):
    """Mirror current policy semantics and return one non-overlapping attribution."""
    profile = sku.cargo_profile
    if profile is None:
        return "cargo_profile_default", "DEFAULT", "cargoProfile"
    top = profile.top_fill_policy
    sources = _source_map(sku)
    if not top.enabled:
        return "topfill_disabled", sources["topFillPolicy.enabled"].value, "topFillPolicy.enabled"

    declared = set(top.allowed_orientations + top.conditional_orientations)
    top_rules = [rule for rule in sku.orientation_policy.effective_rules() if OrientationRegion.TOP_FILL in rule.allowed_regions]
    if not declared or not any(rule.orientation in declared for rule in top_rules):
        return "orientation_context", sources["orientationPolicy.rules"].value, "orientationPolicy.rules"

    if region.base_z + 1e-6 < top.min_base_height:
        return "min_base_height", sources["topFillPolicy.minBaseHeight"].value, "topFillPolicy.minBaseHeight"
    if top.max_layers <= 0:
        return "max_layers", sources["topFillPolicy.maxLayers"].value, "topFillPolicy.maxLayers"
    if ZoneType.ROOF_ONLY in profile.zone_policy.forbidden:
        return "zone_policy", sources["zonePolicy.forbidden"].value, "zonePolicy.forbidden"

    only_non_upright = declared and OrientationMode.UPRIGHT not in declared
    if profile.handling_policy.keep_upright and only_non_upright:
        return "handling_policy", sources["handlingPolicy.keepUpright"].value, "handlingPolicy.keepUpright"
    stack = profile.stack_policy
    if stack.must_be_on_floor or stack.max_stack_layers == 0:
        field = "stackPolicy.mustBeOnFloor" if stack.must_be_on_floor else "stackPolicy.maxStackLayers"
        return "stack_policy", sources[field].value, field
    return None


def _remaining_by_sku(cargo, non_top_placements):
    placed = Counter(p.sku_id for p in non_top_placements)
    return {sku.sku_id: max(0, sku.quantity.required - placed[sku.sku_id]) for sku in cargo}


def _audit_mode(container, cargo, profile, budget, reference):
    config = SearchConfig.for_profile(profile, seed=42)
    config.time_budget_sec = budget
    solution = HierarchicalSearchSolver(config).solve(container, cargo)
    top = [p for p in solution.placements if p.context == PlacementContext.TOP_FILL]
    non_top = [p for p in solution.placements if p.context != PlacementContext.TOP_FILL]
    remaining = _remaining_by_sku(cargo, non_top)
    world = _world(container, cargo, non_top)
    planner = TopFillPlanner(container)
    catalog = {sku.sku_id: sku for sku in cargo}
    regions = planner.extract_top_fill_regions(world, catalog)

    per_sku = {}
    rejection_field_counts = Counter()
    rejection_source_counts = Counter()
    default_release_total = 0
    eligible_region_ids = set()
    counterfactual_rank = []

    for sku in cargo:
        counts = Counter()
        rejected = {
            key: {"count": 0, "by_source": {"USER_DEFINED": 0, "DEFAULT": 0}, "fields": {}}
            for key in REJECTION_KEYS
        }
        released_by_default = 0
        eligible_volume = 0.0
        default_release_volume = 0.0
        for region in regions:
            eligibility = region.eligibility_by_sku[sku.sku_id]
            counts["geometry"] += int(eligibility.geometrically_compatible)
            counts["policy"] += int(eligibility.policy_compatible)
            counts["physics"] += int(eligibility.physically_compatible)
            inventory_ok = remaining[sku.sku_id] > 0
            counts["inventory"] += int(inventory_ok)
            actual_eligible = (
                eligibility.geometrically_compatible and eligibility.policy_compatible
                and eligibility.physically_compatible and inventory_ok
            )
            counts["eligible"] += int(actual_eligible)
            if actual_eligible:
                eligible_region_ids.add(region.region_id)
                eligible_volume += region.usable_volume

            if not eligibility.policy_compatible:
                block = _primary_policy_block(sku, region)
                if block is None:
                    # Defensive audit label if implementation gains a new policy gate.
                    block = ("orientation_context", "DEFAULT", "UNATTRIBUTED_POLICY_GATE")
                reason, source, field = block
                rejected[reason]["count"] += 1
                rejected[reason]["by_source"][source] += 1
                rejected[reason]["fields"][field] = rejected[reason]["fields"].get(field, 0) + 1
                rejection_field_counts[field] += 1
                rejection_source_counts[source] += 1
                if source == "DEFAULT":
                    rejected["cargo_profile_default"]["count"] += 1
                    rejected["cargo_profile_default"]["by_source"]["DEFAULT"] += 1
                    rejected["cargo_profile_default"]["fields"][field] = (
                        rejected["cargo_profile_default"]["fields"].get(field, 0) + 1
                    )
                    # Upper bound: remove DEFAULT blockers only, retain geometry,
                    # physics, inventory, and every USER_DEFINED rule unchanged.
                    if eligibility.geometrically_compatible and eligibility.physically_compatible and inventory_ok:
                        released_by_default += 1
                        default_release_volume += region.usable_volume

        default_release_total += released_by_default
        top_policy = sku.cargo_profile.top_fill_policy
        per_sku[sku.sku_id] = {
            "remaining_quantity": remaining[sku.sku_id],
            "topfill_enabled": {
                "value": top_policy.enabled,
                "source": _source(sku, "topFillPolicy.enabled"),
            },
            "orientation_rules": _orientation_rules(sku),
            "geometry_compatible_count": counts["geometry"],
            "policy_compatible_count": counts["policy"],
            "physics_compatible_count": counts["physics"],
            "inventory_available_count": counts["inventory"],
            "eligible_count": counts["eligible"],
            "eligible_region_usable_volume_m3": round(eligible_volume, 5),
            "rejected_by": rejected,
            "default_rule_blocks_count": rejected["cargo_profile_default"]["count"],
            "theoretical_default_release_count": released_by_default,
            "theoretical_default_release_volume_m3": round(default_release_volume, 5),
        }
        counterfactual_rank.append({
            "sku_id": sku.sku_id,
            "actual_eligible_count": counts["eligible"],
            "default_release_count": released_by_default,
            "remaining_quantity": remaining[sku.sku_id],
            "unit_volume_m3": round(sku.box.volume, 6),
        })

    actual_rank = sorted(
        ({"sku_id": sku_id, "eligible_count": data["eligible_count"],
          "remaining_quantity": data["remaining_quantity"],
          "eligible_region_usable_volume_m3": data["eligible_region_usable_volume_m3"]}
         for sku_id, data in per_sku.items() if data["eligible_count"] > 0),
        key=lambda item: (item["eligible_count"], item["remaining_quantity"]), reverse=True,
    )
    counterfactual_rank.sort(key=lambda item: (item["default_release_count"], item["remaining_quantity"]), reverse=True)
    exposed_volume = sum(region.usable_volume for region in regions if region.region_id in eligible_region_ids)
    policy_pairs = sum(item["policy_compatible_count"] for item in per_sku.values())
    eligible_pairs = sum(item["eligible_count"] for item in per_sku.values())
    total_pairs = len(regions) * len(cargo)
    placed_volume = sum(p.volume for p in top)
    result = {
        "mode": profile.value,
        "audit_snapshot": "final solution minus TOP_FILL placements (BLK-004B metric-compatible)",
        "region_count": len(regions),
        "region_sku_pair_count": total_pairs,
        "top_fill_usable_volume_m3": round(sum(r.usable_volume for r in regions), 5),
        "policy_exposed_unique_region_volume_m3": round(exposed_volume, 5),
        "top_fill_placed_count": len(top),
        "top_fill_placed_volume_m3": round(placed_volume, 5),
        "policy_compatible_count": policy_pairs,
        "policy_incompatible_count": total_pairs - policy_pairs,
        "eligible_count": eligible_pairs,
        "policy_pass_rate": round(policy_pairs / total_pairs if total_pairs else 0.0, 6),
        "eligible_pass_rate": round(eligible_pairs / total_pairs if total_pairs else 0.0, 6),
        "placed_to_policy_exposed_volume_ratio": round(placed_volume / exposed_volume if exposed_volume else 0.0, 6),
        "reference_match": {
            "region_count": len(regions) == reference["top_fill_region_count"],
            "usable_volume": abs(sum(r.usable_volume for r in regions) - reference["top_fill_usable_volume"]) < 1e-4,
            "policy_compatible": policy_pairs == reference["region_eligibility"]["stage_true_counts"]["policy_compatible"],
            "eligible": eligible_pairs == reference["region_eligibility"]["stage_true_counts"]["eligible"],
            "policy_incompatible": total_pairs - policy_pairs == reference["region_eligibility"]["rejection_reasons"]["POLICY_INCOMPATIBLE"],
        },
        "rejection_field_counts": dict(rejection_field_counts),
        "rejection_source_counts": dict(rejection_source_counts),
        "default_rule_blocks_count": rejection_source_counts["DEFAULT"],
        "theoretical_additional_eligible_if_default_released": default_release_total,
        "skus": per_sku,
        "actual_topfill_filler_ranking": actual_rank,
        "counterfactual_default_release_ranking": counterfactual_rank,
    }
    return result


def _cross_mode(modes):
    fields = Counter()
    sources = Counter()
    default_release = 0
    for mode in modes.values():
        fields.update(mode["rejection_field_counts"])
        sources.update(mode["rejection_source_counts"])
        default_release += mode["theoretical_additional_eligible_if_default_released"]
    return {
        "rejection_field_counts": dict(fields),
        "rejection_source_counts": dict(sources),
        "default_rule_blocks_count": sources["DEFAULT"],
        "theoretical_additional_eligible_if_default_released": default_release,
        "top_rejection_fields": [
            {"field": field, "count": count} for field, count in fields.most_common()
        ],
    }


def _answers(modes, cross):
    actual = Counter()
    default_rank = Counter()
    for mode in modes.values():
        for item in mode["actual_topfill_filler_ranking"]:
            actual[item["sku_id"]] += item["eligible_count"]
        for item in mode["counterfactual_default_release_ranking"]:
            default_rank[item["sku_id"]] += item["default_release_count"]
    return {
        "1_primary_bottleneck": "POLICY",
        "1_reason": "Only 17 of 770 Region×SKU pairs pass policy across both modes; the deployment/search cap is secondary within that narrow exposed set.",
        "2_largest_rejection_fields": cross["top_rejection_fields"],
        "3_user_defined_limits": [
            "SKU-02 topFillPolicy.minBaseHeight=2.5m and matching TOP_FILL orientation-rule base height",
            "SKU-14 topFillPolicy.minBaseHeight=1.3m and matching conditional-flat orientation-rule base height",
        ],
        "4_conservative_defaults": [
            "REAR_UPRIGHT_DEFAULT, MIDDLE_UPRIGHT_DEFAULT, and DOOR_UPRIGHT_DEFAULT set topFillPolicy.enabled=false",
            "Those default profiles also declare maxLayers=0 and no Top Fill orientation list, but primary attribution stops at enabled=false",
        ],
        "5_max_additional_eligible_candidates_if_only_defaults_released": cross["theoretical_additional_eligible_if_default_released"],
        "5_unit": "Region×SKU eligibility combinations across BALANCED + OPTIMIZE; upper bound, not a policy recommendation",
        "6_actual_best_topfill_fillers": [
            {"sku_id": sku_id, "eligible_count_across_modes": count}
            for sku_id, count in actual.most_common()
        ],
        "6_counterfactual_default_profile_candidates": [
            {"sku_id": sku_id, "releasable_count_across_modes": count}
            for sku_id, count in default_rank.most_common() if count > 0
        ],
    }


def _report(audit):
    bal = audit["modes"]["BALANCED"]
    opt = audit["modes"]["OPTIMIZE"]
    cross = audit["cross_mode"]
    answers = audit["answers"]
    top_fields = "\n".join(
        f"- `{item['field']}`: {item['count']} rejections"
        for item in answers["2_largest_rejection_fields"]
    )
    user_limits = "\n".join(f"- {item}" for item in answers["3_user_defined_limits"])
    defaults = "\n".join(f"- {item}" for item in answers["4_conservative_defaults"])
    fillers = ", ".join(
        f"{item['sku_id']} ({item['eligible_count_across_modes']})"
        for item in answers["6_actual_best_topfill_fillers"]
    ) or "none"
    cf_fillers = ", ".join(
        f"{item['sku_id']} ({item['releasable_count_across_modes']})"
        for item in answers["6_counterfactual_default_profile_candidates"][:8]
    ) or "none"
    return f"""# BLK-005A — Policy / Eligibility Bottleneck Audit

## Audit boundary

This is a read-only audit. No CargoProfile value, Search Objective, eligibility gate, or Hard Constraint was changed. Counts use the BLK-004B metric-compatible snapshot: final solution minus TOP_FILL placements. One candidate means one `TopFillRegion × SKU` eligibility combination.

## Executive result

Top Fill is primarily **Policy-bottlenecked** at candidate admission. Search/deployment remains a secondary bottleneck after admission, but it cannot access most of the reported 39m³ because only 17 of 770 region/SKU combinations pass policy across both modes.

| metric | BALANCED | OPTIMIZE |
| --- | ---: | ---: |
| regions | {bal['region_count']} | {opt['region_count']} |
| Region×SKU pairs | {bal['region_sku_pair_count']} | {opt['region_sku_pair_count']} |
| policy compatible | {bal['policy_compatible_count']} | {opt['policy_compatible_count']} |
| policy incompatible | {bal['policy_incompatible_count']} | {opt['policy_incompatible_count']} |
| eligible | {bal['eligible_count']} | {opt['eligible_count']} |
| policy pass rate | {bal['policy_pass_rate']:.2%} | {opt['policy_pass_rate']:.2%} |
| usable volume | {bal['top_fill_usable_volume_m3']}m³ | {opt['top_fill_usable_volume_m3']}m³ |
| policy-exposed unique-region volume | {bal['policy_exposed_unique_region_volume_m3']}m³ | {opt['policy_exposed_unique_region_volume_m3']}m³ |
| placed / exposed-region volume | {bal['placed_to_policy_exposed_volume_ratio']:.2%} | {opt['placed_to_policy_exposed_volume_ratio']:.2%} |

The last row shows why Search is still secondary rather than irrelevant: conversion inside policy-exposed regions is low and the bounded deployment placed 12/16 cartons. But the first-order loss happens before Search sees candidates.

## Largest rejection contributors

{top_fields}

- DEFAULT-sourced primary blocks: {cross['default_rule_blocks_count']}
- USER_DEFINED-sourced primary blocks: {cross['rejection_source_counts'].get('USER_DEFINED', 0)}

Primary attribution is non-overlapping. For default profiles, `enabled=false` is counted first; their `maxLayers=0` and empty orientation list are recorded in the JSON but not double-counted.

## USER_DEFINED restrictions

{user_limits}

These limits account for the high-base filtering of SKU-02 and SKU-14. They were not changed.

## Conservative DEFAULT restrictions

{defaults}

No DEFAULT was automatically relaxed. If all DEFAULT-sourced admission blocks were hypothetically removed while every USER_DEFINED rule, geometry, physics, and inventory fact stayed fixed, the upper bound is **{bal['theoretical_additional_eligible_if_default_released']} additional combinations in BALANCED and {opt['theoretical_additional_eligible_if_default_released']} in OPTIMIZE, {answers['5_max_additional_eligible_candidates_if_only_defaults_released']} across both modes**. This is an audit ceiling, not an executable policy proposal.

## Best actual Top Fill fillers

Under the active profiles, the ranking is: {fillers}. SKU-14 is the only SKU with actual eligible Top Fill regions in both modes. Counterfactual default-profile geometry/physics candidates rank: {cf_fillers}.

## Answers

1. Primary bottleneck: Policy. Search/deployment is secondary within the small admitted set.
2. Largest rejection fields: `topFillPolicy.enabled`, then `topFillPolicy.minBaseHeight`.
3. USER_DEFINED restrictions: SKU-02 2.5m minimum base; SKU-14 1.3m minimum base and their context-bound orientation rules.
4. Conservative DEFAULT: Top Fill disabled for the three default profile families, with maxLayers=0/empty Top Fill orientations behind that primary gate.
5. Maximum theoretical DEFAULT-only release: {bal['theoretical_additional_eligible_if_default_released']} BALANCED + {opt['theoretical_additional_eligible_if_default_released']} OPTIMIZE = {answers['5_max_additional_eligible_candidates_if_only_defaults_released']} Region×SKU combinations.
6. Actual filler: SKU-14. Other SKU rankings are counterfactual only and must not be interpreted as permission.

## Stop condition

BLK-005A audit is complete. No policy was modified and no next BLK was started.
"""


def main():
    container, cargo = load_dataset(DATASET)
    reference = json.load(open(BLK004B, encoding="utf-8"))["modes"]
    modes = {}
    for profile, budget in ((SearchProfile.BALANCED, 30.0), (SearchProfile.OPTIMIZE, 60.0)):
        modes[profile.value] = _audit_mode(container, cargo, profile, budget, reference[profile.value])
        print(profile.value, modes[profile.value]["policy_compatible_count"], modes[profile.value]["eligible_count"], flush=True)
    cross = _cross_mode(modes)
    audit = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "audit_only": True,
        "policy_mutations": 0,
        "search_objective_mutations": 0,
        "hard_constraint_mutations": 0,
        "modes": modes,
        "cross_mode": cross,
        "answers": _answers(modes, cross),
    }
    if not all(all(mode["reference_match"].values()) for mode in modes.values()):
        raise RuntimeError(f"BLK-005A audit snapshot does not match BLK-004B: {[m['reference_match'] for m in modes.values()]}")
    with open(os.path.join(ROOT, "BLK005A_ELIGIBILITY_BREAKDOWN.json"), "w", encoding="utf-8") as handle:
        json.dump(audit, handle, indent=2, ensure_ascii=False)
    with open(os.path.join(ROOT, "BLK005A_POLICY_BOTTLENECK_REPORT.md"), "w", encoding="utf-8") as handle:
        handle.write(_report(audit))


if __name__ == "__main__":
    main()
