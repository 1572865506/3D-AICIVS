"""
Baseline Greedy Solver for Solver V2 (Agent 05 / BLK-002).
Implements a clean-room phase-aware greedy packer:
- Phase 1: FOUNDATION (floor base layers)
- Phase 2: MAIN_WALL (upright body from rear to door safe limit)
- Phase 3: GAP_FILL / TRANSITION (smoothing and wall base preparation)
- Phase 4: TOP_FILL (headspace fill, conditional flat permitted)
- Phase 5: DOOR_SEAL (continuous door closure from existing wall surface)

Features:
- ElasticDoorFrontier integration: no static 4.8m lockout, continuous cooperative packing
- Door Reserve Pool vs Door Excess separation
- Category-aware candidate anchor scheduling
- Cheap support pre-filter to prevent candidate starvation
- Deterministic random seed
- Atomicity: Candidate -> Hard Gate -> Residual Score -> Atomic Commit
- Comprehensive Telemetry with granular rejection & termination diagnostics
- Independent Validation Integration (Agent 06)
"""
import time
import random
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any

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
from backend.solver_v2.spaces.types import AnchorCategory
from backend.solver_v2.world.state import WorldState
from backend.solver_v2.spaces.engine import FreeSpaceEngine
from backend.solver_v2.orientation.manager import OrientationEngine
from backend.solver_v2.zones.manager import AdaptiveZoneManager
from backend.solver_v2.quantity.manager import QuantityManager, SpatialReservationManager
from backend.solver_v2.candidates.generator import CandidateGenerator, CandidatePlacement, CandidateBudget
from backend.solver_v2.feasibility.pipeline import HardValidationPipeline
from backend.solver_v2.solver.scorer import CandidateScorer
from backend.solver_v2.door.elastic_frontier import ElasticDoorFrontier
from backend.solver_v2.door.closure_planner import DoorClosurePlanner, DoorReadinessReport
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from backend.solver_v2.validation.types import ValidationResult
from backend.solver_v2.topfill.planner import TopFillPlanner
from backend.solver_v2.stability.tipping_moment import TippingMomentAnalyzer


@dataclass
class SolverTelemetry:
    """Telemetry report for solver execution with detailed anchor & candidate metrics."""
    runtime_ms: float = 0.0
    candidates_generated: int = 0
    candidates_evaluated: int = 0
    candidates_rejected_by_reason: Dict[str, int] = field(default_factory=dict)
    anchors_generated_by_type: Dict[str, int] = field(default_factory=dict)
    anchors_sampled_by_type: Dict[str, int] = field(default_factory=dict)
    candidates_generated_by_anchor_type: Dict[str, int] = field(default_factory=dict)
    candidates_valid_by_anchor_type: Dict[str, int] = field(default_factory=dict)
    floor_frontier_count: int = 0
    supported_frontier_count: int = 0
    wall_frontier_count: int = 0
    no_candidate_reason: str = ""
    phase_termination_reason: Dict[str, str] = field(default_factory=dict)
    ems_peak: int = 0
    extreme_points_peak: int = 0
    steps_committed: int = 0
    phases_completed: List[str] = field(default_factory=list)
    door_readiness: Optional[Dict[str, Any]] = None
    top_fill_metrics: Optional[Dict[str, Any]] = None
    wall_plan_search_metrics: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "runtime_ms": round(self.runtime_ms, 2),
            "candidates_generated": self.candidates_generated,
            "candidates_evaluated": self.candidates_evaluated,
            "candidates_rejected_by_reason": self.candidates_rejected_by_reason,
            "anchors_generated_by_type": self.anchors_generated_by_type,
            "anchors_sampled_by_type": self.anchors_sampled_by_type,
            "candidates_generated_by_anchor_type": self.candidates_generated_by_anchor_type,
            "candidates_valid_by_anchor_type": self.candidates_valid_by_anchor_type,
            "floor_frontier_count": self.floor_frontier_count,
            "supported_frontier_count": self.supported_frontier_count,
            "wall_frontier_count": self.wall_frontier_count,
            "no_candidate_reason": self.no_candidate_reason,
            "phase_termination_reason": self.phase_termination_reason,
            "ems_peak": self.ems_peak,
            "extreme_points_peak": self.extreme_points_peak,
            "steps_committed": self.steps_committed,
            "phases_completed": self.phases_completed,
            "door_readiness": self.door_readiness,
            "top_fill_metrics": self.top_fill_metrics,
            "wall_plan_search_metrics": self.wall_plan_search_metrics,
        }


@dataclass
class SolverSolution:
    """Complete solution output produced by BaselineGreedySolver."""
    status: str
    container: ContainerSpec
    placements: List[Placement]
    placed_count: int
    unplaced_count: int
    volume_utilization_pct: float
    total_weight_kg: float
    validation_result: ValidationResult
    telemetry: SolverTelemetry

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "placed_count": self.placed_count,
            "unplaced_count": self.unplaced_count,
            "volume_utilization_pct": round(self.volume_utilization_pct, 4),
            "total_weight_kg": round(self.total_weight_kg, 2),
            "is_valid": self.validation_result.is_valid,
            "rejection_reasons": self.validation_result.rejection_reasons,
            "telemetry": self.telemetry.to_dict(),
            "placements": [
                {
                    "placement_id": p.placement_id,
                    "sku_id": p.sku_id,
                    "x": p.position.x,
                    "y": p.position.y,
                    "z": p.position.z,
                    "dx": p.orientation.dx,
                    "dy": p.orientation.dy,
                    "dz": p.orientation.dz,
                    "weight_kg": p.weight_kg,
                    "context": p.context.value,
                }
                for p in self.placements
            ],
        }


class BaselineGreedySolver:
    """
    Greedy baseline solver for Solver V2.
    """

    def __init__(
        self,
        seed: int = 42,
        grid_resolution: float = 0.2,
        max_candidates_per_step: int = 300,
        scorer: Optional[CandidateScorer] = None,
        validator_pipeline: Optional[HardValidationPipeline] = None,
    ):
        self.seed = seed
        self.grid_resolution = grid_resolution
        self.max_candidates_per_step = max_candidates_per_step
        self.scorer = scorer
        self.validator_pipeline = validator_pipeline

    def solve(
        self,
        container: ContainerSpec,
        cargo_list: List[CargoSKU],
        options: Optional[Dict[str, Any]] = None,
    ) -> SolverSolution:
        """
        Executes phased baseline packing with ElasticDoorFrontier.
        """
        random.seed(self.seed)
        t0 = time.perf_counter()

        telemetry = SolverTelemetry()

        # 1. Initialize State, Engines, and ElasticDoorFrontier
        world_state = WorldState(container=container, cargo_catalog=cargo_list)
        space_engine = FreeSpaceEngine(container=container, grid_resolution=self.grid_resolution)
        orientation_engine = OrientationEngine()
        zone_mgr = AdaptiveZoneManager(container=container)
        qty_mgr = QuantityManager(cargo_list=cargo_list)
        res_mgr = SpatialReservationManager()
        candidate_gen = CandidateGenerator()
        validator_pipeline = self.validator_pipeline if self.validator_pipeline is not None else HardValidationPipeline()
        scorer = self.scorer if self.scorer is not None else CandidateScorer()
        topfill_planner = TopFillPlanner(container, orientation_engine=orientation_engine)

        door_seal_skus = [s for s in cargo_list if PackingRole.DOOR_SEAL in s.packing_roles or s.target_zone == ZoneType.DOOR]
        elastic_frontier = ElasticDoorFrontier(container=container, door_skus=door_seal_skus)
        qty_mgr.set_door_reserve_allocations(elastic_frontier.allocations)
        zone_mgr.adapt_door_zone_to_cargo(door_seal_skus)
        res_mgr.reserve_door_zone(container, door_zone_length_m=zone_mgr.door_zone_length_m)

        sku_catalog = {s.sku_id: s for s in cargo_list}

        # 2. Phased Packing Execution
        phases = [
            (PlacementContext.FOUNDATION, "Phase 1: Foundation (Floor)"),
            (PlacementContext.MAIN_WALL, "Phase 2: Main Walls (Body)"),
            (PlacementContext.GAP_FILL, "Phase 3: Transition (Smoothing & Base Preparation)"),
            (PlacementContext.TOP_FILL, "Phase 4: Top Fill (Headspace)"),
            (PlacementContext.DOOR_SEAL, "Phase 5: Door Seal Closure"),
        ]

        step_idx = 0

        for context, phase_name in phases:
            # During Door Seal phase, release door zone spatial reservation
            if context == PlacementContext.DOOR_SEAL:
                for r in res_mgr._reservations.values():
                    if r.reservation_id == "DOOR_ZONE_RESERVATION":
                        r.is_active = False

            phase_progress = True
            while phase_progress:
                # Find available SKUs for current context
                eligible_sku_ids = qty_mgr.get_sku_priorities(context=context)
                if not eligible_sku_ids:
                    telemetry.phase_termination_reason[phase_name] = "ALL_SKUS_COMPLETED"
                    break

                # Filter SKUs fitting current phase context
                phase_skus = []
                for sid in eligible_sku_ids:
                    sku = sku_catalog[sid]
                    if context == PlacementContext.FOUNDATION:
                        if (PackingRole.FOUNDATION in sku.packing_roles or
                            sku.stacking_policy.must_be_on_floor or
                            sku.cargo_class.value == "HEAVY"):
                            phase_skus.append(sku)
                    elif context == PlacementContext.MAIN_WALL:
                        if PackingRole.MAIN_WALL in sku.packing_roles or PackingRole.FLEXIBLE in sku.packing_roles or PackingRole.DOOR_SEAL in sku.packing_roles:
                            phase_skus.append(sku)
                    elif context == PlacementContext.GAP_FILL:
                        phase_skus.append(sku)
                    elif context == PlacementContext.TOP_FILL:
                        if PackingRole.TOP_FILL in sku.packing_roles or sku.orientation_policy.allow_flat:
                            phase_skus.append(sku)
                    elif context == PlacementContext.DOOR_SEAL:
                        phase_skus.append(sku)

                if not phase_skus:
                    # In main wall / gap fill / top fill, fallback to any eligible SKU
                    if context in (PlacementContext.MAIN_WALL, PlacementContext.GAP_FILL, PlacementContext.TOP_FILL):
                        phase_skus = [sku_catalog[sid] for sid in eligible_sku_ids]
                    else:
                        telemetry.phase_termination_reason[phase_name] = "NO_ELIGIBLE_SKUS_FOR_PHASE"
                        break

                # Generate candidates with category-aware budget
                budget = CandidateBudget.from_total(self.max_candidates_per_step)
                candidates = candidate_gen.generate_candidates(
                    world_state=world_state,
                    space_engine=space_engine,
                    orientation_engine=orientation_engine,
                    zone_mgr=zone_mgr,
                    qty_mgr=qty_mgr,
                    active_skus=phase_skus,
                    context=context,
                    max_candidates=self.max_candidates_per_step,
                    budget=budget,
                )

                # Merge generator telemetry
                gen_telem = candidate_gen.last_telemetry
                for k, v in gen_telem.get("anchors_generated_by_type", {}).items():
                    telemetry.anchors_generated_by_type[k] = telemetry.anchors_generated_by_type.get(k, 0) + v
                for k, v in gen_telem.get("anchors_sampled_by_type", {}).items():
                    telemetry.anchors_sampled_by_type[k] = telemetry.anchors_sampled_by_type.get(k, 0) + v
                for k, v in gen_telem.get("candidates_generated_by_anchor_type", {}).items():
                    telemetry.candidates_generated_by_anchor_type[k] = telemetry.candidates_generated_by_anchor_type.get(k, 0) + v
                telemetry.floor_frontier_count = max(telemetry.floor_frontier_count, gen_telem.get("floor_frontier_count", 0))
                telemetry.supported_frontier_count = max(telemetry.supported_frontier_count, gen_telem.get("supported_frontier_count", 0))
                telemetry.wall_frontier_count = max(telemetry.wall_frontier_count, gen_telem.get("wall_frontier_count", 0))

                telemetry.candidates_generated += len(candidates)
                if not candidates:
                    telemetry.no_candidate_reason = "NO_CANDIDATES_GENERATED_BY_GENERATOR"
                    telemetry.phase_termination_reason[phase_name] = "NO_CANDIDATE_FOR_PHASE"
                    phase_progress = False
                    break

                # Filter and Score Candidates
                valid_scored_candidates: List[Tuple[float, CandidatePlacement, CargoSKU]] = []
                topfill_regions = {
                    r.region_id: r for r in topfill_planner.extract_top_fill_regions(world_state, sku_catalog)
                } if context == PlacementContext.TOP_FILL else {}

                for cand in candidates:
                    sku = sku_catalog[cand.sku_id]
                    telemetry.candidates_evaluated += 1

                    is_valid, _ = validator_pipeline.is_feasible(
                        candidate=cand,
                        sku=sku,
                        world_state=world_state,
                        zone_mgr=zone_mgr,
                        res_mgr=res_mgr,
                        elastic_frontier=elastic_frontier,
                        context=context,
                    )
                    if not is_valid:
                        continue
                    if context == PlacementContext.TOP_FILL:
                        region = topfill_regions.get(cand.topfill_region_id or "")
                        if region is None:
                            validator_pipeline.rejection_counts["TOP_FILL_REGION_REQUIRED"] += 1
                            continue
                        top_eval = topfill_planner.evaluate_topfill_candidate(
                            cand, sku, region, world_state, sku_catalog, zone_mgr,
                        )
                        if not top_eval.is_valid:
                            key = (
                                "TOP_FILL_INSUFFICIENT_SUPPORT" if not top_eval.support_passed else
                                "TOP_FILL_COMPRESSION" if not top_eval.compression_passed else
                                "TOP_FILL_ORIENTATION_CONTEXT" if not top_eval.orientation_context_passed else
                                "TOP_FILL_MAX_LAYERS" if not top_eval.layer_limit_passed else
                                "TOP_FILL_STABILITY"
                            )
                            validator_pipeline.rejection_counts[key] += 1
                            continue

                    score = scorer.score_candidate(
                        candidate=cand,
                        sku=sku,
                        world_state=world_state,
                        space_engine=space_engine,
                        zone_mgr=zone_mgr,
                        remaining_skus=phase_skus,
                        elastic_frontier=elastic_frontier,
                        context=context,
                    )
                    valid_scored_candidates.append((score, cand, sku))
                    cat_name = cand.anchor_category.value if hasattr(cand.anchor_category, "value") else str(cand.anchor_category)
                    telemetry.candidates_valid_by_anchor_type[cat_name] = telemetry.candidates_valid_by_anchor_type.get(cat_name, 0) + 1

                if not valid_scored_candidates:
                    telemetry.no_candidate_reason = "ALL_CANDIDATES_REJECTED_BY_VALIDATION"
                    telemetry.phase_termination_reason[phase_name] = f"NO_VALID_CANDIDATE_FOR_PHASE(tested={len(candidates)})"
                    phase_progress = False
                    break

                # Sort by score descending and select best
                valid_scored_candidates.sort(key=lambda item: item[0], reverse=True)
                best_score, best_cand, best_sku = valid_scored_candidates[0]

                # Convert to Placement and Commit
                placement_id = f"p_{step_idx:04d}_{best_sku.sku_id}"
                instance_id = f"inst_{step_idx:04d}"
                placement = best_cand.to_placement(
                    placement_id=placement_id,
                    instance_id=instance_id,
                    step_index=step_idx,
                )

                world_state.commit(placement)
                space_engine.on_placement_committed(placement, phase_skus)
                qty_mgr.record_placement(best_sku.sku_id, context=context)

                step_idx += 1
                telemetry.steps_committed += 1
                telemetry.ems_peak = max(telemetry.ems_peak, len(space_engine.ems_spaces))
                telemetry.extreme_points_peak = max(telemetry.extreme_points_peak, len(space_engine.extreme_points))

            telemetry.phases_completed.append(phase_name)

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        telemetry.runtime_ms = elapsed_ms
        telemetry.candidates_rejected_by_reason = dict(validator_pipeline.rejection_counts)

        # 3. Door Deployment & Readiness Evaluation
        door_planner = DoorClosurePlanner(container=container, frontier=elastic_frontier)
        deploy_res = door_planner.deploy_door_seal(
            world_state=world_state,
            space_engine=space_engine,
            qty_mgr=qty_mgr,
            door_seal_skus=door_seal_skus,
        )
        final_placements = world_state.placements
        readiness_rep = door_planner.evaluate_door_readiness(
            final_placements,
            reserve_deployed=qty_mgr.get_reserve_deployed(),
            has_door_reserve_pool=(qty_mgr.get_reserve_requested() > 0),
        )
        telemetry.door_readiness = {
            "is_door_ready": readiness_rep.is_door_ready,
            "door_clearance_margin_m": readiness_rep.door_clearance_margin_m,
            "door_zone_occupancy": readiness_rep.door_zone_occupancy,
            "door_closure_coverage": readiness_rep.door_closure_coverage,
            "largest_door_gap": readiness_rep.largest_door_gap,
            "door_wall_flatness": readiness_rep.door_wall_flatness,
            "anti_toppling_stable_ratio": readiness_rep.anti_toppling_stable_ratio,
            "door_readiness_score": readiness_rep.door_readiness_score,
            "reached_transition_zone": readiness_rep.reached_transition_zone,
            "reached_door_closure_zone": readiness_rep.reached_door_closure_zone,
            "reserve_deployed": readiness_rep.reserve_deployed,
            "authoritative_transition_start_x": readiness_rep.authoritative_transition_start_x,
            "authoritative_door_start_x": readiness_rep.authoritative_door_start_x,
            "boundary_source": readiness_rep.boundary_source,
            "rejection_reasons": list(readiness_rep.rejection_reasons),
            "door_deployment_trace": deploy_res.to_dict(),
        }

        # 4. Independent Validation (Agent 06)
        val_result = IndependentGlobalValidator.validate(
            container=container,
            placements=final_placements,
            cargo_list=cargo_list,
        )

        total_req = sum(s.quantity.required for s in cargo_list)
        placed_cnt = len(final_placements)
        unplaced_cnt = max(0, total_req - placed_cnt)

        container_vol = container.volume
        cargo_vol = sum(p.volume for p in final_placements)
        util_pct = (cargo_vol / container_vol * 100.0) if container_vol > 0 else 0.0

        status = "SUCCESS" if (val_result.is_valid and (qty_mgr.all_required_satisfied() or unplaced_cnt == 0)) else (
            "VALID_PARTIAL" if val_result.is_valid else "INVALID"
        )

        return SolverSolution(
            status=status,
            container=container,
            placements=final_placements,
            placed_count=placed_cnt,
            unplaced_count=unplaced_cnt,
            volume_utilization_pct=util_pct,
            total_weight_kg=world_state.total_weight_kg,
            validation_result=val_result,
            telemetry=telemetry,
        )
