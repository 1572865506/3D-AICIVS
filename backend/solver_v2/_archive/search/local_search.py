"""
Local search, post-constructive repair, and compaction engine for Solver V2 (Agent 09).
"""
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple

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
from backend.solver_v2.spaces.engine import FreeSpaceEngine
from backend.solver_v2.orientation.manager import OrientationEngine
from backend.solver_v2.zones.manager import AdaptiveZoneManager
from backend.solver_v2.quantity.manager import QuantityManager, SpatialReservationManager
from backend.solver_v2.candidates.generator import CandidateGenerator, CandidatePlacement
from backend.solver_v2.feasibility.pipeline import HardValidationPipeline
from backend.solver_v2.solver.scorer import CandidateScorer
from backend.solver_v2.topfill.planner import TopFillPlanner
from backend.solver_v2.door.closure_planner import DoorClosurePlanner


@dataclass
class LocalSearchResult:
    """Result of local search and repair pass."""
    additional_placements: int = 0
    repaired_steps: int = 0
    improved_volume_pct: float = 0.0


class LocalSearchOptimizer:
    """
    Performs local search and post-constructive repair:
    - Residual gap fill with remaining loose items
    - Headspace Top Fill compaction
    - Door zone sealing & stabilization
    """

    def __init__(
        self,
        candidate_gen: Optional[CandidateGenerator] = None,
        validator_pipeline: Optional[HardValidationPipeline] = None,
        scorer: Optional[CandidateScorer] = None,
    ):
        self.candidate_gen = candidate_gen or CandidateGenerator()
        self.validator_pipeline = validator_pipeline or HardValidationPipeline()
        self.scorer = scorer or CandidateScorer()

    def run_local_repair_pass(
        self,
        world_state: WorldState,
        space_engine: FreeSpaceEngine,
        orientation_engine: OrientationEngine,
        zone_mgr: AdaptiveZoneManager,
        qty_mgr: QuantityManager,
        res_mgr: SpatialReservationManager,
        cargo_catalog: Dict[str, CargoSKU],
        max_iterations: int = 50,
    ) -> LocalSearchResult:
        """
        Executes an iterative residual gap fill and compaction pass over free spaces.
        """
        result = LocalSearchResult()
        init_vol = sum(p.volume for p in world_state.placements)
        container_vol = world_state.container.volume

        # 1. Check if all required quantities are satisfied
        if qty_mgr.all_required_satisfied():
            return result

        # 2. Release door zone reservation for residual gap fill
        for r in res_mgr._reservations.values():
            if r.reservation_id == "DOOR_ZONE_RESERVATION":
                r.is_active = False

        step_idx = len(world_state.placements)
        topfill_planner = TopFillPlanner(world_state.container, orientation_engine=orientation_engine)

        for _ in range(max_iterations):
            unfilled_sku_ids = qty_mgr.get_sku_priorities()
            if not unfilled_sku_ids:
                break

            remaining_skus = [cargo_catalog[sid] for sid in unfilled_sku_ids if qty_mgr.get_remaining(sid) > 0]
            if not remaining_skus:
                break

            # Try Top Fill context first if headspace is available, else GAP_FILL / MAIN_WALL
            candidates = self.candidate_gen.generate_candidates(
                world_state=world_state,
                space_engine=space_engine,
                orientation_engine=orientation_engine,
                zone_mgr=zone_mgr,
                qty_mgr=qty_mgr,
                active_skus=remaining_skus,
                context=PlacementContext.TOP_FILL,
                max_candidates=100,
            )

            if not candidates:
                # Fallback to GAP_FILL / MAIN_WALL context
                candidates = self.candidate_gen.generate_candidates(
                    world_state=world_state,
                    space_engine=space_engine,
                    orientation_engine=orientation_engine,
                    zone_mgr=zone_mgr,
                    qty_mgr=qty_mgr,
                    active_skus=remaining_skus,
                    context=PlacementContext.GAP_FILL,
                    max_candidates=100,
                )

            if not candidates:
                break

            # Filter feasible candidates
            valid_scored: List[Tuple[float, CandidatePlacement, CargoSKU]] = []
            topfill_regions = {
                r.region_id: r for r in topfill_planner.extract_top_fill_regions(world_state, cargo_catalog)
            }
            for cand in candidates:
                sku = cargo_catalog[cand.sku_id]
                is_valid, _ = self.validator_pipeline.is_feasible(
                    candidate=cand,
                    sku=sku,
                    world_state=world_state,
                    zone_mgr=zone_mgr,
                    res_mgr=res_mgr,
                )
                if not is_valid:
                    continue
                if cand.context == PlacementContext.TOP_FILL:
                    region = topfill_regions.get(cand.topfill_region_id or "")
                    if region is None or not topfill_planner.evaluate_topfill_candidate(
                        cand, sku, region, world_state, cargo_catalog, zone_mgr,
                    ).is_valid:
                        continue

                score = self.scorer.score_candidate(
                    candidate=cand,
                    sku=sku,
                    world_state=world_state,
                    space_engine=space_engine,
                    zone_mgr=zone_mgr,
                    remaining_skus=remaining_skus,
                )
                valid_scored.append((score, cand, sku))

            if not valid_scored:
                break

            # Select best candidate
            valid_scored.sort(key=lambda item: item[0], reverse=True)
            _, best_cand, best_sku = valid_scored[0]

            placement_id = f"repair_{step_idx:04d}_{best_sku.sku_id}"
            instance_id = f"inst_repair_{step_idx:04d}"
            placement = best_cand.to_placement(
                placement_id=placement_id,
                instance_id=instance_id,
                step_index=step_idx,
            )

            world_state.commit(placement)
            space_engine.on_placement_committed(placement, remaining_skus)
            qty_mgr.record_placement(best_sku.sku_id)

            step_idx += 1
            result.additional_placements += 1
            result.repaired_steps += 1

        final_vol = sum(p.volume for p in world_state.placements)
        if container_vol > 0:
            result.improved_volume_pct = (final_vol - init_vol) / container_vol * 100.0

        return result
