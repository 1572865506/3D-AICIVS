"""BLK-006E bounded terminal Top-Fill repair and legal solution neighborhood search.

The optimizer is deliberately downstream of GLOBAL wall-plan search.  It never
changes CargoProfile, hard thresholds, Door semantics, or the global objective.
Every trial is built on an isolated WorldState and only a strictly better,
independently validated COMPLETE_LEGAL result can replace its parent.
"""
from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from backend.solver_v2.domain.models import (
    CargoSKU, ContainerSpec, OrientationMode, PackingRole, Placement,
    PlacementContext, TopFillAdmissionState, ZoneType,
)
from backend.solver_v2.door.closure_planner import DoorClosurePlanner
from backend.solver_v2.door.elastic_frontier import ElasticDoorFrontier
from backend.solver_v2.physics.evaluator import PhysicsStabilityEngine
from backend.solver_v2.quantity.manager import QuantityManager, SpatialReservationManager
from backend.solver_v2.structure.cavity_classifier import AdvancedCavityClassifier
from backend.solver_v2.topfill.planner import ResidualRectangle, TopFillPlanner
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from backend.solver_v2.world.state import GeometricIntegrityError, WorldState
from backend.solver_v2.zones.manager import AdaptiveZoneManager


PLAN_FAMILIES = (
    "VOLUME_FIRST", "HEIGHT_FIRST", "FOOTPRINT_FIRST", "RESIDUAL_MATCH",
    "LAYER_COMPLETION", "MIXED_SKU", "ORIENTATION_DIVERSITY", "REGION_FIRST",
)


@dataclass(frozen=True)
class TerminalRepairConfig:
    profile: str = "BALANCED"
    stage_a_budget_sec: float = 20.0
    stage_b_budget_sec: float = 30.0
    stage_c_budget_sec: float = 30.0
    overall_budget_sec: float = 90.0
    max_plans_per_region: int = 8
    max_combination_states: int = 3
    max_topfill_seed_placements: int = 16
    lookahead_depth: int = 2
    monotonic_epsilon_m3: float = 1e-6
    enable_stage_b: bool = True
    enable_stage_c: bool = True

    @classmethod
    def for_profile(cls, profile: str) -> "TerminalRepairConfig":
        name = profile.upper()
        if name == "FAST":
            return cls(profile=name, stage_a_budget_sec=5.0, stage_b_budget_sec=0.0,
                       stage_c_budget_sec=0.0, overall_budget_sec=5.0,
                       max_combination_states=1, max_topfill_seed_placements=8,
                       enable_stage_b=False, enable_stage_c=False)
        if name == "OPTIMIZE":
            return cls(profile=name)
        return cls(profile="BALANCED", stage_c_budget_sec=0.0,
                   overall_budget_sec=50.0, enable_stage_c=False)


@dataclass
class TerminalRepairResult:
    placements: List[Placement]
    parent_volume_m3: float
    repaired_volume_m3: float
    accepted: bool
    source: str
    validation: Dict[str, Any]
    region_diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    plan_diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    trace: List[Dict[str, Any]] = field(default_factory=list)
    rejection_pareto: Dict[str, Any] = field(default_factory=dict)
    stage_summaries: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    runtime_sec: float = 0.0
    parent_main_volume_m3: float = 0.0
    parent_topfill_volume_m3: float = 0.0
    repaired_main_volume_m3: float = 0.0
    repaired_topfill_volume_m3: float = 0.0

    @property
    def volume_gain_m3(self) -> float:
        return self.repaired_volume_m3 - self.parent_volume_m3


class TerminalTopFillRepairOptimizer:
    """Deterministic Stage A/B/C repair with strict rollback and final validation."""

    def __init__(self, container: ContainerSpec, cargo: Sequence[CargoSKU],
                 config: Optional[TerminalRepairConfig] = None):
        self.container = container
        self.cargo = list(cargo)
        self.catalog = {sku.sku_id: sku for sku in cargo}
        self.config = config or TerminalRepairConfig()
        self.planner = TopFillPlanner(container)
        self._rejections: Counter = Counter()

    def optimize(self, parent_placements: Sequence[Placement]) -> TerminalRepairResult:
        started = time.perf_counter()
        parent = list(parent_placements)
        parent_volume = sum(p.volume for p in parent)
        parent_validation = self._validate_complete(parent)
        if not parent_validation["complete_legal"]:
            return TerminalRepairResult(
                placements=parent, parent_volume_m3=parent_volume,
                repaired_volume_m3=parent_volume, accepted=False,
                source="PARENT_RETAINED_INVALID_REPAIR_INPUT",
                validation=parent_validation, runtime_sec=time.perf_counter() - started,
            )

        best = parent
        best_volume = parent_volume
        trace: List[Dict[str, Any]] = []
        stage_summaries: Dict[str, Dict[str, Any]] = {}

        # Stage A freezes MAIN+DOOR and replaces all terminal Top Fill.
        base = [p for p in parent if p.context != PlacementContext.TOP_FILL]
        region_diag, plan_diag = self._describe_plans(base)
        stage_deadline = min(started + self.config.overall_budget_sec,
                             time.perf_counter() + self.config.stage_a_budget_sec)
        best, best_volume, summary = self._attempt_topfill_plans(
            "STAGE_A_TOPFILL_REPACK", base, best, best_volume, stage_deadline, trace,
        )
        stage_summaries["STAGE_A"] = summary

        # Stage B/C are conditionally activated only when Stage A did not match
        # the supplied parent. Their variants are generic geometric operators.
        if self.config.enable_stage_b and best_volume <= parent_volume + self.config.monotonic_epsilon_m3:
            deadline = min(started + self.config.overall_budget_sec,
                           time.perf_counter() + self.config.stage_b_budget_sec)
            variants = self._terminal_wall_variants(base, wall_count=1)
            best, best_volume, summary = self._attempt_neighborhood(
                "STAGE_B_LAST_WALL", variants, best, best_volume, deadline, trace,
            )
            stage_summaries["STAGE_B"] = summary
        else:
            stage_summaries["STAGE_B"] = {"activated": False, "reason": "STAGE_A_IMPROVED_OR_PROFILE_DISABLED"}

        if (self.config.enable_stage_c and best_volume <= parent_volume + self.config.monotonic_epsilon_m3
                and time.perf_counter() < started + self.config.overall_budget_sec):
            deadline = min(started + self.config.overall_budget_sec,
                           time.perf_counter() + self.config.stage_c_budget_sec)
            variants = self._terminal_wall_variants(base, wall_count=2)
            best, best_volume, summary = self._attempt_neighborhood(
                "STAGE_C_LAST_TWO_WALLS", variants, best, best_volume, deadline, trace,
            )
            stage_summaries["STAGE_C"] = summary
        else:
            stage_summaries["STAGE_C"] = {"activated": False, "reason": "STAGE_B_IMPROVED_OR_PROFILE_DISABLED"}

        accepted = best_volume > parent_volume + self.config.monotonic_epsilon_m3
        selected = best if accepted else parent
        final_validation = self._validate_complete(selected)
        if not final_validation["complete_legal"]:
            selected = parent
            best_volume = parent_volume
            accepted = False
            final_validation = parent_validation
            trace.append({"stage": "FINAL", "status": "ROLLBACK", "reason": "FINAL_GLOBAL_VALIDATION_FAILED"})

        return TerminalRepairResult(
            placements=selected, parent_volume_m3=parent_volume,
            repaired_volume_m3=sum(p.volume for p in selected), accepted=accepted,
            source="GLOBAL_REPAIRED" if accepted else "PARENT_RETAINED",
            validation=final_validation, region_diagnostics=region_diag,
            plan_diagnostics=plan_diag, trace=trace,
            rejection_pareto=self._pareto(), stage_summaries=stage_summaries,
            runtime_sec=time.perf_counter() - started,
            parent_main_volume_m3=sum(p.volume for p in parent if p.context != PlacementContext.TOP_FILL),
            parent_topfill_volume_m3=sum(p.volume for p in parent if p.context == PlacementContext.TOP_FILL),
            repaired_main_volume_m3=sum(p.volume for p in selected if p.context != PlacementContext.TOP_FILL),
            repaired_topfill_volume_m3=sum(p.volume for p in selected if p.context == PlacementContext.TOP_FILL),
        )

    def _build_state(self, placements: Iterable[Placement]) -> Tuple[WorldState, QuantityManager]:
        world = WorldState(self.container, self.cargo)
        qty = QuantityManager(self.cargo)
        for placement in sorted(placements, key=lambda p: (p.min_z, p.min_x, p.min_y, p.step_index)):
            world.commit(placement)
            qty.record_placement(placement.sku_id, placement.context)
        return world, qty

    def _describe_plans(self, base: List[Placement]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        world, qty = self._build_state(base)
        regions = self.planner.extract_top_fill_regions(world, self.catalog, qty_mgr=qty)
        region_rows: List[Dict[str, Any]] = []
        plan_rows: List[Dict[str, Any]] = []
        for region in regions:
            pool = self.planner.build_region_candidate_pool(world, region, qty, self.catalog)
            dx, dy = region.x_range[1] - region.x_range[0], region.y_range[1] - region.y_range[0]
            aspect = max(dx, dy) / max(min(dx, dy), 1e-9)
            if dx * dy < 0.04:
                shape = "SMALL_FRAGMENT"
            elif aspect >= 5.0:
                shape = "NARROW_STRIP"
            elif aspect >= 2.5:
                shape = "LONG_STRIP"
            elif region.local_flatness < 0.90:
                shape = "STEP_REGION"
            elif region.available_height > 0.8:
                shape = "MULTI_LEVEL_REGION"
            elif region.support_coverage >= 0.90:
                shape = "LARGE_CONTINUOUS"
            else:
                shape = "RECTANGULAR_POCKET"
            row = {
                "region_id": region.region_id, "logical_wall_id": region.logical_wall_id,
                "classification": shape, "x_range": list(region.x_range),
                "y_range": list(region.y_range), "base_z": region.base_z,
                "available_height": region.available_height, "support_area": region.support_area,
                "support_coverage": region.support_coverage, "local_flatness": region.local_flatness,
                "usable_volume": region.usable_volume, "neighbor_count": 0,
                "candidate_count": len(pool),
            }
            region_rows.append(row)
            residual = [ResidualRectangle(
                f"{region.region_id}_BASE", *region.x_range, *region.y_range, region.base_z, 1,
            )]
            for family in PLAN_FAMILIES[:self.config.max_plans_per_region]:
                options = self.planner._local_options(
                    region, pool, residual, qty, strategy=family,
                    lookahead_depth=self.config.lookahead_depth,
                )
                top = options[0] if options else None
                plan_rows.append({
                    "region_id": region.region_id, "plan_family": family,
                    "feasible": top is not None,
                    "seed_sku": top[1].sku_id if top else None,
                    "seed_orientation": top[1].orientation.name if top else None,
                    "score": round(top[0], 6) if top else None,
                    "inventory_reconciled_at_commit": True,
                })
        return region_rows, plan_rows

    def _strategy_order(self) -> List[str]:
        # Deterministic and geometry-generic.  Volume first is the primary repair
        # hypothesis; the remaining families supply bounded alternative plans.
        return list(PLAN_FAMILIES)

    def _attempt_topfill_plans(self, stage: str, base: List[Placement], current_best: List[Placement],
                               best_volume: float, deadline: float,
                               trace: List[Dict[str, Any]]) -> Tuple[List[Placement], float, Dict[str, Any]]:
        stage_started = time.perf_counter()
        attempts = accepted = 0
        start_volume = best_volume
        for family in self._strategy_order()[:self.config.max_combination_states]:
            if time.perf_counter() >= deadline:
                break
            attempts += 1
            try:
                world, qty = self._build_state(base)
                deployment = self.planner.deploy_conditional_top_fill(
                    world, qty, self.catalog, AdaptiveZoneManager(self.container),
                    SpatialReservationManager(),
                    max_placements=self.config.max_topfill_seed_placements,
                    strategy=family, lookahead_depth=self.config.lookahead_depth,
                    defer_plan_level_validation=True,
                )
                for plan in deployment.region_plans.values():
                    funnel = plan.get("funnel", {})
                    mapping = {
                        "COLLISION": "COLLISION", "SUPPORT": "SUPPORT",
                        "STABILITY": "STABILITY", "LAYER_LIMIT": "LAYER_LIMIT",
                        "INVENTORY": "INVENTORY", "REGION_EXHAUSTED": "REGION_UNREACHABLE",
                        "RANKED_OUT": "FRAGMENTATION_OR_RANKING",
                        "ATTEMPT_FAILED": "PHYSICS_OR_POLICY",
                    }
                    for source, target in mapping.items():
                        self._rejections[target] += int(funnel.get(source, 0) or 0)
                self._rejections["COMPRESSION"] += deployment.rejected_compression
                self._rejections["ORIENTATION_POLICY"] += deployment.rejected_orientation_context
                candidate = world.placements
                volume = sum(p.volume for p in candidate)
                validation = self._validate_complete(candidate)
                monotonic = volume > best_volume + self.config.monotonic_epsilon_m3
                ok = monotonic and validation["complete_legal"]
                if ok:
                    current_best, best_volume, accepted = candidate, volume, accepted + 1
                else:
                    self._rejections["NO_VOLUME_GAIN" if not monotonic else "GLOBAL_VALIDATION"] += 1
                trace.append({
                    "stage": stage, "operator": family, "status": "ACCEPTED" if ok else "ROLLED_BACK",
                    "placed_topfill": deployment.placed_count, "candidate_volume_m3": volume,
                    "gain_vs_current_m3": volume - best_volume if not ok else volume - start_volume,
                    "complete_legal": validation["complete_legal"],
                    "rejection_reason": None if ok else ("NON_MONOTONIC" if not monotonic else "HARD_VALIDATION"),
                })
            except (GeometricIntegrityError, ValueError, KeyError) as exc:
                self._rejections["COLLISION_OR_BOUNDS"] += 1
                trace.append({"stage": stage, "operator": family, "status": "ROLLED_BACK",
                              "rejection_reason": type(exc).__name__})
        return current_best, best_volume, {
            "activated": True, "attempts": attempts, "accepted_trials": accepted,
            "gain_m3": best_volume - start_volume, "budget_exhausted": time.perf_counter() >= deadline,
            "runtime_sec": time.perf_counter() - stage_started,
        }

    def _terminal_wall_variants(self, base: List[Placement], wall_count: int) -> List[Tuple[str, List[Placement]]]:
        main = [p for p in base if p.context not in (PlacementContext.DOOR_SEAL, PlacementContext.TOP_FILL)]
        fixed_door = [p for p in base if p.context == PlacementContext.DOOR_SEAL]
        walls = self.planner.container and WorldState(self.container, self.cargo).wall_analyzer.extract_walls(main)
        selected = sorted(walls, key=lambda w: (w.x_end, w.wall_id))[-wall_count:]
        selected_ids = {p.placement_id for wall in selected for p in wall.placements}
        fixed = [p for p in main if p.placement_id not in selected_ids] + fixed_door
        terminal = [p for p in main if p.placement_id in selected_ids]
        if not terminal:
            return []
        variants: List[Tuple[str, List[Placement]]] = [("REPACK_SAME_GEOMETRY", fixed + terminal)]
        max_y = max(p.max_y for p in terminal)
        width_variant = [p for p in terminal if p.max_y < max_y - 1e-6]
        if width_variant:
            variants.append(("REDUCE_TERMINAL_WALL_WIDTH", fixed + width_variant))
        max_z = max(p.max_z for p in terminal)
        height_variant = [p for p in terminal if p.max_z < max_z - 1e-6]
        if height_variant:
            variants.append(("REDUCE_TERMINAL_WALL_HEIGHT", fixed + height_variant))
        return variants

    def _attempt_neighborhood(self, stage: str, variants: List[Tuple[str, List[Placement]]],
                              current_best: List[Placement], best_volume: float, deadline: float,
                              trace: List[Dict[str, Any]]) -> Tuple[List[Placement], float, Dict[str, Any]]:
        start_volume = best_volume
        attempts = 0
        for operator, base in variants:
            if time.perf_counter() >= deadline:
                break
            attempts += 1
            current_best, best_volume, _ = self._attempt_topfill_plans(
                f"{stage}:{operator}", base, current_best, best_volume, deadline, trace,
            )
        return current_best, best_volume, {
            "activated": True, "operators_generated": len(variants), "operators_attempted": attempts,
            "gain_m3": best_volume - start_volume, "budget_exhausted": time.perf_counter() >= deadline,
        }

    def _validate_complete(self, placements: List[Placement]) -> Dict[str, Any]:
        validation = IndependentGlobalValidator.validate(self.container, placements, self.cargo)
        physics = PhysicsStabilityEngine().evaluate_system(self.container, placements, self.catalog)
        cavity = AdvancedCavityClassifier(self.container).classify_cavities(placements)
        door_skus = [sku for sku in self.cargo if PackingRole.DOOR_SEAL in sku.packing_roles or sku.target_zone == ZoneType.DOOR]
        frontier = ElasticDoorFrontier(self.container, door_skus)
        door = DoorClosurePlanner(self.container, frontier=frontier).evaluate_door_readiness(
            placements, reserve_deployed=sum(p.context == PlacementContext.DOOR_SEAL for p in placements),
            has_door_reserve_pool=bool(door_skus),
        )
        auto_flat = main_conditional = 0
        counts = Counter(p.sku_id for p in placements)
        inventory_ok = all(counts[sku.sku_id] <= (sku.quantity.max_quantity or sku.quantity.required) for sku in self.cargo)
        for p in placements:
            sku = self.catalog[p.sku_id]
            if p.context == PlacementContext.TOP_FILL and p.orientation.is_flat:
                if sku.cargo_profile and sku.cargo_profile.top_fill_policy.admission_state == TopFillAdmissionState.AUTO:
                    auto_flat += 1
            elif p.orientation.is_flat:
                rule = sku.orientation_policy.rule_for(OrientationMode.FLAT, p.context)
                if rule is not None and rule.condition != "ALWAYS":
                    main_conditional += 1
        complete = (
            validation.is_valid and physics.is_valid and door.is_door_ready and inventory_ok
            and not cavity.enclosed_cavities and cavity.bridge_void_count == 0
            and auto_flat == 0 and main_conditional == 0
        )
        return {
            "complete_legal": complete, "global_validator_valid": validation.is_valid,
            "physics_valid": physics.is_valid, "door_ready": door.is_door_ready,
            "inventory_valid": inventory_ok, "enclosed_cavity": len(cavity.enclosed_cavities),
            "bridge_void": cavity.bridge_void_count, "auto_flat": auto_flat,
            "main_body_conditional_flat": main_conditional,
            "hard_violation_count": len(validation.violations),
        }

    def _pareto(self) -> Dict[str, Any]:
        total = sum(self._rejections.values())
        rows = []
        cumulative = 0
        for reason, count in self._rejections.most_common():
            cumulative += count
            rows.append({"reason": reason, "count": count,
                         "share": count / max(total, 1), "cumulative_share": cumulative / max(total, 1)})
        return {"total_rejections": total, "reasons": rows}
