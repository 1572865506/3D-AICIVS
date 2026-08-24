"""
Bounded Beam Search over Aggregate Structures with Limited Backtracking (Agent 09 / BLK-002B).
Equipped with ElasticDoorFrontier, Progress Watchdog (WALL_STALL), Valley Filling, and stepwise aggregate downgrade.
Search Objective: Hard Validity -> Volume / Space Utilization -> X Progression -> Wall Continuity -> SKU Diversity -> Carton Count.
"""
import time
import copy
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any, Set

from backend.solver_v2.domain.models import (
    ContainerSpec,
    CargoSKU,
    Placement,
    PlacementContext,
    ZoneType,
    PackingRole,
    Point3D,
    Orientation3D,
)
from backend.solver_v2.world.state import WorldState
from backend.solver_v2.spaces.types import AnchorCategory
from backend.solver_v2.spaces.engine import FreeSpaceEngine
from backend.solver_v2.orientation.manager import OrientationEngine
from backend.solver_v2.zones.manager import AdaptiveZoneManager
from backend.solver_v2.quantity.manager import QuantityManager, SpatialReservationManager
from backend.solver_v2.candidates.generator import CandidateGenerator, CandidatePlacement
from backend.solver_v2.feasibility.pipeline import HardValidationPipeline
from backend.solver_v2.solver.scorer import CandidateScorer
from backend.solver_v2.door.elastic_frontier import ElasticDoorFrontier
from backend.solver_v2.search.config import SearchConfig
from backend.solver_v2.search.aggregate import AggregateCandidateGenerator, AggregateCandidate
from backend.solver_v2.topfill.planner import TopFillPlanner
from backend.solver_v2.physics.evaluator import PhysicsStabilityEngine
from backend.solver_v2.search.global_wall_search import (
    GLOBAL_SEARCH, FutureTopFillEstimator, GlobalWallObjective, SearchState,
    WallCandidate, SearchStateSignature, beam_diversity_key, root_search_state,
)
from backend.solver_v2.search.diverse_wall_candidates import (
    CandidateSignature, DiverseWallCandidateGenerator,
)
from backend.solver_v2.structure.cavity_classifier import AdvancedCavityClassifier


@dataclass
class BeamNode:
    """Represents a state node in the Bounded Beam search tree."""
    node_id: str
    placements: List[Placement] = field(default_factory=list)
    placed_quantities: Dict[str, int] = field(default_factory=dict)
    cumulative_score: float = 0.0
    total_volume: float = 0.0
    total_weight_kg: float = 0.0
    depth: int = 0
    phase_idx: int = 0
    parent_id: Optional[str] = None
    step_history: List[int] = field(default_factory=list)
    last_max_x: float = 0.0
    stall_count: int = 0
    search_state: Optional[SearchState] = None

    @property
    def placed_count(self) -> int:
        return len(self.placements)


class BoundedBeamSearchEngine:
    """
    Orchestrates Bounded Beam Search over Aggregate Structures:
    - Phase 1: Foundation (Floor)
    - Phase 2: Main Body (Aggregate Blocks & Layers)
    - Phase 3: Transition (Smoothing & Base Preparation)
    - Phase 4: Top Fill (Headspace)
    - Phase 5: Door Seal Closure
    """

    def __init__(
        self,
        container: ContainerSpec,
        cargo_list: List[CargoSKU],
        config: SearchConfig,
    ):
        self.container = container
        self.cargo_list = cargo_list
        self.config = config
        self.sku_catalog = {s.sku_id: s for s in cargo_list}
        self.total_required_items = sum(s.quantity.required for s in cargo_list)

        self.door_seal_skus = [s for s in cargo_list if PackingRole.DOOR_SEAL in s.packing_roles or s.target_zone == ZoneType.DOOR]
        self.elastic_frontier = ElasticDoorFrontier(container=self.container, door_skus=self.door_seal_skus)

        self.agg_generator = AggregateCandidateGenerator()
        self.candidate_gen = CandidateGenerator()
        self.validator_pipeline = HardValidationPipeline()
        self.scorer = CandidateScorer()
        self.physics_engine = PhysicsStabilityEngine()
        self.wall_objective = GlobalWallObjective(container)
        self.topfill_estimator = FutureTopFillEstimator(container, self.sku_catalog)
        self.diverse_wall_generator = DiverseWallCandidateGenerator()
        self._global_started = time.perf_counter()
        self._deep_profile_samples: Dict[str, List[float]] = defaultdict(list)
        self._cache_counters: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"hits": 0, "misses": 0, "saved_estimated_ms": 0.0}
        )
        self._topfill_estimate_cache: Dict[Tuple[Any, ...], Dict[str, Any]] = {}

        # Telemetry tracking for search
        self.telemetry: Dict[str, Any] = {
            "candidates_generated": 0,
            "candidates_evaluated": 0,
            "candidates_rejected_by_reason": {},
            "anchors_generated_by_type": {},
            "anchors_sampled_by_type": {},
            "candidates_generated_by_anchor_type": {},
            "candidates_valid_by_anchor_type": {},
            "floor_frontier_count": 0,
            "supported_frontier_count": 0,
            "wall_frontier_count": 0,
            "phase_termination_reason": {},
            "wall_plan_search": {
                "mode": self.config.wall_plan_search_mode,
                "states_generated": 0,
                "states_expanded": 0,
                "candidates_generated": 0,
                "candidates_rejected": 0,
                "objective_values": [],
                "search_trace": [],
                "selected_path": [],
                "max_depth": 0,
                "candidate_diversity_by_state": {},
                "duplicate_states_removed": 0,
                "dominated_states_removed": 0,
                "candidate_cap_pruned": 0,
                "beam_pruned": 0,
                "dead_end_states": {},
                "budget_stop_reason": None,
                "topfill_estimator_calls": 0,
                "full_topfill_calls": 0,
                "complete_solutions_found": 0,
                "incumbent_updates": 0,
                "incumbent_history": [],
                "fallback_used": False,
                "returned_solution_source": "GLOBAL_SEARCH" if self.config.wall_plan_search_mode == GLOBAL_SEARCH else "LEGACY_GREEDY",
                "performance": {
                    "candidate_generation_ms": 0.0, "candidate_generation_calls": 0,
                    "hard_validation_ms": 0.0, "hard_validation_calls": 0,
                    "state_clone_ms": 0.0, "state_clone_calls": 0,
                    "objective_ms": 0.0, "objective_calls": 0,
                    "topfill_estimate_ms": 0.0, "topfill_estimate_calls": 0,
                    "state_expansion_ms": 0.0, "state_expansion_calls": 0,
                },
            },
        }

    def search(
        self,
        sku_priority_order: Optional[List[str]] = None,
        deadline_perf_counter: Optional[float] = None,
    ) -> List[Placement]:
        """
        Executes bounded beam search across phases with aggregate structures.
        Returns the best list of Placements found.
        """
        phases = [
            (PlacementContext.FOUNDATION, "Phase 1: Foundation"),
            (PlacementContext.MAIN_WALL, "Phase 2: MainBody"),
        ] if self.config.wall_plan_search_mode == GLOBAL_SEARCH else [
            (PlacementContext.FOUNDATION, "Phase 1: Foundation"),
            (PlacementContext.MAIN_WALL, "Phase 2: MainBody"),
            (PlacementContext.GAP_FILL, "Phase 3: Transition"),
            (PlacementContext.TOP_FILL, "Phase 4: TopFill"),
            (PlacementContext.DOOR_SEAL, "Phase 5: DoorSeal"),
        ]

        root = BeamNode(
            node_id="root",
            placements=[],
            placed_quantities={s.sku_id: 0 for s in self.cargo_list},
            cumulative_score=0.0,
            total_volume=0.0,
            total_weight_kg=0.0,
            depth=0,
            phase_idx=0,
            last_max_x=0.0,
            stall_count=0,
            search_state=root_search_state(self.cargo_list),
        )

        current_beam: List[BeamNode] = [root]
        best_completed_node: BeamNode = root

        for phase_idx, (context, phase_name) in enumerate(phases):
            if deadline_perf_counter and time.perf_counter() >= deadline_perf_counter:
                self.telemetry["phase_termination_reason"][phase_name] = "TIME_BUDGET_EXCEEDED"
                break

            next_beam = self._expand_phase(
                current_beam=current_beam,
                context=context,
                phase_idx=phase_idx,
                phase_name=phase_name,
                sku_priority_order=sku_priority_order,
                deadline_perf_counter=deadline_perf_counter,
            )

            if next_beam:
                current_beam = next_beam
                if self.config.wall_plan_search_mode == GLOBAL_SEARCH:
                    next_phase = (
                        "TRANSITION" if context == PlacementContext.MAIN_WALL else
                        "DOOR" if context == PlacementContext.GAP_FILL else
                        "TOP_FILL" if context == PlacementContext.DOOR_SEAL else
                        "COMPLETE" if context == PlacementContext.TOP_FILL else "MAIN"
                    )
                    for node in current_beam:
                        if node.search_state is not None:
                            isolated = node.search_state.clone(
                                state_id=node.search_state.state_id,
                                parent_state=node.search_state.parent_state,
                            )
                            isolated.phase = next_phase
                            node.search_state = isolated
                for node in current_beam:
                    if self._is_better_node(node, best_completed_node):
                        best_completed_node = node
            else:
                self.telemetry["phase_termination_reason"][phase_name] = "NO_VALID_EXPANSION"
                break

        # Record validation rejections into telemetry
        self.telemetry["candidates_rejected_by_reason"] = dict(self.validator_pipeline.rejection_counts)
        if best_completed_node.search_state is not None:
            self.telemetry["wall_plan_search"]["selected_path"] = list(best_completed_node.search_state.wall_sequence)
            self.telemetry["wall_plan_search"]["selected_state"] = best_completed_node.search_state.to_dict()
        performance = self.telemetry["wall_plan_search"]["performance"]
        self.telemetry["wall_plan_search"]["performance_averages_ms"] = {
            name.replace("_ms", "_ms"): round(
                performance[name] / max(1, performance.get(name.replace("_ms", "_calls"), 0)), 6,
            )
            for name in (
                "candidate_generation_ms", "hard_validation_ms", "state_clone_ms",
                "objective_ms", "topfill_estimate_ms", "state_expansion_ms",
            )
        }
        self.telemetry["wall_plan_search"]["deep_profile"] = self._deep_profile_summary()
        self.telemetry["wall_plan_search"]["cache_diagnostic"] = self._cache_summary()
        return best_completed_node.placements

    def _record_profile(self, stage: str, elapsed_ms: float) -> None:
        self._deep_profile_samples[stage].append(max(0.0, elapsed_ms))

    def _deep_profile_summary(self) -> Dict[str, Dict[str, float]]:
        summary: Dict[str, Dict[str, float]] = {}
        required = {
            "candidate_enumeration_ms", "candidate_geometry_build_ms", "collision_query_ms",
            "support_graph_ms", "load_propagation_ms", "compression_validation_ms",
            "stability_validation_ms", "bounds_validation_ms", "zone_validation_ms",
            "handling_validation_ms", "residual_space_update_ms", "top_surface_update_ms",
            "inventory_update_ms", "state_signature_ms", "dominance_check_ms",
            "candidate_ranking_ms", "state_reconstruction_ms", "state_expansion_inclusive_ms",
        }
        for stage in sorted(required.union(self._deep_profile_samples)):
            samples = self._deep_profile_samples.get(stage, [])
            if not samples:
                summary[stage] = {
                    "exclusive_ms": 0.0, "inclusive_ms": 0.0, "call_count": 0,
                    "avg_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0,
                }
                continue
            ordered = sorted(samples)
            total = sum(ordered)
            p95_index = min(len(ordered) - 1, max(0, int(math.ceil(.95 * len(ordered))) - 1))
            summary[stage] = {
                "exclusive_ms": round(total, 6),
                "inclusive_ms": round(total, 6),
                "call_count": len(ordered),
                "avg_ms": round(total / max(1, len(ordered)), 6),
                "p50_ms": round(statistics.median(ordered), 6),
                "p95_ms": round(ordered[p95_index], 6),
                "max_ms": round(max(ordered), 6),
            }
        parent = summary.pop("state_expansion_inclusive_ms", None)
        if parent is not None:
            child_total = sum(
                value["exclusive_ms"] for key, value in summary.items()
                if key not in {"state_signature_ms", "dominance_check_ms"}
            )
            parent["exclusive_ms"] = round(max(0.0, parent["inclusive_ms"] - child_total), 6)
            summary["state_expansion_ms"] = parent
        return summary

    def _cache_summary(self) -> Dict[str, Dict[str, float]]:
        result: Dict[str, Dict[str, float]] = {}
        for name, counters in sorted(self._cache_counters.items()):
            calls = counters["hits"] + counters["misses"]
            result[name] = {
                "cache_hits": int(counters["hits"]),
                "cache_misses": int(counters["misses"]),
                "hit_rate": round(counters["hits"] / calls, 6) if calls else 0.0,
                "saved_estimated_ms": round(counters["saved_estimated_ms"], 6),
            }
        geometry_calls = self.diverse_wall_generator.cache_hits + self.diverse_wall_generator.cache_misses
        result["CandidateGeometryCache"] = {
            "cache_hits": self.diverse_wall_generator.cache_hits,
            "cache_misses": self.diverse_wall_generator.cache_misses,
            "hit_rate": round(self.diverse_wall_generator.cache_hits / geometry_calls, 6) if geometry_calls else 0.0,
            "saved_estimated_ms": round(self.diverse_wall_generator.cache_saved_estimated_ms, 6),
        }
        return result

    def _expand_phase(
        self,
        current_beam: List[BeamNode],
        context: PlacementContext,
        phase_idx: int,
        phase_name: str,
        sku_priority_order: Optional[List[str]] = None,
        deadline_perf_counter: Optional[float] = None,
    ) -> List[BeamNode]:
        """
        Expands all nodes in current beam until the phase is saturated or budget runs out.
        """
        active_nodes = list(current_beam)

        while active_nodes:
            if deadline_perf_counter and time.perf_counter() >= deadline_perf_counter:
                self.telemetry["phase_termination_reason"][phase_name] = "TIMEOUT_IN_EXPANSION"
                break

            expansion_candidates: List[BeamNode] = []
            progress_made = False

            for node in active_nodes:
                if deadline_perf_counter and time.perf_counter() >= deadline_perf_counter:
                    break

                node_expansion_started = time.perf_counter()
                # Reconstruct transient state for this node
                reconstruction_started = time.perf_counter()
                world_state, space_engine, zone_mgr, qty_mgr, res_mgr = self._reconstruct_state(node)
                self._record_profile(
                    "state_reconstruction_ms", (time.perf_counter() - reconstruction_started) * 1000.0,
                )
                if context == PlacementContext.MAIN_WALL and self.config.wall_plan_search_mode == GLOBAL_SEARCH:
                    if self._global_budget_reached():
                        self._record_dead_end(self.telemetry["wall_plan_search"]["budget_stop_reason"] or "STATE_BUDGET_STOP")
                        expansion_candidates.append(node)
                        continue
                    self.telemetry["wall_plan_search"]["states_expanded"] += 1
                    optimistic_remaining = sum(
                        max(0, sku.quantity.required - node.placed_quantities.get(sku.sku_id, 0)) * sku.box.volume
                        for sku in self.cargo_list
                    )
                    optimistic_upper_bound = min(
                        self.container.volume, node.total_volume + optimistic_remaining,
                    )
                    self.telemetry["wall_plan_search"].setdefault("upper_bound_checks", 0)
                    self.telemetry["wall_plan_search"]["upper_bound_checks"] += 1
                    if (
                        self.config.global_incumbent_volume_m3 > 0.0
                        and optimistic_upper_bound <= self.config.global_incumbent_volume_m3 + 1e-9
                    ):
                        self.telemetry["wall_plan_search"].setdefault("bound_pruned", 0)
                        self.telemetry["wall_plan_search"]["bound_pruned"] += 1
                        self._record_dead_end("BOUND_PRUNED")
                        expansion_candidates.append(node)
                        continue
                    if node.search_state is not None and node.search_state.depth >= self.config.global_wall_max_depth:
                        self._record_dead_end("DEPTH_LIMIT_REACHED")
                        expansion_candidates.append(node)
                        continue

                # If door seal context, release door reservation
                if context == PlacementContext.DOOR_SEAL:
                    for r in res_mgr._reservations.values():
                        if r.reservation_id == "DOOR_ZONE_RESERVATION":
                            r.is_active = False

                # Select eligible SKUs for this phase
                eligible_skus = self._get_phase_skus(qty_mgr, context, sku_priority_order)
                if not eligible_skus:
                    if context == PlacementContext.MAIN_WALL and self.config.wall_plan_search_mode == GLOBAL_SEARCH:
                        self._record_dead_end("INVENTORY_EXHAUSTED")
                    expansion_candidates.append(node)
                    continue

                # Progress Watchdog: check if stalled in X
                is_stalled = (node.stall_count >= self.config.wall_stall_threshold)

                # Generate candidates (stepwise aggregate downgrade + continuous frontier)
                generation_started = time.perf_counter()
                agg_candidates = self.agg_generator.generate_aggregate_candidates(
                    space_engine=space_engine,
                    orientation_engine=OrientationEngine(),
                    zone_mgr=zone_mgr,
                    qty_mgr=qty_mgr,
                    active_skus=eligible_skus,
                    context=context,
                    max_candidates=self.config.max_candidates_per_step,
                    enable_patterns=self.config.enable_pattern_aggregation,
                    world_state=world_state,
                    is_wall_stalled=is_stalled,
                )
                self._record_profile(
                    "candidate_enumeration_ms", (time.perf_counter() - generation_started) * 1000.0,
                )
                if context == PlacementContext.MAIN_WALL and self.config.wall_plan_search_mode == GLOBAL_SEARCH:
                    perf = self.telemetry["wall_plan_search"]["performance"]
                    perf["candidate_generation_ms"] += (time.perf_counter() - generation_started) * 1000.0
                    perf["candidate_generation_calls"] += 1

                self.telemetry["candidates_generated"] += len(agg_candidates)

                if not agg_candidates:
                    if context == PlacementContext.MAIN_WALL and self.config.wall_plan_search_mode == GLOBAL_SEARCH:
                        self._record_dead_end("FRONTIER_BLOCKED")
                    expansion_candidates.append(node)
                    continue

                diversity_diag = None
                if context == PlacementContext.MAIN_WALL and self.config.wall_plan_search_mode == GLOBAL_SEARCH:
                    # Raw aggregates are proposals. Only bounded, fully validated
                    # proposals become WallCandidates and enter the global beam.
                    geometry_started = time.perf_counter()
                    pool = self.diverse_wall_generator.build_pool(
                        agg_candidates, world_state, qty_mgr,
                        max_proposals=max(1, self.config.global_wall_candidates_per_state),
                        phase=node.search_state.phase if node.search_state is not None else "MAIN",
                    )
                    self._record_profile(
                        "candidate_geometry_build_ms", (time.perf_counter() - geometry_started) * 1000.0,
                    )
                    agg_candidates = pool.proposals
                    self.telemetry["wall_plan_search"]["candidate_cap_pruned"] += max(
                        0, pool.raw_generated - pool.duplicates_removed - pool.cheap_rejected - len(agg_candidates)
                    )
                    self.telemetry["wall_plan_search"]["candidates_generated"] += len(agg_candidates)
                    state_key = node.search_state.state_id if node.search_state else node.node_id
                    diversity_diag = {
                        "state_id": state_key,
                        "proposals_generated": len(agg_candidates),
                        "raw_generated": pool.raw_generated,
                        "duplicates_removed": pool.duplicates_removed,
                        "cheap_rejected": pool.cheap_rejected,
                        "cheap_rejection_reasons": pool.cheap_rejection_reasons,
                        "hard_rejected": 0,
                        "valid_candidates": 0,
                        "structurally_distinct_valid_candidates": 0,
                        "valid_by_family": {}, "valid_by_sku": {}, "valid_by_orientation": {},
                        "valid_by_wall_width_bucket": {}, "valid_by_layer_count": {},
                        "proposed_by_family": pool.proposed_by_family,
                        "valid_signatures": [], "scores": [],
                    }
                    self.telemetry["wall_plan_search"]["candidate_diversity_by_state"][state_key] = diversity_diag

                topfill_planner = TopFillPlanner(self.container) if context == PlacementContext.TOP_FILL else None
                topfill_regions = {
                    r.region_id: r for r in topfill_planner.extract_top_fill_regions(world_state, self.sku_catalog)
                } if topfill_planner else {}

                # Validate and score aggregate candidates
                branch_children: List[Tuple[float, BeamNode]] = []

                for agg in agg_candidates:
                    if deadline_perf_counter and time.perf_counter() >= deadline_perf_counter:
                        break
                    if context == PlacementContext.MAIN_WALL and self.config.wall_plan_search_mode == GLOBAL_SEARCH and self._global_budget_reached():
                        break
                    validation_started = time.perf_counter()
                    composition = Counter(item.sku_id for item in agg.item_candidates)
                    if any(qty_mgr.get_remaining(sid, context=context) < count for sid, count in composition.items()):
                        if diversity_diag is not None:
                            diversity_diag["hard_rejected"] += 1
                        continue

                    all_valid = True
                    committed_deltas = []
                    child_placements: List[Placement] = []

                    step_base = len(node.placements)
                    for item_idx, item_cand in enumerate(agg.item_candidates):
                        sku = self.sku_catalog[item_cand.sku_id]
                        self.telemetry["candidates_evaluated"] += 1
                        is_feasible, hard_reason = self.validator_pipeline.is_feasible(
                            candidate=item_cand,
                            sku=sku,
                            world_state=world_state,
                            zone_mgr=zone_mgr,
                            res_mgr=res_mgr,
                            elastic_frontier=self.elastic_frontier,
                            context=context,
                            timing_hook=self._record_profile,
                        )
                        if not is_feasible:
                            all_valid = False
                            if context == PlacementContext.MAIN_WALL and self.config.wall_plan_search_mode == GLOBAL_SEARCH:
                                self._trace_wall_rejection(node, agg.candidate_id, hard_reason or "HARD_VALIDATOR")
                            break
                        if topfill_planner:
                            region = topfill_regions.get(item_cand.topfill_region_id or "")
                            if region is None:
                                self.validator_pipeline.rejection_counts["TOP_FILL_REGION_REQUIRED"] += 1
                                all_valid = False
                                break
                            top_eval = topfill_planner.evaluate_topfill_candidate(
                                item_cand, sku, region, world_state, self.sku_catalog, zone_mgr,
                            )
                            if not top_eval.is_valid:
                                key = (
                                    "TOP_FILL_INSUFFICIENT_SUPPORT" if not top_eval.support_passed else
                                    "TOP_FILL_COMPRESSION" if not top_eval.compression_passed else
                                    "TOP_FILL_ORIENTATION_CONTEXT" if not top_eval.orientation_context_passed else
                                    "TOP_FILL_MAX_LAYERS" if not top_eval.layer_limit_passed else
                                    "TOP_FILL_STABILITY"
                                )
                                self.validator_pipeline.rejection_counts[key] += 1
                                all_valid = False
                                break

                        p_id = f"p_{step_base + item_idx:04d}_{item_cand.sku_id}"
                        p_inst = f"inst_{step_base + item_idx:04d}"
                        placement = item_cand.to_placement(
                            placement_id=p_id,
                            instance_id=p_inst,
                            step_index=step_base + item_idx,
                        )
                        commit_started = time.perf_counter()
                        try:
                            delta = world_state.commit(placement)
                            committed_deltas.append(delta)
                            child_placements.append(placement)
                        except Exception:
                            all_valid = False
                            break
                        finally:
                            self._record_profile(
                                "incremental_commit_ms", (time.perf_counter() - commit_started) * 1000.0,
                            )

                    physics = None
                    if all_valid and len(child_placements) == agg.item_count and context == PlacementContext.MAIN_WALL and self.config.wall_plan_search_mode == GLOBAL_SEARCH:
                        physics = self._evaluate_wall_candidate_physics(world_state, child_placements)
                        if not physics["is_valid"]:
                            all_valid = False
                            reason = "COMPRESSION" if not physics["load_report"].is_valid else "STABILITY"
                            self._trace_wall_rejection(node, agg.candidate_id, reason)

                    if all_valid and len(child_placements) == agg.item_count and context == PlacementContext.MAIN_WALL and self.config.wall_plan_search_mode == GLOBAL_SEARCH:
                        cavity_ok, cavity_reason = self._candidate_cavity_gate(
                            node, agg, world_state, zone_mgr,
                        )
                        if not cavity_ok:
                            all_valid = False
                            self._trace_wall_rejection(node, agg.candidate_id, cavity_reason)

                    if all_valid and len(child_placements) == agg.item_count:
                        first_cand = agg.item_candidates[0]
                        first_sku = self.sku_catalog[first_cand.sku_id]
                        score = self.scorer.score_candidate(
                            candidate=first_cand,
                            sku=first_sku,
                            world_state=world_state,
                            space_engine=space_engine,
                            zone_mgr=zone_mgr,
                            remaining_skus=eligible_skus,
                            elastic_frontier=self.elastic_frontier,
                            context=context,
                        )
                        # Volume-based aggregate score bonus (proportional to volume, NOT raw carton count)
                        if agg.item_count > 1:
                            score += 50.0 * agg.total_volume

                        child_search_state = node.search_state
                        if context == PlacementContext.MAIN_WALL and self.config.wall_plan_search_mode == GLOBAL_SEARCH:
                            parent_state = self._synchronized_search_state(node, qty_mgr, world_state, child_placements)
                            wall_candidate = WallCandidate.from_placements(
                                agg.candidate_id, "+".join(sorted(composition)), child_placements,
                            )
                            inventory_started = time.perf_counter()
                            remaining = {
                                sid: max(0, qty_mgr.get_remaining(sid, PlacementContext.MAIN_WALL) - composition.get(sid, 0))
                                for sid in self.sku_catalog
                            }
                            self._record_profile(
                                "inventory_update_ms", (time.perf_counter() - inventory_started) * 1000.0,
                            )
                            topfill_started = time.perf_counter()
                            topfill_key = (
                                tuple(sorted(remaining.items())), parent_state.phase,
                                tuple((p.sku_id, p.orientation.name, round(p.min_x, 4), round(p.min_y, 4),
                                       round(p.min_z, 4), round(p.max_x, 4), round(p.max_y, 4), round(p.max_z, 4))
                                      for p in wall_candidate.placements),
                            )
                            if topfill_key in self._topfill_estimate_cache:
                                topfill = copy.deepcopy(self._topfill_estimate_cache[topfill_key])
                                counters = self._cache_counters["TopFillEstimateCache"]
                                counters["hits"] += 1
                                counters["saved_estimated_ms"] += 0.08
                            else:
                                topfill = self.topfill_estimator.estimate(wall_candidate, remaining)
                                self._topfill_estimate_cache[topfill_key] = copy.deepcopy(topfill)
                                self._cache_counters["TopFillEstimateCache"]["misses"] += 1
                            perf = self.telemetry["wall_plan_search"]["performance"]
                            perf["topfill_estimate_ms"] += (time.perf_counter() - topfill_started) * 1000.0
                            perf["topfill_estimate_calls"] += 1
                            self._record_profile(
                                "top_surface_update_ms", (time.perf_counter() - topfill_started) * 1000.0,
                            )
                            self.telemetry["wall_plan_search"]["topfill_estimator_calls"] += 1
                            support_ratios = [
                                world_state.support_graph.get_total_support_ratio(p.placement_id)
                                for p in child_placements
                            ]
                            support_margin = min(support_ratios, default=1.0)
                            objective_started = time.perf_counter()
                            objective = self.wall_objective.evaluate(
                                parent_state, wall_candidate, topfill,
                                sum(qty_mgr.get_remaining(sid, PlacementContext.MAIN_WALL) for sid in composition),
                                self.container.Lx - zone_mgr.door_zone_length_m,
                                support_margin,
                            )
                            perf["objective_ms"] += (time.perf_counter() - objective_started) * 1000.0
                            perf["objective_calls"] += 1
                            state_id = f"{parent_state.state_id}/{agg.candidate_id}"
                            clone_started = time.perf_counter()
                            residual_started = time.perf_counter()
                            child_search_state = parent_state.branch(
                                wall_candidate, state_id, remaining,
                                support_state={
                                    "placement_count": len(world_state.placements),
                                    "new_support_ratios": support_ratios,
                                    "minimum_support_ratio": support_margin,
                                },
                                load_state={
                                    "is_valid": bool(physics and physics["load_report"].is_valid),
                                    "total_weight_kg": physics["load_report"].total_cargo_weight_kg if physics else world_state.total_weight_kg,
                                    "compression_violations": list(physics["compression_violations"]) if physics else [],
                                },
                                stability_state={
                                    "is_valid": bool(physics and physics["is_valid"]),
                                    "violations": list(physics["stability_violations"]) if physics else [],
                                },
                                residual_space={
                                    "remaining_x": max(0.0, self.container.Lx - world_state.max_x),
                                    "container_residual_volume": max(0.0, self.container.volume - sum(p.volume for p in world_state.placements)),
                                },
                                top_fill_potential=topfill,
                                door_state={
                                    "safe_x": self.container.Lx - zone_mgr.door_zone_length_m,
                                    "candidate_max_x": max(p.max_x for p in child_placements),
                                    "at_risk": objective.door_penalty > 0.0,
                                },
                                objective=objective,
                            )
                            self._record_profile(
                                "residual_space_update_ms", (time.perf_counter() - residual_started) * 1000.0,
                            )
                            # Phase is part of the immutable branch snapshot.
                            # Crossing the authoritative transition frontier
                            # changes later candidate selection/door risk
                            # semantics without invoking a second greedy fill.
                            if child_search_state.current_x >= zone_mgr.transition_start_x:
                                child_search_state.phase = "TRANSITION"
                            perf["state_clone_ms"] += (time.perf_counter() - clone_started) * 1000.0
                            perf["state_clone_calls"] += 1
                            score = objective.final_score
                            wall_tel = self.telemetry["wall_plan_search"]
                            wall_tel["states_generated"] += 1
                            wall_tel["max_depth"] = max(wall_tel["max_depth"], child_search_state.depth)
                            wall_tel["objective_values"].append(objective.final_score)
                            wall_tel["search_trace"].append({
                                "state_id": child_search_state.state_id,
                                "parent_state": parent_state.state_id,
                                "selected_candidate": wall_candidate.to_dict(),
                                "candidate_family": agg.candidate_family,
                                "candidate_signature": json.loads(agg.candidate_signature) if agg.candidate_signature else {},
                                "score_breakdown": objective.to_dict(),
                                "hard_constraint_state": {"is_valid": True, "violations": []},
                                "status": "CANDIDATE_VALID",
                            })
                            if diversity_diag is not None:
                                signature = self.diverse_wall_generator.signature_for(agg)
                                diversity_diag["valid_candidates"] += 1
                                diversity_diag["valid_signatures"].append(signature.to_dict())
                                diversity_diag["scores"].append(objective.final_score)
                                self._increment_diversity(diversity_diag, agg, signature)

                        elif self.config.wall_plan_search_mode == GLOBAL_SEARCH and node.search_state is not None:
                            child_search_state = node.search_state.clone(
                                state_id=f"{node.search_state.state_id}/{context.value}_{agg.candidate_id}",
                            )
                            child_search_state.placements = copy.deepcopy(node.placements + child_placements)
                            child_search_state.current_x = max(
                                child_search_state.current_x,
                                max((p.max_x for p in child_placements), default=child_search_state.current_x),
                            )
                            child_search_state.phase = (
                                "TRANSITION" if context == PlacementContext.GAP_FILL else
                                "TOP_FILL" if context == PlacementContext.TOP_FILL else
                                "DOOR" if context == PlacementContext.DOOR_SEAL else child_search_state.phase
                            )

                        new_placed_qty = dict(node.placed_quantities)
                        for sid, count in composition.items():
                            new_placed_qty[sid] = new_placed_qty.get(sid, 0) + count

                        # Track X advancement for Watchdog
                        cand_max_x = max([p.max_x for p in child_placements], default=node.last_max_x)
                        advancement = cand_max_x - node.last_max_x
                        new_stall_count = 0 if advancement > 0.05 else node.stall_count + 1
                        new_max_x = max(node.last_max_x, cand_max_x)

                        child_node = BeamNode(
                            node_id=f"node_{node.depth + 1}_{len(expansion_candidates)}",
                            placements=node.placements + child_placements,
                            placed_quantities=new_placed_qty,
                            cumulative_score=node.cumulative_score + score,
                            total_volume=node.total_volume + agg.total_volume,
                            total_weight_kg=node.total_weight_kg + agg.total_weight_kg,
                            depth=node.depth + 1,
                            phase_idx=phase_idx,
                            parent_id=node.node_id,
                            last_max_x=new_max_x,
                            stall_count=new_stall_count,
                            search_state=child_search_state,
                        )
                        branch_children.append((score, child_node))

                    if not all_valid and diversity_diag is not None:
                        diversity_diag["hard_rejected"] += 1
                    for delta in reversed(committed_deltas):
                        world_state.rollback(delta)
                    if context == PlacementContext.MAIN_WALL and self.config.wall_plan_search_mode == GLOBAL_SEARCH:
                        perf = self.telemetry["wall_plan_search"]["performance"]
                        perf["hard_validation_ms"] += (time.perf_counter() - validation_started) * 1000.0
                        perf["hard_validation_calls"] += 1

                if diversity_diag is not None:
                    scores = diversity_diag.pop("scores")
                    diversity_diag["structurally_distinct_valid_candidates"] = len({
                        json.dumps(item, sort_keys=True) for item in diversity_diag["valid_signatures"]
                    })
                    diversity_diag["score_min"] = min(scores) if scores else None
                    diversity_diag["score_max"] = max(scores) if scores else None
                    diversity_diag["score_mean"] = sum(scores) / len(scores) if scores else None
                    diversity_diag["score_std"] = (
                        math.sqrt(sum((value - diversity_diag["score_mean"]) ** 2 for value in scores) / len(scores))
                        if scores else None
                    )

                if branch_children:
                    progress_made = True
                    # Rank branch children by volume gain + score + X advancement
                    ranking_started = time.perf_counter()
                    if context == PlacementContext.MAIN_WALL and self.config.wall_plan_search_mode == GLOBAL_SEARCH:
                        branch_children.sort(
                            key=lambda item: (item[0], item[1].total_volume, item[1].last_max_x, item[1].search_state.state_id),
                            reverse=True,
                        )
                    else:
                        branch_children.sort(
                            key=lambda item: (item[1].total_volume, item[1].last_max_x, item[0]),
                            reverse=True,
                        )
                    self._record_profile(
                        "candidate_ranking_ms", (time.perf_counter() - ranking_started) * 1000.0,
                    )
                    top_children = [child for _, child in branch_children[: self.config.beam_width]]
                    if context == PlacementContext.MAIN_WALL and self.config.wall_plan_search_mode == GLOBAL_SEARCH:
                        selected_ids = {child.search_state.state_id for child in top_children if child.search_state is not None}
                        self.telemetry["wall_plan_search"]["search_trace"].append({
                            "parent_state": node.search_state.state_id if node.search_state else node.node_id,
                            "selected_states": sorted(selected_ids),
                            "rejected_by_beam": sorted(
                                child.search_state.state_id for _, child in branch_children
                                if child.search_state is not None and child.search_state.state_id not in selected_ids
                            ),
                            "status": "BEAM_SELECTION",
                        })
                    expansion_candidates.extend(top_children)
                else:
                    if context == PlacementContext.MAIN_WALL and self.config.wall_plan_search_mode == GLOBAL_SEARCH:
                        self._record_dead_end("HARD_CONSTRAINT_DEAD_END")
                    expansion_candidates.append(node)

                if context == PlacementContext.MAIN_WALL and self.config.wall_plan_search_mode == GLOBAL_SEARCH:
                    perf = self.telemetry["wall_plan_search"]["performance"]
                    expansion_elapsed_ms = (time.perf_counter() - node_expansion_started) * 1000.0
                    perf["state_expansion_ms"] += expansion_elapsed_ms
                    perf["state_expansion_calls"] += 1
                    self._record_profile("state_expansion_inclusive_ms", expansion_elapsed_ms)

            if not progress_made:
                self.telemetry["phase_termination_reason"][phase_name] = f"SATURATED_OR_NO_CANDIDATES"
                break

            # Prune overall expansion candidates to bounded beam_width prioritizing Volume & X Progression
            if context == PlacementContext.MAIN_WALL and self.config.wall_plan_search_mode == GLOBAL_SEARCH:
                expansion_candidates.sort(
                    key=lambda n: (n.cumulative_score, n.total_volume, n.last_max_x, n.search_state.state_id if n.search_state else n.node_id),
                    reverse=True,
                )
            else:
                expansion_candidates.sort(
                    key=lambda n: (n.total_volume, n.last_max_x, n.cumulative_score, n.placed_count),
                    reverse=True,
                )
            unique_nodes: List[BeamNode] = []
            if context == PlacementContext.MAIN_WALL and self.config.wall_plan_search_mode == GLOBAL_SEARCH:
                pruned = self._prune_global_states(expansion_candidates)
                diversity_counts: Counter = Counter()
                for cand_node in pruned:
                    if cand_node.search_state is None:
                        continue
                    key = beam_diversity_key(cand_node.search_state)
                    if diversity_counts[key] >= self.config.global_beam_diversity_per_key:
                        continue
                    diversity_counts[key] += 1
                    unique_nodes.append(cand_node)
                    if len(unique_nodes) >= self.config.beam_width:
                        break
                self.telemetry["wall_plan_search"]["beam_pruned"] += max(0, len(pruned) - len(unique_nodes))
            else:
                seen_keys: Set[Tuple[int, int]] = set()
                for cand_node in expansion_candidates:
                    key = (int(cand_node.total_volume * 10), int(cand_node.last_max_x * 10))
                    if key not in seen_keys:
                        seen_keys.add(key)
                        unique_nodes.append(cand_node)
                    if len(unique_nodes) >= self.config.beam_width:
                        break

            active_nodes = unique_nodes if unique_nodes else expansion_candidates[: self.config.beam_width]

        return active_nodes

    def _synchronized_search_state(
        self,
        node: BeamNode,
        qty_mgr: QuantityManager,
        world_state: WorldState,
        child_placements: List[Placement],
    ) -> SearchState:
        """Create an isolated parent snapshot at the exact pre-candidate boundary."""
        state = (node.search_state or root_search_state(self.cargo_list)).clone(
            state_id=(node.search_state.state_id if node.search_state else node.node_id),
            parent_state=(node.search_state.parent_state if node.search_state else node.parent_id),
        )
        state.current_x = node.last_max_x
        state.placed_volume = node.total_volume
        state.placements = copy.deepcopy(list(node.placements))
        state.remaining_inventory = {
            sid: qty_mgr.get_remaining(sid, PlacementContext.MAIN_WALL)
            for sid in self.sku_catalog
        }
        state.depth = node.search_state.depth if node.search_state is not None else 0
        return state

    def _global_budget_reached(self) -> bool:
        telemetry = self.telemetry["wall_plan_search"]
        if time.perf_counter() - self._global_started >= self.config.global_runtime_budget_sec:
            telemetry["budget_stop_reason"] = "RUNTIME_STOP"
            return True
        if telemetry["states_generated"] >= self.config.global_max_states_generated:
            telemetry["budget_stop_reason"] = "STATE_BUDGET_STOP"
            return True
        if telemetry["states_expanded"] >= self.config.global_max_states_expanded:
            telemetry["budget_stop_reason"] = "STATE_BUDGET_STOP"
            return True
        return False

    def _record_dead_end(self, code: str) -> None:
        dead = self.telemetry["wall_plan_search"]["dead_end_states"]
        dead[code] = dead.get(code, 0) + 1

    def _prune_global_states(self, nodes: List[BeamNode]) -> List[BeamNode]:
        """Exact signature dedup followed by conservative comparable dominance."""
        telemetry = self.telemetry["wall_plan_search"]
        deduped: List[BeamNode] = []
        signatures: Set[Tuple[Any, ...]] = set()
        for node in nodes:
            if node.search_state is None:
                deduped.append(node)
                continue
            signature_started = time.perf_counter()
            key = SearchStateSignature.from_state(node.search_state).key()
            self._record_profile(
                "state_signature_ms", (time.perf_counter() - signature_started) * 1000.0,
            )
            if key in signatures:
                telemetry["duplicate_states_removed"] += 1
                continue
            signatures.add(key)
            deduped.append(node)

        dominance_started = time.perf_counter()
        kept: List[BeamNode] = []
        for candidate in deduped:
            if candidate.search_state is None:
                kept.append(candidate)
                continue
            dominated = False
            for other in deduped:
                if other is candidate or other.search_state is None:
                    continue
                a, b = other.search_state, candidate.search_state
                if a.phase != b.phase or a.remaining_inventory != b.remaining_inventory:
                    continue
                a_top = float(a.top_fill_potential.get("packable_volume_estimate", 0.0))
                b_top = float(b.top_fill_potential.get("packable_volume_estimate", 0.0))
                a_res = float(a.score_components.get("residual_quality", 0.0))
                b_res = float(b.score_components.get("residual_quality", 0.0))
                a_door = float(a.score_components.get("door_penalty", 0.0))
                b_door = float(b.score_components.get("door_penalty", 0.0))
                weak = (
                    a.current_x >= b.current_x and a.placed_volume >= b.placed_volume
                    and a_top >= b_top and a_res >= b_res and a_door <= b_door
                )
                strict = (
                    a.current_x > b.current_x or a.placed_volume > b.placed_volume
                    or a_top > b_top or a_res > b_res or a_door < b_door
                )
                if weak and strict:
                    dominated = True
                    break
            if dominated:
                telemetry["dominated_states_removed"] += 1
            else:
                kept.append(candidate)
        self._record_profile(
            "dominance_check_ms", (time.perf_counter() - dominance_started) * 1000.0,
        )
        return kept

    def _candidate_cavity_gate(
        self,
        node: BeamNode,
        candidate: AggregateCandidate,
        world_state: WorldState,
        zone_mgr: AdaptiveZoneManager,
    ) -> Tuple[bool, str]:
        """Topological frontier proof, with full classifier fallback off-frontier."""
        eps = world_state.geom_epsilon
        door_safe_x = self.container.Lx - zone_mgr.door_zone_length_m
        is_frontier_open = (
            candidate.bounding_box.min_x >= node.last_max_x - 0.30 - eps
            and candidate.bounding_box.max_x <= door_safe_x + eps
            and candidate.bounding_box.max_x < self.container.Lx - eps
        )
        if is_frontier_open:
            # The entire forward half-space remains connected to the door; a
            # frontier append cannot topologically enclose a new void behind it.
            return True, "FRONTIER_OPEN_CAVITY_PROOF"
        cavity = AdvancedCavityClassifier(self.container).classify_cavities(world_state.placements)
        if cavity.enclosed_cavities or cavity.bridge_void_count:
            return False, "CAVITY_OR_BRIDGE"
        return True, "FULL_CAVITY_CHECK_PASS"

    @staticmethod
    def _increment_diversity(
        diagnostics: Dict[str, Any],
        candidate: AggregateCandidate,
        signature: CandidateSignature,
    ) -> None:
        def increment(field: str, key: str) -> None:
            mapping = diagnostics[field]
            mapping[key] = mapping.get(key, 0) + 1

        increment("valid_by_family", candidate.candidate_family)
        for sku_id, _ in signature.sku_composition:
            increment("valid_by_sku", sku_id)
        for orientation, _ in signature.orientation_composition:
            increment("valid_by_orientation", orientation)
        width = signature.wall_width
        if width < 0.5:
            bucket = "LT_0.5M"
        elif width < 1.0:
            bucket = "0.5_TO_1.0M"
        elif width < 2.0:
            bucket = "1.0_TO_2.0M"
        else:
            bucket = "GE_2.0M"
        increment("valid_by_wall_width_bucket", bucket)
        increment("valid_by_layer_count", str(len(signature.layer_structure)))

    def _evaluate_wall_candidate_physics(
        self,
        world_state: WorldState,
        child_placements: List[Placement],
    ) -> Dict[str, Any]:
        """Run existing physical evaluators while reusing the branch's committed graphs."""
        load_report = self.physics_engine.load_engine.compute_loads(
            world_state.support_graph, self.sku_catalog, timing_hook=self._record_profile,
        )
        violations: List[str] = []
        started = time.perf_counter()
        for placement in child_placements:
            report = self.physics_engine.item_evaluator.evaluate_placement(
                placement=placement,
                sku=self.sku_catalog.get(placement.sku_id),
                support_graph=world_state.support_graph,
                contact_graph=world_state.contact_graph,
                container=self.container,
            )
            if not report.is_stable:
                violations.append(f"ITEM:{placement.placement_id}:{';'.join(report.reasons)}")
        self._record_profile("stability_validation_ms", (time.perf_counter() - started) * 1000.0)
        if not load_report.is_valid or violations:
            return {
                "is_valid": False,
                "load_report": load_report,
                "compression_violations": list(load_report.violations),
                "stability_violations": violations,
            }
        started = time.perf_counter()
        cluster_reports = self.physics_engine.cluster_evaluator.evaluate_clusters(
            placements=world_state.placements,
            contact_graph=world_state.contact_graph,
            container=self.container,
        )
        child_ids = {p.placement_id for p in child_placements}
        for report in cluster_reports:
            if not report.is_stable and child_ids.intersection(report.placement_ids):
                violations.append(f"CLUSTER:{report.cluster_id}:{';'.join(report.reasons)}")
        self._record_profile("cluster_stability_ms", (time.perf_counter() - started) * 1000.0)
        started = time.perf_counter()
        wall_reports = self.physics_engine.wall_evaluator.evaluate_walls(
            placements=world_state.placements,
            contact_graph=world_state.contact_graph,
            container=self.container,
        )
        for report in wall_reports:
            if not report.is_stable and child_ids.intersection(report.placement_ids):
                violations.append(f"WALL:{report.wall_id}:{';'.join(report.reasons)}")
        self._record_profile("wall_stability_ms", (time.perf_counter() - started) * 1000.0)
        return {
            "is_valid": load_report.is_valid and not violations,
            "load_report": load_report,
            "compression_violations": list(load_report.violations),
            "stability_violations": violations,
        }

    def _trace_wall_rejection(self, node: BeamNode, candidate_id: str, reason: str) -> None:
        wall_tel = self.telemetry["wall_plan_search"]
        wall_tel["candidates_rejected"] += 1
        wall_tel["search_trace"].append({
            "parent_state": node.search_state.state_id if node.search_state else node.node_id,
            "candidate_id": candidate_id,
            "status": "HARD_REJECTED",
            "rejection_reason": reason,
        })

    def _reconstruct_state(
        self,
        node: BeamNode,
    ) -> Tuple[WorldState, FreeSpaceEngine, AdaptiveZoneManager, QuantityManager, SpatialReservationManager]:
        """
        Reconstructs execution engines and applies the node's placements.
        """
        world_state = WorldState(container=self.container, cargo_catalog=self.cargo_list)
        space_engine = FreeSpaceEngine(container=self.container, grid_resolution=self.config.grid_resolution)
        zone_mgr = AdaptiveZoneManager(container=self.container)
        qty_mgr = QuantityManager(cargo_list=self.cargo_list)
        res_mgr = SpatialReservationManager()

        qty_mgr.set_door_reserve_allocations(self.elastic_frontier.allocations)
        zone_mgr.adapt_door_zone_to_cargo(self.door_seal_skus)
        res_mgr.reserve_door_zone(self.container, door_zone_length_m=zone_mgr.door_zone_length_m)

        for p in node.placements:
            world_state.commit(p)
            if self.config.wall_plan_search_mode != GLOBAL_SEARCH:
                space_engine.on_placement_replayed(p)
            qty_mgr.record_placement(p.sku_id, context=p.context)
        if self.config.wall_plan_search_mode == GLOBAL_SEARCH:
            space_engine.rebuild_frontier_view(node.placements)

        return world_state, space_engine, zone_mgr, qty_mgr, res_mgr

    def _get_phase_skus(
        self,
        qty_mgr: QuantityManager,
        context: PlacementContext,
        priority_order: Optional[List[str]] = None,
    ) -> List[CargoSKU]:
        """Filters remaining eligible SKUs for the given phase context."""
        unfilled = qty_mgr.get_sku_priorities(context=context)
        door_sku_ids = {s.sku_id for s in self.door_seal_skus}

        if context == PlacementContext.DOOR_SEAL:
            # In DOOR_SEAL phase, strictly prioritize door seal SKUs first
            ordered = [sid for sid in unfilled if sid in door_sku_ids] + [sid for sid in unfilled if sid not in door_sku_ids]
        elif context in (PlacementContext.FOUNDATION, PlacementContext.MAIN_WALL):
            if priority_order:
                non_door_prio = [sid for sid in priority_order if sid in unfilled and sid not in door_sku_ids]
                door_prio = [sid for sid in priority_order if sid in unfilled and sid in door_sku_ids]
                remaining_other = [sid for sid in unfilled if sid not in priority_order]
                ordered = non_door_prio + door_prio + remaining_other
            else:
                ordered = unfilled
        else:
            if priority_order:
                ordered = [sid for sid in priority_order if sid in unfilled] + [sid for sid in unfilled if sid not in priority_order]
            else:
                ordered = unfilled

        phase_skus = []
        for sid in ordered:
            sku = self.sku_catalog[sid]
            if context == PlacementContext.FOUNDATION:
                if (PackingRole.FOUNDATION in sku.packing_roles or
                    sku.stacking_policy.must_be_on_floor or
                    sku.cargo_class.value == "HEAVY"):
                    phase_skus.append(sku)
            elif context == PlacementContext.MAIN_WALL:
                # In MAIN_WALL: only include MAIN_WALL, FLEXIBLE, or DOOR_SEAL with excess
                if PackingRole.MAIN_WALL in sku.packing_roles or PackingRole.FLEXIBLE in sku.packing_roles or PackingRole.DOOR_SEAL in sku.packing_roles:
                    phase_skus.append(sku)
            elif context == PlacementContext.GAP_FILL:
                phase_skus.append(sku)
            elif context == PlacementContext.TOP_FILL:
                if PackingRole.TOP_FILL in sku.packing_roles or sku.orientation_policy.allow_flat:
                    phase_skus.append(sku)
            elif context == PlacementContext.DOOR_SEAL:
                phase_skus.append(sku)

        if not phase_skus and context in (PlacementContext.MAIN_WALL, PlacementContext.GAP_FILL, PlacementContext.TOP_FILL):
            phase_skus = [self.sku_catalog[sid] for sid in ordered]

        return phase_skus

    @staticmethod
    def _is_better_node(a: BeamNode, b: BeamNode) -> bool:
        """
        Determines if node A is strictly superior to node B based on Search Objective:
        1. Total Cargo Volume (primary metric)
        2. Longitudinal X progression (farthest forward advancement)
        3. Cumulative Score
        4. Placed Count (tie-breaker)
        """
        # Primary: Total Volume (0.05 m3 tolerance)
        if a.total_volume > b.total_volume + 0.05:
            return True
        if b.total_volume > a.total_volume + 0.05:
            return False

        # Secondary: X Advancement (0.10 m tolerance)
        if a.last_max_x > b.last_max_x + 0.10:
            return True
        if b.last_max_x > a.last_max_x + 0.10:
            return False

        # Tertiary: Cumulative Score
        if a.cumulative_score > b.cumulative_score + 1.0:
            return True
        if b.cumulative_score > a.cumulative_score + 1.0:
            return False

        # Lowest Tie-breaker: Placed Count
        return a.placed_count > b.placed_count
