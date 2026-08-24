"""
Hierarchical Search Solver for Solver V2 (Agent 09 / BLK-002B).
Orchestrates:
- Multi-start heuristics
- ElasticDoorFrontier & Cooperative Door Closure
- Bounded Beam over Aggregate Structures (Blocks / Layers / Wall Slices)
- Limited Backtracking
- Local Search & Post-Constructive Repair
- Time Budgeting & Anytime Output with Best-so-Far Callbacks
- Search Objective: Hard Validity -> Volume / Space Utilization -> Required Satisfaction -> X Progression -> Carton Count
- Full Multi-Start Telemetry Aggregation
- Independent Global Validation
"""
import copy
import time
import random
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any, Callable

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
from backend.solver_v2.solver.baseline_solver import SolverTelemetry, SolverSolution
from backend.solver_v2.door.elastic_frontier import ElasticDoorFrontier
from backend.solver_v2.door.closure_planner import DoorClosurePlanner, DoorReadinessReport
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from backend.solver_v2.validation.types import ValidationResult

from backend.solver_v2.search.config import SearchConfig, SearchProfile
from backend.solver_v2.search.multi_start import MultiStartManager, MultiStartConfig
from backend.solver_v2.search.beam import BoundedBeamSearchEngine
from backend.solver_v2.search.local_search import LocalSearchOptimizer
from backend.solver_v2.topfill.planner import TopFillPlanner
from backend.solver_v2.topfill.terminal_repair import (
    TerminalRepairConfig, TerminalTopFillRepairOptimizer,
)
from backend.solver_v2.structure.cavity_classifier import AdvancedCavityClassifier


@dataclass
class SearchTelemetry:
    """Detailed telemetry report for Hierarchical Search execution."""
    runtime_ms: float = 0.0
    profile_used: str = ""
    multi_start_runs_executed: int = 0
    best_strategy_name: str = ""
    beam_width_used: int = 0
    aggregate_placements_count: int = 0
    single_placements_count: int = 0
    local_search_repairs: int = 0
    improvements_recorded: int = 0
    time_budget_sec: float = 0.0
    timed_out: bool = False
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
    door_readiness: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "runtime_ms": round(self.runtime_ms, 2),
            "profile_used": self.profile_used,
            "multi_start_runs_executed": self.multi_start_runs_executed,
            "best_strategy_name": self.best_strategy_name,
            "beam_width_used": self.beam_width_used,
            "aggregate_placements_count": self.aggregate_placements_count,
            "single_placements_count": self.single_placements_count,
            "local_search_repairs": self.local_search_repairs,
            "improvements_recorded": self.improvements_recorded,
            "time_budget_sec": self.time_budget_sec,
            "timed_out": self.timed_out,
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
            "door_readiness": self.door_readiness,
        }


class HierarchicalSearchSolver:
    """
    Agent 09 — Hierarchical Search Solver.
    Integrates multi-start, aggregate bounded beam, elastic door frontier, local repair, and anytime best-so-far reporting.
    """

    def __init__(
        self,
        config: Optional[SearchConfig] = None,
        incumbent_solution: Optional[SolverSolution] = None,
    ):
        self.config = config or SearchConfig.for_profile(SearchProfile.BALANCED)
        self.incumbent_solution = incumbent_solution

    def solve(
        self,
        container: ContainerSpec,
        cargo_list: List[CargoSKU],
        options: Optional[Dict[str, Any]] = None,
    ) -> SolverSolution:
        """
        Executes hierarchical multi-start beam search within the configured time budget.
        """
        t_start = time.perf_counter()

        # Parse options override
        cfg = self._resolve_config(options)
        deadline = t_start + cfg.time_budget_sec

        profile_name = cfg.profile.value if hasattr(cfg.profile, "value") else str(cfg.profile)
        telemetry = SearchTelemetry(
            profile_used=profile_name,
            beam_width_used=cfg.beam_width,
            time_budget_sec=cfg.time_budget_sec,
        )

        sku_catalog = {s.sku_id: s for s in cargo_list}
        total_required_items = sum(s.quantity.required for s in cargo_list)
        incumbent = self._validated_incumbent(container, cargo_list)
        if cfg.wall_plan_search_mode == "GLOBAL_SEARCH" and incumbent is not None:
            cfg.global_incumbent_volume_m3 = sum(p.volume for p in incumbent.placements)
            cfg.global_incumbent_utilization_pct = incumbent.volume_utilization_pct

        # 1. Generate Multi-Start Strategies
        strategies = MultiStartManager.generate_strategies(
            cargo_list=cargo_list,
            num_runs=cfg.multi_start_runs,
            base_seed=cfg.seed,
        )

        local_optimizer = LocalSearchOptimizer() if cfg.enable_local_search else None

        best_solution: Optional[SolverSolution] = None
        best_placed_count = -1
        best_volume_util = -1.0
        best_score = -float("inf")

        for run_idx, strat in enumerate(strategies):
            # Check deadline
            now = time.perf_counter()
            if now >= deadline:
                telemetry.timed_out = True
                break

            telemetry.multi_start_runs_executed += 1
            random.seed(strat.seed)

            # 2. Run Bounded Beam Search over Aggregate Structures with ElasticDoorFrontier
            beam_searcher = BoundedBeamSearchEngine(
                container=container,
                cargo_list=cargo_list,
                config=cfg,
            )
            beam_placements = beam_searcher.search(
                sku_priority_order=strat.sku_priority_order,
                deadline_perf_counter=deadline,
            )

            # Aggregate Multi-Start Telemetry from beam searcher
            bt = beam_searcher.telemetry
            if cfg.wall_plan_search_mode == "GLOBAL_SEARCH" and incumbent is not None:
                bt["wall_plan_search"]["incumbent_history"].insert(0, {
                    "timestamp_sec": 0.0, "depth": 0,
                    "utilization": incumbent.volume_utilization_pct,
                    "topfill_utilization": None,
                    "placed_volume": cfg.global_incumbent_volume_m3,
                    "score": None, "door_ready": True,
                    "solution_source": "LEGACY_INCUMBENT",
                })
            telemetry.candidates_generated += bt.get("candidates_generated", 0)
            telemetry.candidates_evaluated += bt.get("candidates_evaluated", 0)
            for r, cnt in bt.get("candidates_rejected_by_reason", {}).items():
                telemetry.candidates_rejected_by_reason[r] = telemetry.candidates_rejected_by_reason.get(r, 0) + cnt
            for a, cnt in bt.get("anchors_generated_by_type", {}).items():
                telemetry.anchors_generated_by_type[a] = telemetry.anchors_generated_by_type.get(a, 0) + cnt
            for a, cnt in bt.get("candidates_generated_by_anchor_type", {}).items():
                telemetry.candidates_generated_by_anchor_type[a] = telemetry.candidates_generated_by_anchor_type.get(a, 0) + cnt
            for a, cnt in bt.get("candidates_valid_by_anchor_type", {}).items():
                telemetry.candidates_valid_by_anchor_type[a] = telemetry.candidates_valid_by_anchor_type.get(a, 0) + cnt
            telemetry.floor_frontier_count = max(telemetry.floor_frontier_count, bt.get("floor_frontier_count", 0))
            telemetry.supported_frontier_count = max(telemetry.supported_frontier_count, bt.get("supported_frontier_count", 0))
            telemetry.wall_frontier_count = max(telemetry.wall_frontier_count, bt.get("wall_frontier_count", 0))
            for p, reason in bt.get("phase_termination_reason", {}).items():
                telemetry.phase_termination_reason[f"{strat.strategy.value}_{p}"] = reason

            # 3. Build candidate WorldState from beam placements
            cand_world = WorldState(container=container, cargo_catalog=cargo_list)
            cand_space = FreeSpaceEngine(container=container, grid_resolution=cfg.grid_resolution)
            cand_qty = QuantityManager(cargo_list=cargo_list)
            cand_zone = AdaptiveZoneManager(container=container)
            cand_res = SpatialReservationManager()

            cand_qty.set_door_reserve_allocations(beam_searcher.elastic_frontier.allocations)
            cand_zone.adapt_door_zone_to_cargo(beam_searcher.door_seal_skus)
            cand_res.reserve_door_zone(container, door_zone_length_m=cand_zone.door_zone_length_m)

            for p in beam_placements:
                try:
                    cand_world.commit(p)
                    cand_space.on_placement_replayed(p)
                    cand_qty.record_placement(p.sku_id, context=p.context)
                except Exception:
                    pass

            # 4. Local Search & Post-Constructive Repair
            if local_optimizer and not cand_qty.all_required_satisfied() and time.perf_counter() < deadline:
                repair_res = local_optimizer.run_local_repair_pass(
                    world_state=cand_world,
                    space_engine=cand_space,
                    orientation_engine=OrientationEngine(),
                    zone_mgr=cand_zone,
                    qty_mgr=cand_qty,
                    res_mgr=cand_res,
                    cargo_catalog=sku_catalog,
                )
                telemetry.local_search_repairs += repair_res.repaired_steps

            # 4a/4b. GLOBAL closes the elastic door frontier before top fill;
            # LEGACY keeps its already accepted historical ordering.
            topfill_limit = (
                cfg.global_full_topfill_seed_budget
                if cfg.wall_plan_search_mode == "GLOBAL_SEARCH" else
                (8 if cfg.profile == SearchProfile.FAST else (16 if cfg.profile == SearchProfile.OPTIMIZE else 12))
            )
            door_planner = DoorClosurePlanner(container=container, frontier=beam_searcher.elastic_frontier)

            def deploy_terminal_door():
                started = time.perf_counter()
                result = door_planner.deploy_door_seal(
                    world_state=cand_world,
                    space_engine=cand_space,
                    qty_mgr=cand_qty,
                    door_seal_skus=beam_searcher.door_seal_skus,
                )
                if cfg.wall_plan_search_mode == "GLOBAL_SEARCH":
                    bt["wall_plan_search"]["performance"]["terminal_door_ms"] = (
                        time.perf_counter() - started
                    ) * 1000.0
                return result

            def deploy_terminal_topfill():
                started = time.perf_counter()
                if cfg.wall_plan_search_mode == "GLOBAL_SEARCH":
                    bt["wall_plan_search"]["full_topfill_calls"] += 1
                result = TopFillPlanner(container).deploy_conditional_top_fill(
                    world_state=cand_world,
                    qty_mgr=cand_qty,
                    cargo_catalog=sku_catalog,
                    zone_mgr=cand_zone,
                    res_mgr=cand_res,
                    max_placements=topfill_limit,
                )
                if cfg.wall_plan_search_mode == "GLOBAL_SEARCH":
                    bt["wall_plan_search"]["performance"]["terminal_topfill_ms"] = (
                        time.perf_counter() - started
                    ) * 1000.0
                return result

            if cfg.wall_plan_search_mode == "GLOBAL_SEARCH":
                deploy_res = deploy_terminal_door()
                topfill_deploy = deploy_terminal_topfill()
                bt["wall_plan_search"]["phase_history"] = [
                    "MAIN", "TRANSITION", "DOOR", "TOP_FILL", "COMPLETE",
                ]
            else:
                topfill_deploy = deploy_terminal_topfill()
                deploy_res = deploy_terminal_door()

            # 4c. BLK-006E is an explicit terminal-only neighborhood.  It runs
            # after MAIN/TRANSITION/DOOR/TOP_FILL, never participates in beam
            # expansion, and can only replace the parent by strict legal gain.
            if cfg.wall_plan_search_mode == "GLOBAL_SEARCH" and cfg.terminal_topfill_repair_enabled:
                repair_started = time.perf_counter()
                repair_cfg = TerminalRepairConfig.for_profile(cfg.terminal_topfill_repair_profile)
                repair = TerminalTopFillRepairOptimizer(container, cargo_list, repair_cfg).optimize(
                    cand_world.placements
                )
                bt["wall_plan_search"]["terminal_repair"] = {
                    "accepted": repair.accepted,
                    "source": repair.source,
                    "parent_volume_m3": repair.parent_volume_m3,
                    "repaired_volume_m3": repair.repaired_volume_m3,
                    "volume_gain_m3": repair.volume_gain_m3,
                    "parent_main_volume_m3": repair.parent_main_volume_m3,
                    "parent_topfill_volume_m3": repair.parent_topfill_volume_m3,
                    "repaired_main_volume_m3": repair.repaired_main_volume_m3,
                    "repaired_topfill_volume_m3": repair.repaired_topfill_volume_m3,
                    "runtime_sec": repair.runtime_sec,
                    "validation": repair.validation,
                    "stage_summaries": repair.stage_summaries,
                    "trace": repair.trace,
                    "rejection_pareto": repair.rejection_pareto,
                    "region_diagnostics": repair.region_diagnostics,
                    "plan_diagnostics": repair.plan_diagnostics,
                }
                if repair.accepted:
                    cand_world = WorldState(container=container, cargo_catalog=cargo_list)
                    cand_qty = QuantityManager(cargo_list=cargo_list)
                    cand_qty.set_door_reserve_allocations(beam_searcher.elastic_frontier.allocations)
                    for placement in repair.placements:
                        cand_world.commit(placement)
                        cand_qty.record_placement(placement.sku_id, placement.context)
                    topfill_deploy.placed = [
                        p for p in repair.placements if p.context == PlacementContext.TOP_FILL
                    ]
                bt["wall_plan_search"]["performance"]["terminal_repair_ms"] = (
                    time.perf_counter() - repair_started
                ) * 1000.0

            # 5. Independent Global Validation (Agent 06)
            terminal_validation_started = time.perf_counter()
            final_placements = cand_world.placements
            val_result = IndependentGlobalValidator.validate(
                container=container,
                placements=final_placements,
                cargo_list=cargo_list,
            )

            placed_cnt = len(final_placements)
            unplaced_cnt = max(0, total_required_items - placed_cnt)
            container_vol = container.volume
            cargo_vol = sum(p.volume for p in final_placements)
            util_pct = (cargo_vol / container_vol * 100.0) if container_vol > 0 else 0.0

            status = "SUCCESS" if (val_result.is_valid and (cand_qty.all_required_satisfied() or unplaced_cnt == 0)) else (
                "VALID_PARTIAL" if val_result.is_valid else "INVALID"
            )

            # Door readiness evaluation with deployment check
            readiness_rep = door_planner.evaluate_door_readiness(
                final_placements,
                reserve_deployed=cand_qty.get_reserve_deployed(),
                has_door_reserve_pool=(cand_qty.get_reserve_requested() > 0),
            )
            door_readiness_dict = {
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
            final_cavity = AdvancedCavityClassifier(container).classify_cavities(final_placements)
            if cfg.wall_plan_search_mode == "GLOBAL_SEARCH":
                bt["wall_plan_search"]["performance"]["terminal_validation_ms"] = (
                    time.perf_counter() - terminal_validation_started
                ) * 1000.0
            stability_debt_count = len(cand_world.stability_debt.get_unresolved_debts())
            complete_legal = (
                val_result.is_valid and readiness_rep.is_door_ready
                and not final_cavity.enclosed_cavities and final_cavity.bridge_void_count == 0
                and stability_debt_count == 0
            )
            if cfg.wall_plan_search_mode == "GLOBAL_SEARCH" and complete_legal:
                bt["wall_plan_search"]["complete_solutions_found"] += 1
                status = "COMPLETE_LEGAL"

            # Compute solution score: Hard Validity -> Volume Util -> Required Satisfaction -> Door Ready -> X Progression -> Carton Count
            req_satisfied_cnt = sum(
                1 for s in cargo_list
                if not s.quantity.is_elastic and cand_qty.get_state(s.sku_id) and cand_qty.get_state(s.sku_id).is_required_satisfied
            )
            door_bonus = 50000.0 if readiness_rep.is_door_ready else (10000.0 if readiness_rep.reached_transition_zone else 0.0)
            current_solution_score = (
                (1000000.0 if val_result.is_valid else -1000000.0) +
                util_pct * 1000.0 +
                req_satisfied_cnt * 200.0 +
                door_bonus +
                cand_world.max_x * 50.0 +
                placed_cnt * 1.0
            )
            if cfg.wall_plan_search_mode == "GLOBAL_SEARCH" and complete_legal:
                bt["wall_plan_search"]["incumbent_updates"] += 1
                bt["wall_plan_search"]["incumbent_history"].append({
                    "timestamp_sec": round(time.perf_counter() - t_start, 6),
                    "depth": bt["wall_plan_search"].get("max_depth", 0),
                    "utilization": util_pct,
                    "topfill_utilization": (
                        sum(p.volume for p in topfill_deploy.placed)
                        / max(sum(plan.get("usable_volume", 0.0) for plan in topfill_deploy.region_plans.values()), 1e-9)
                    ),
                    "placed_volume": cargo_vol,
                    "score": current_solution_score,
                    "door_ready": True,
                })

            # Create current candidate solution with anchor metrics
            classified_info = cand_space.get_classified_anchors(cand_world)
            anchors_gen = {cat.value: len(anchs) for cat, anchs in classified_info.items()}
            base_telemetry = SolverTelemetry(
                runtime_ms=(time.perf_counter() - t_start) * 1000.0,
                steps_committed=placed_cnt,
                phases_completed=["MultiStart_" + strat.strategy.value],
                candidates_generated=telemetry.candidates_generated,
                candidates_evaluated=telemetry.candidates_evaluated,
                candidates_rejected_by_reason=dict(telemetry.candidates_rejected_by_reason),
                anchors_generated_by_type=anchors_gen,
                candidates_generated_by_anchor_type=dict(telemetry.candidates_generated_by_anchor_type),
                candidates_valid_by_anchor_type=dict(telemetry.candidates_valid_by_anchor_type),
                floor_frontier_count=len(classified_info.get(AnchorCategory.FLOOR_FRONTIER, [])),
                supported_frontier_count=len(classified_info.get(AnchorCategory.SUPPORTED_FRONTIER, [])),
                wall_frontier_count=len(classified_info.get(AnchorCategory.WALL_FRONTIER, [])),
                phase_termination_reason={"MultiStart": f"Completed run with strategy {strat.strategy.value}, placed={placed_cnt}"},
                door_readiness=door_readiness_dict,
                top_fill_metrics={
                    "placed_count": topfill_deploy.placed_count,
                    "placed_volume_m3": sum(p.volume for p in topfill_deploy.placed),
                    "rejected_insufficient_support": topfill_deploy.rejected_insufficient_support,
                    "rejected_compression": topfill_deploy.rejected_compression,
                    "rejected_orientation_context": topfill_deploy.rejected_orientation_context,
                    "rejected_max_layers": topfill_deploy.rejected_max_layers,
                    "rejected_stability": topfill_deploy.rejected_stability,
                    "region_funnels": topfill_deploy.region_funnels,
                    "region_plans": topfill_deploy.region_plans,
                },
                wall_plan_search_metrics=bt.get("wall_plan_search", {}),
            )
            telemetry.door_readiness = door_readiness_dict

            candidate_solution = SolverSolution(
                status=status,
                container=container,
                placements=final_placements,
                placed_count=placed_cnt,
                unplaced_count=unplaced_cnt,
                volume_utilization_pct=util_pct,
                total_weight_kg=cand_world.total_weight_kg,
                validation_result=val_result,
                telemetry=base_telemetry,
            )

            # 6. Check if this is the best solution so far (Volume & Validity First)
            is_better = False
            if best_solution is None:
                is_better = True
            elif val_result.is_valid and not best_solution.validation_result.is_valid:
                is_better = True
            elif val_result.is_valid == best_solution.validation_result.is_valid:
                if util_pct > best_volume_util + 0.10:
                    is_better = True
                elif abs(util_pct - best_volume_util) <= 0.10:
                    if cand_world.max_x > best_solution.container.Lx * 0.8 and placed_cnt > best_placed_count:
                        is_better = True
                    elif current_solution_score > best_score:
                        is_better = True

            if is_better:
                best_solution = candidate_solution
                best_placed_count = placed_cnt
                best_volume_util = util_pct
                best_score = current_solution_score
                telemetry.best_strategy_name = strat.strategy.value
                telemetry.improvements_recorded += 1

                # Trigger Best-so-far Callback
                if cfg.on_improvement_callback is not None:
                    try:
                        cfg.on_improvement_callback(best_solution.to_dict(), run_idx, best_score)
                    except Exception:
                        pass

        # Finalize telemetry
        elapsed_ms = (time.perf_counter() - t_start) * 1000.0
        telemetry.runtime_ms = elapsed_ms

        if best_solution is None:
            # Fallback empty solution
            val_empty = IndependentGlobalValidator.validate(container=container, placements=[], cargo_list=cargo_list)
            best_solution = SolverSolution(
                status="EMPTY",
                container=container,
                placements=[],
                placed_count=0,
                unplaced_count=total_required_items,
                volume_utilization_pct=0.0,
                total_weight_kg=0.0,
                validation_result=val_empty,
                telemetry=SolverTelemetry(runtime_ms=elapsed_ms),
            )

        # A partial GLOBAL state is diagnostic only and is never a production
        # result. Fall back through the preserved legacy path using an isolated
        # configuration; this does not mutate or silently promote the branch.
        if cfg.wall_plan_search_mode == "GLOBAL_SEARCH" and best_solution.status != "COMPLETE_LEGAL" and incumbent is None:
            global_diagnostic = copy.deepcopy(best_solution.telemetry.wall_plan_search_metrics or {})
            legacy_cfg = copy.deepcopy(cfg)
            legacy_cfg.wall_plan_search_mode = "LEGACY_GREEDY"
            legacy_cfg.time_budget_sec = max(5.0, min(30.0, cfg.time_budget_sec))
            legacy_cfg.multi_start_runs = 1
            legacy_result = HierarchicalSearchSolver(legacy_cfg).solve(container, cargo_list)
            global_diagnostic.update({
                "fallback_used": True,
                "fallback_reason": global_diagnostic.get("budget_stop_reason") or "NO_COMPLETE_LEGAL_GLOBAL_SOLUTION",
                "returned_solution_source": "LEGACY_GREEDY_INCUMBENT",
            })
            legacy_result.telemetry.wall_plan_search_metrics = global_diagnostic
            return legacy_result

        if cfg.wall_plan_search_mode == "GLOBAL_SEARCH":
            global_best = best_solution
            global_diagnostic = copy.deepcopy(global_best.telemetry.wall_plan_search_metrics or {})
            global_top = global_best.telemetry.top_fill_metrics or {}
            global_top_usable = sum(
                plan.get("usable_volume", 0.0)
                for plan in global_top.get("region_plans", {}).values()
            )
            global_top_volume = sum(
                p.volume for p in global_best.placements if p.context == PlacementContext.TOP_FILL
            )
            global_main_volume = sum(
                p.volume for p in global_best.placements
                if p.context not in (PlacementContext.TOP_FILL, PlacementContext.DOOR_SEAL)
            )
            global_door_volume = sum(
                p.volume for p in global_best.placements if p.context == PlacementContext.DOOR_SEAL
            )
            readiness_data = global_best.telemetry.door_readiness or {}
            door_start_x = float(readiness_data.get("authoritative_door_start_x", container.Lx))
            occupied_door_volume = sum(
                max(0.0, p.max_x - max(p.min_x, door_start_x)) * p.orientation.dy * p.orientation.dz
                for p in global_best.placements if p.max_x > door_start_x
            )
            global_diagnostic["global_best_result"] = {
                "status": global_best.status,
                "utilization_pct": global_best.volume_utilization_pct,
                "placed_volume_m3": sum(p.volume for p in global_best.placements),
                "door_ready": bool((global_best.telemetry.door_readiness or {}).get("is_door_ready", False)),
                "main_body_volume_m3": global_main_volume,
                "topfill_volume_m3": global_top_volume,
                "topfill_usable_volume_m3": global_top_usable,
                "topfill_utilization": global_top_volume / max(global_top_usable, 1e-9),
                "door_volume_m3": global_door_volume,
                "unused_container_volume_m3": max(0.0, container.volume - sum(p.volume for p in global_best.placements)),
                "residual_top_volume_m3": max(0.0, global_top_usable - global_top_volume),
                "max_x": max((p.max_x for p in global_best.placements), default=0.0),
                "door_residual_volume_m3": max(
                    0.0, (container.Lx - door_start_x) * container.Ly * container.Lz - occupied_door_volume,
                ),
            }
            if incumbent is not None and incumbent.volume_utilization_pct >= global_best.volume_utilization_pct - 1e-9:
                best_solution = copy.deepcopy(incumbent)
                global_diagnostic.update({
                    "fallback_used": False,
                    "returned_solution_source": "LEGACY_INCUMBENT",
                    "incumbent_won_comparison": True,
                })
                best_solution.telemetry.wall_plan_search_metrics = global_diagnostic
            else:
                global_diagnostic.update({
                    "returned_solution_source": "GLOBAL_SEARCH",
                    "incumbent_won_comparison": False,
                })
                best_solution.telemetry.wall_plan_search_metrics = global_diagnostic

        # Attach search telemetry in best solution telemetry dict
        best_solution.telemetry.runtime_ms = elapsed_ms
        best_solution.telemetry.candidates_generated = telemetry.candidates_generated
        best_solution.telemetry.candidates_evaluated = telemetry.candidates_evaluated
        best_solution.telemetry.candidates_rejected_by_reason = dict(telemetry.candidates_rejected_by_reason)
        best_solution.telemetry.phases_completed.append(f"SearchCompleted(runs={telemetry.multi_start_runs_executed},best={telemetry.best_strategy_name})")

        return best_solution

    def _resolve_config(self, options: Optional[Dict[str, Any]]) -> SearchConfig:
        """Resolves configuration options."""
        if not options:
            return self.config

        profile_str = options.get("profile", self.config.profile.value if hasattr(self.config.profile, "value") else "BALANCED")
        profile = SearchProfile(profile_str) if profile_str in SearchProfile.__members__ else SearchProfile.BALANCED
        cfg = SearchConfig.for_profile(
            profile=profile,
            seed=options.get("seed", self.config.seed),
            on_improvement=options.get("on_improvement_callback", self.config.on_improvement_callback),
        )
        for k, v in options.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg

    def _validated_incumbent(
        self,
        container: ContainerSpec,
        cargo_list: List[CargoSKU],
    ) -> Optional[SolverSolution]:
        """Revalidate a supplied legacy lower bound before it can seed/return."""
        if self.incumbent_solution is None:
            return None
        incumbent = copy.deepcopy(self.incumbent_solution)
        validation = IndependentGlobalValidator.validate(container, incumbent.placements, cargo_list)
        cavity = AdvancedCavityClassifier(container).classify_cavities(incumbent.placements)
        door_skus = [
            sku for sku in cargo_list
            if PackingRole.DOOR_SEAL in sku.packing_roles or sku.target_zone == ZoneType.DOOR
        ]
        frontier = ElasticDoorFrontier(container=container, door_skus=door_skus)
        qty = QuantityManager(cargo_list)
        qty.set_door_reserve_allocations(frontier.allocations)
        for placement in incumbent.placements:
            qty.record_placement(placement.sku_id, context=placement.context)
        door = DoorClosurePlanner(container=container, frontier=frontier).evaluate_door_readiness(
            incumbent.placements,
            reserve_deployed=qty.get_reserve_deployed(),
            has_door_reserve_pool=qty.get_reserve_requested() > 0,
        )
        if not validation.is_valid or not door.is_door_ready or cavity.enclosed_cavities or cavity.bridge_void_count:
            return None
        incumbent.validation_result = validation
        incumbent.status = "COMPLETE_LEGAL"
        incumbent.telemetry.door_readiness = {
            **(incumbent.telemetry.door_readiness or {}), "is_door_ready": True,
        }
        return incumbent
