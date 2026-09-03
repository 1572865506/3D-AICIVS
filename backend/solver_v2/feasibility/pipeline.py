"""
Hard Validation Pipeline for Solver V2 (Agent 05 / BLK-002).
Provides ultra-fast, millisecond-level candidate feasibility gating:
1. Bounds Check
2. Spatial Index Collision Check
3. Spatial Reservation Conflict Check
4. Elastic Door Frontier & Hard Zone Compliance Check
5. Floor-Only Rule Check
6. Bottom Support Ratio & Floating Check
7. Lower Box No-Top-Stacking Check
8. Stacking Layer Depth Limits
9. Lower Box Bearing Capacity Limits
10. Payload Weight Capacity Check
"""
import time
from typing import Tuple, Optional, List, Dict, Any, Callable
from collections import defaultdict

from backend.solver_v2.domain.models import (
    CargoSKU,
    ContainerSpec,
    Placement,
    PlacementContext,
    PackingRole,
    ZoneType,
)
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.candidates.generator import CandidatePlacement
from backend.solver_v2.world.state import WorldState
from backend.solver_v2.zones.manager import AdaptiveZoneManager
from backend.solver_v2.quantity.manager import SpatialReservationManager
from backend.solver_v2.door.elastic_frontier import ElasticDoorFrontier, ProbeStatus


class HardValidationPipeline:
    """
    Fast, stateless hard validation pipeline for candidate placements.
    """

    def __init__(
        self,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
        max_allowed_cavity_volume: Optional[float] = None,
    ):
        self.geom_epsilon = geom_epsilon
        self.max_allowed_cavity_volume = max_allowed_cavity_volume
        self.rejection_counts: Dict[str, int] = defaultdict(int)
        self._residual_scorer = None

    def is_feasible(
        self,
        candidate: CandidatePlacement,
        sku: CargoSKU,
        world_state: WorldState,
        zone_mgr: AdaptiveZoneManager,
        res_mgr: Optional[SpatialReservationManager] = None,
        elastic_frontier: Optional[ElasticDoorFrontier] = None,
        context: Optional[PlacementContext] = None,
        timing_hook: Optional[Callable[[str, float], None]] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Runs the full sequence of hard gates on candidate.
        Returns (is_valid, failure_reason).
        """
        eps = self.geom_epsilon
        container = world_state.container
        cand_aabb = candidate.aabb
        x, y, z = candidate.x, candidate.y, candidate.z
        dx, dy, dz = candidate.dx, candidate.dy, candidate.dz

        def record(stage: str, started: float) -> None:
            if timing_hook is not None:
                timing_hook(stage, (time.perf_counter() - started) * 1000.0)

        # 1. Bounds Check
        stage_started = time.perf_counter()
        bounds_ok = cand_aabb.is_within_bounds(container.Lx, container.Ly, container.Lz, eps=eps)
        record("bounds_validation_ms", stage_started)
        if not bounds_ok:
            self.rejection_counts["BOUNDS"] += 1
            return False, "Candidate exceeds container bounds"

        # 2. Collision Check (via Spatial Index)
        stage_started = time.perf_counter()
        colliding_items = world_state.spatial_index.query_intersect(cand_aabb, eps=eps)
        record("collision_query_ms", stage_started)
        if colliding_items:
            self.rejection_counts["COLLISION"] += 1
            return False, f"Candidate collides with {len(colliding_items)} existing items"

        # 3. Spatial Reservation Check
        if res_mgr:
            stage_started = time.perf_counter()
            ok_res, reason_res = res_mgr.check_candidate_conflict(cand_aabb, sku)
            record("handling_validation_ms", stage_started)
            if not ok_res:
                self.rejection_counts["SPATIAL_RESERVATION"] += 1
                return False, reason_res

        # 4. Elastic Door Frontier Probe Check (if available)
        if elastic_frontier:
            stage_started = time.perf_counter()
            is_door = (PackingRole.DOOR_SEAL in sku.packing_roles or sku.target_zone == ZoneType.DOOR)
            probe = elastic_frontier.evaluate_probe(
                candidate_max_x=x + dx,
                current_max_x=world_state.max_x,
                is_door_sku=is_door,
                context=context,
            )
            record("zone_validation_ms", stage_started)
            if probe.status == ProbeStatus.INFEASIBLE:
                self.rejection_counts["DOOR_FRONTIER_INFEASIBLE"] += 1
                return False, probe.reason or "Candidate encroaches on dynamic door reservation"

        # 5. Zone Compliance Gating
        stage_started = time.perf_counter()
        ok_zone, reason_zone = zone_mgr.check_hard_zone_compliance(sku, x, y, z, dx, dy, dz)
        record("zone_validation_ms", stage_started)
        if not ok_zone:
            self.rejection_counts["ZONE_RULE"] += 1
            return False, reason_zone

        # 6. Payload Weight Capacity Check
        if container.max_payload_kg > 0:
            if world_state.total_weight_kg + candidate.weight_kg > container.max_payload_kg + eps:
                self.rejection_counts["MAX_PAYLOAD"] += 1
                return False, "Total weight would exceed container max payload"

        # 7. Floor Only Check
        if sku.stacking_policy.must_be_on_floor and z > eps:
            self.rejection_counts["FLOOR_ONLY"] += 1
            return False, f"SKU '{sku.sku_id}' must be on floor, but candidate is at z={z:.3f}"

        # 8. Support Ratio & Floating Box Check
        if z > eps:
            support_started = time.perf_counter()
            # Query items directly below candidate's bottom face
            support_aabb = AABB(x, y, z - 0.05, x + dx, y + dy, z + eps)
            touching_items = world_state.spatial_index.query_intersect(support_aabb, eps=eps)

            total_support_area = 0.0
            lower_placements: List[Placement] = []

            for item in touching_items:
                p_below: Optional[Placement] = item.data
                if p_below is None:
                    continue

                # Check if top face of p_below aligns with candidate bottom z
                p_top_z = p_below.position.z + p_below.orientation.dz
                if abs(p_top_z - z) <= eps:
                    # Compute XY contact area
                    p_min_x, p_max_x = p_below.min_x, p_below.max_x
                    p_min_y, p_max_y = p_below.min_y, p_below.max_y

                    ox = max(0.0, min(x + dx, p_max_x) - max(x, p_min_x))
                    oy = max(0.0, min(y + dy, p_max_y) - max(y, p_min_y))
                    if ox > eps and oy > eps:
                        total_support_area += ox * oy
                        lower_placements.append(p_below)

            base_area = dx * dy
            support_ratio = min(1.0, (total_support_area / base_area)) if base_area > 0 else 0.0
            min_ratio = sku.stacking_policy.min_support_ratio

            if support_ratio < min_ratio - eps:
                record("support_graph_ms", support_started)
                self.rejection_counts["INSUFFICIENT_SUPPORT"] += 1
                return False, f"Insufficient support ratio ({support_ratio * 100:.1f}% < {min_ratio * 100:.1f}%)"

            # Anti-Bridge Check: check maximum unsupported span between supports
            if len(lower_placements) >= 2:
                sorted_lp_y = sorted(lower_placements, key=lambda p: p.min_y)
                for i in range(len(sorted_lp_y) - 1):
                    gap_y = sorted_lp_y[i+1].min_y - sorted_lp_y[i].max_y
                    max_allowed_span = sku.stacking_policy.max_unsupported_span_m
                    if gap_y > max_allowed_span:
                        self.rejection_counts["BRIDGE_VOID_VIOLATION"] += 1
                        record("support_graph_ms", support_started)
                        return False, f"Unsupported span ({gap_y:.3f}m) exceeds max allowed bridge span ({max_allowed_span:.3f}m)"

            # 9. Check if any lower placement forbids stacking on top
            catalog = world_state._cargo_catalog
            for lp in lower_placements:
                lower_sku = catalog.get(lp.sku_id)
                if lower_sku and not lower_sku.stacking_policy.allow_stacking_on_top:
                    self.rejection_counts["NO_TOP_STACK"] += 1
                    record("support_graph_ms", support_started)
                    return False, f"Supporting item '{lp.placement_id}' forbids stacking on top"

                # 10. Bearing Capacity Check on lower placement
                if lower_sku and lower_sku.stacking_policy.max_bearing_kg is not None:
                    if candidate.weight_kg > lower_sku.stacking_policy.max_bearing_kg + eps:
                        self.rejection_counts["BEARING_EXCEEDED"] += 1
                        record("compression_validation_ms", support_started)
                        return False, f"Candidate weight ({candidate.weight_kg:.1f}kg) exceeds supporting item bearing limit ({lower_sku.stacking_policy.max_bearing_kg:.1f}kg)"

            # 11. Stacking layers check
            if sku.stacking_policy.max_stack_layers is not None:
                max_layers = sku.stacking_policy.max_stack_layers
                layers_below = 0
                curr_z = z
                while curr_z > eps:
                    found_below = False
                    search_aabb = AABB(x, y, curr_z - 0.05, x + dx, y + dy, curr_z + eps)
                    below_items = world_state.spatial_index.query_intersect(search_aabb, eps=eps)
                    for it in below_items:
                        pl = it.data
                        if (
                            pl
                            and pl.sku_id == sku.sku_id
                            and abs(pl.position.z + pl.orientation.dz - curr_z) <= eps
                        ):
                            layers_below += 1
                            curr_z = pl.position.z
                            found_below = True
                            break
                    if not found_below:
                        break
                if layers_below + 1 > max_layers:
                    self.rejection_counts["STACK_LIMIT_VIOLATION"] += 1
                    record("compression_validation_ms", support_started)
                    return False, f"Stack depth ({layers_below + 1}) exceeds max layers ({max_layers})"

            record("support_graph_ms", support_started)
        # 12. Enclosed Cavity Hard Threshold Check (Step 5.3)
        if self.max_allowed_cavity_volume is not None and world_state.container is not None:
            cavity_started = time.perf_counter()
            if self._residual_scorer is None or self._residual_scorer.container is not world_state.container:
                from backend.solver_v2.spaces.residual_quality import ResidualQualityScorer
                self._residual_scorer = ResidualQualityScorer(container=world_state.container)
            
            rq_res = self._residual_scorer.evaluate_detailed(
                world_state=world_state,
                candidate_placement=candidate,
            )
            new_cavity_volume = rq_res.enclosed_cavity_volume
            record("cavity_validation_ms", cavity_started)
            if new_cavity_volume > self.max_allowed_cavity_volume:
                self.rejection_counts["ENCLOSED_CAVITY_EXCEEDED"] += 1
                return False, f"ENCLOSED_CAVITY_EXCEEDED: Cavity volume {new_cavity_volume:.4f}m3 exceeds allowed {self.max_allowed_cavity_volume:.4f}m3"

        return True, None
