"""
Door Closure Planner and Anti-Toppling Verification for Solver V2 (Agent 08 / BLK-002B).
Evaluates door boundary clearances, door-face flatness, cross-sectional closure coverage,
anti-tipping resistance upon door opening, and ensures continuous wall growth.

Enforces strict hard prerequisites on door readiness:
1. Cargo must reach transition zone (reached_transition_zone == True)
2. Cargo must reach door closure zone (reached_door_closure_zone == True)
3. Largest longitudinal door gap must be within threshold (<= 0.50m)
4. Door zone occupancy must exceed minimum (>= 0.05)
5. Door closure coverage must exceed minimum (>= 0.25)
6. Door reserve pool must be actually deployed (reserve_deployed > 0 if reserve exists)
"""
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any, Set
import math

from backend.solver_v2.domain.models import (
    ContainerSpec,
    CargoSKU,
    Placement,
    PlacementContext,
    PackingRole,
    Point3D,
    Orientation3D,
)
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.physics.contact_graph import ContactGraph, ContactDirection
from backend.solver_v2.structure.wall_surface import WallSurfaceMap, WallSurfaceMetrics


@dataclass(frozen=True)
class DoorReadinessReport:
    """Quantitative evaluation of container door closure readiness and cargo retention safety."""
    is_door_ready: bool
    door_clearance_margin_m: float      # Distance from front-most cargo to Lx (must be >= 0)
    door_zone_occupancy: float          # Volume utilization in door zone [Lx - d_door, Lx]
    door_face_flatness: float           # Flatness score [0.0, 1.0] of cargo face adjacent to door
    anti_toppling_stable_ratio: float   # Ratio of door-zone cargo that is stable against door-opening tipping
    door_readiness_score: float         # Composite readiness score [0.0, 100.0]
    rejection_reasons: Tuple[str, ...]
    door_closure_coverage: float = 0.0  # Cross section coverage ratio [0.0, 1.0] of front door wall
    largest_door_gap: float = 0.0       # Largest gap along longitudinal door threshold
    reached_transition_zone: bool = False
    reached_door_closure_zone: bool = False
    reserve_deployed: int = 0
    authoritative_transition_start_x: float = 0.0
    authoritative_door_start_x: float = 0.0
    boundary_source: str = "ElasticDoorFrontier"

    @property
    def door_wall_flatness(self) -> float:
        return self.door_face_flatness

    @property
    def primary_rejection_reason(self) -> Optional[str]:
        return self.rejection_reasons[0] if self.rejection_reasons else None


@dataclass
class DoorDeploymentResult:
    """Detailed trace and metrics resulting from active door reserve deployment."""
    door_phase_started: bool
    door_phase_start_x: float
    door_anchor_count: int
    door_candidates_generated: int
    door_candidates_valid: int
    door_candidates_rejected_by_reason: Dict[str, int]
    door_placements: List[Placement]
    reserve_deployed_by_sku: Dict[str, int]
    reserve_remaining_by_sku: Dict[str, int]
    reserve_deployed: int
    reserve_remaining: int
    closure_before: float
    closure_after: float
    largest_gap_before: float
    largest_gap_after: float
    door_occupancy_before: float
    door_occupancy_after: float
    authoritative_transition_start_x: float
    authoritative_door_start_x: float
    boundary_source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "door_phase_started": self.door_phase_started,
            "door_phase_start_x": self.door_phase_start_x,
            "door_anchor_count": self.door_anchor_count,
            "door_candidates_generated": self.door_candidates_generated,
            "door_candidates_valid": self.door_candidates_valid,
            "door_candidates_rejected_by_reason": self.door_candidates_rejected_by_reason,
            "door_placements_count": len(self.door_placements),
            "reserve_deployed_by_sku": self.reserve_deployed_by_sku,
            "reserve_remaining_by_sku": self.reserve_remaining_by_sku,
            "reserve_deployed": self.reserve_deployed,
            "reserve_remaining": self.reserve_remaining,
            "closure_before": self.closure_before,
            "closure_after": self.closure_after,
            "largest_gap_before": self.largest_gap_before,
            "largest_gap_after": self.largest_gap_after,
            "door_occupancy_before": self.door_occupancy_before,
            "door_occupancy_after": self.door_occupancy_after,
            "authoritative_transition_start_x": self.authoritative_transition_start_x,
            "authoritative_door_start_x": self.authoritative_door_start_x,
            "boundary_source": self.boundary_source,
        }


class DoorClosurePlanner:
    """
    Plans, deploys, and verifies cargo layout in the container door zone.
    Ensures continuous wall growth from existing cargo and robust closure.
    """

    def __init__(
        self,
        container: ContainerSpec,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
        frontier: Optional[Any] = None,
        door_zone_length_m: Optional[float] = None,
        transition_zone_length_m: float = 0.5,
    ):
        self.container = container
        self.geom_epsilon = geom_epsilon
        self.frontier = frontier

        if frontier is not None and hasattr(frontier, "get_metrics"):
            metrics = frontier.get_metrics()
            self.door_zone_x_start = float(metrics.door_closure_start_x)
            self.transition_zone_x_start = float(metrics.transition_start_x)
            self.latest_safe_main_x = float(metrics.latest_safe_main_x)
            self.door_zone_length_m = max(0.0, container.Lx - self.door_zone_x_start)
            self.boundary_source = "ElasticDoorFrontier"
        else:
            d_len = door_zone_length_m if door_zone_length_m is not None else 0.400
            self.door_zone_length_m = d_len
            self.door_zone_x_start = max(0.0, container.Lx - d_len)
            self.transition_zone_x_start = max(0.0, self.door_zone_x_start - transition_zone_length_m)
            self.latest_safe_main_x = max(0.0, container.Lx - 0.200)
            self.boundary_source = "ElasticDoorFrontierDefault"

    def is_in_door_zone(self, placement: Placement) -> bool:
        """Returns True if the placement intersects the door zone."""
        return placement.max_x > (self.door_zone_x_start - self.geom_epsilon)

    def evaluate_door_readiness(
        self,
        placements: List[Placement],
        contact_graph: Optional[ContactGraph] = None,
        min_clearance_m: float = 0.0,
        door_clearance_tolerance_m: float = 0.02,
        reserve_deployed: int = 0,
        has_door_reserve_pool: bool = False,
    ) -> DoorReadinessReport:
        """
        Evaluates complete door closure readiness with strict hard prerequisites:
        1. Boundary clearance: no placement max_x > Lx.
        2. Door clearance margin: (Lx - max_x) >= min_clearance_m.
        3. Transition & Door Zone Reachability: cargo must have advanced into transition & door zones.
        4. Longitudinal gap: (Lx - max_x) <= 0.50m.
        5. Door zone occupancy: must be >= 0.05.
        6. Cross-section coverage: front cargo must cover >= 25% of cross section.
        7. Reserve pool deployment: if door reserve pool exists, at least 1 must be deployed.
        8. Anti-toppling stability: door-adjacent cargo must have bottom/rear contact.
        """
        reasons: List[str] = []
        eps = self.geom_epsilon

        if not placements:
            return DoorReadinessReport(
                is_door_ready=False,
                door_clearance_margin_m=self.container.Lx,
                door_zone_occupancy=0.0,
                door_face_flatness=0.0,
                anti_toppling_stable_ratio=1.0,
                door_readiness_score=0.0,
                rejection_reasons=("No placements in container",),
                door_closure_coverage=0.0,
                largest_door_gap=self.container.Lx,
                reached_transition_zone=False,
                reached_door_closure_zone=False,
                reserve_deployed=0,
                authoritative_transition_start_x=round(self.transition_zone_x_start, 4),
                authoritative_door_start_x=round(self.door_zone_x_start, 4),
                boundary_source=self.boundary_source,
            )

        # 1. Boundary & Clearance Check
        max_cargo_x = max(p.max_x for p in placements)
        if max_cargo_x > self.container.Lx + eps:
            reasons.append(
                f"Cargo exceeds door boundary: max_x {max_cargo_x:.4f}m > container length {self.container.Lx:.4f}m"
            )

        clearance_margin = max(0.0, self.container.Lx - max_cargo_x)
        if clearance_margin < min_clearance_m - eps:
            reasons.append(
                f"Insufficient door clearance: {clearance_margin:.4f}m < required {min_clearance_m:.4f}m"
            )

        # 2. Transition and Door Zone Reachability Prerequisites (Strict Authoritative Boundaries)
        reached_transition = max_cargo_x >= (self.transition_zone_x_start - eps)
        reached_door_zone = max_cargo_x >= (self.door_zone_x_start - eps)

        if not reached_transition:
            reasons.append(
                f"Cargo failed to reach transition zone: max_x {max_cargo_x:.3f}m < transition start {self.transition_zone_x_start:.3f}m"
            )

        if not reached_door_zone:
            reasons.append(
                f"Cargo failed to reach door closure zone: max_x {max_cargo_x:.3f}m < door zone start {self.door_zone_x_start:.3f}m"
            )

        # 3. Door Zone Placements & Occupancy
        door_placements = [p for p in placements if self.is_in_door_zone(p)]
        door_zone_vol = (self.container.Lx - self.door_zone_x_start) * self.container.Ly * self.container.Lz
        door_cargo_vol = sum(p.volume for p in door_placements)
        door_occupancy = (door_cargo_vol / door_zone_vol) if door_zone_vol > 0 else 0.0

        if reached_door_zone and door_occupancy < 0.05:
            reasons.append(
                f"Door zone occupancy too low: {door_occupancy:.1%} < minimum required 5.0%"
            )

        # 4. Longitudinal Door Gap (cargo must reach close to door threshold)
        largest_door_gap = max(clearance_margin, self.container.Lx - max_cargo_x)
        if clearance_margin > 0.50:
            reasons.append(
                f"Excessive longitudinal door gap: {clearance_margin:.3f}m > allowable threshold 0.50m"
            )

        # 5. Door Face Flatness & Cross Section Coverage
        if door_placements:
            door_surface_map = WallSurfaceMap(self.container, grid_resolution_m=0.1, geom_epsilon=eps)
            door_surface_metrics = door_surface_map.build_from_placements(door_placements)
            door_flatness = door_surface_metrics.flatness_score
            largest_door_gap = max(largest_door_gap, door_surface_metrics.max_step_discontinuity)
        else:
            door_flatness = 0.0  # Empty surface cannot have 1.0 flatness!

        # Front items for cross section coverage
        front_threshold = max_cargo_x - 0.6
        front_items = [p for p in placements if p.max_x >= front_threshold - eps]
        front_area = sum(p.orientation.dy * p.orientation.dz for p in front_items)
        cross_section_area = self.container.Ly * self.container.Lz
        closure_coverage = min(1.0, (front_area / cross_section_area)) if cross_section_area > 0 else 0.0

        if reached_door_zone and closure_coverage < 0.25:
            reasons.append(
                f"Door front cross-section coverage too low: {closure_coverage:.1%} < minimum required 25.0%"
            )

        # 6. Door Reserve Pool Deployment Check
        if has_door_reserve_pool and reserve_deployed <= 0:
            door_role_placements_in_zone = [
                p for p in door_placements if p.context == PlacementContext.DOOR_SEAL
            ]
            if not door_role_placements_in_zone:
                reasons.append(
                    f"Door reserve pool was never deployed into door closure (reserve_deployed={reserve_deployed})"
                )

        # 7. Anti-Toppling Stability
        stable_door_items = 0
        for p in front_items:
            slenderness_x = p.orientation.dz / max(1e-4, p.orientation.dx)
            is_floor = p.min_z <= eps

            has_rear_support = False
            if contact_graph is not None:
                back_contacts = contact_graph.get_contacts_in_direction(p.placement_id, ContactDirection.BACK)
                has_rear_support = len(back_contacts) > 0 or p.min_x <= eps
            else:
                has_rear_support = p.min_x > 0.0

            if slenderness_x <= 3.0 or (is_floor and has_rear_support) or has_rear_support:
                stable_door_items += 1

        anti_toppling_ratio = (stable_door_items / len(front_items)) if front_items else 1.0
        if reached_door_zone and anti_toppling_ratio < 0.60:
            reasons.append(
                f"Door front anti-toppling risk: stable ratio {anti_toppling_ratio:.1%} < required 60%"
            )

        # 8. Composite Readiness Score (0 to 100)
        clearance_score = 20.0 if clearance_margin <= 0.50 and clearance_margin >= min_clearance_m else 0.0
        occupancy_score = min(30.0, door_occupancy * 30.0)
        flatness_score = door_flatness * 30.0
        stability_score = anti_toppling_ratio * 20.0

        total_score = clearance_score + occupancy_score + flatness_score + stability_score
        if reasons:
            total_score = max(0.0, min(total_score, 49.0))

        is_ready = (len(reasons) == 0) and reached_door_zone and reached_transition

        return DoorReadinessReport(
            is_door_ready=is_ready,
            door_clearance_margin_m=round(clearance_margin, 4),
            door_zone_occupancy=round(door_occupancy, 4),
            door_face_flatness=round(door_flatness, 4),
            anti_toppling_stable_ratio=round(anti_toppling_ratio, 4),
            door_readiness_score=round(total_score, 2),
            rejection_reasons=tuple(reasons),
            door_closure_coverage=round(closure_coverage, 4),
            largest_door_gap=round(largest_door_gap, 4),
            reached_transition_zone=reached_transition,
            reached_door_closure_zone=reached_door_zone,
            reserve_deployed=reserve_deployed,
            authoritative_transition_start_x=round(self.transition_zone_x_start, 4),
            authoritative_door_start_x=round(self.door_zone_x_start, 4),
            boundary_source=self.boundary_source,
        )

    def deploy_door_seal(
        self,
        world_state: Any,
        space_engine: Any,
        qty_mgr: Any,
        door_seal_skus: List[CargoSKU],
        contact_graph: Optional[ContactGraph] = None,
        max_deploy_items: Optional[int] = None,
    ) -> DoorDeploymentResult:
        """
        Actively plans and places DoorReservePool cartons to cooperatively close the door zone.
        Pushes cargo past door_closure_start_x, covers the front face, and eliminates residual gap.
        Dynamically adapts anchor sampling and item capacity across arbitrary container dimensions.
        """
        from backend.solver_v2.orientation.manager import OrientationEngine

        # Dynamic capacity calculation based on container dimensions and door zone volume
        if max_deploy_items is None or max_deploy_items <= 0:
            door_len = max(0.5, self.container.Lx - self.door_zone_x_start)
            min_box_vol = min((s.box.volume for s in door_seal_skus), default=0.03) if door_seal_skus else 0.03
            est_capacity = int(math.ceil((door_len * self.container.Ly * self.container.Lz * 0.85) / max(1e-4, min_box_vol)))
            effective_max_items = max(60, est_capacity)
        else:
            effective_max_items = max_deploy_items

        eps = self.geom_epsilon
        cur_max_x = world_state.max_x

        init_report = self.evaluate_door_readiness(
            world_state.placements,
            contact_graph=contact_graph,
            reserve_deployed=qty_mgr.get_reserve_deployed(),
            has_door_reserve_pool=True,
        )

        closure_before = init_report.door_closure_coverage
        largest_gap_before = init_report.largest_door_gap
        door_occ_before = init_report.door_zone_occupancy

        # Check if cargo reached transition zone
        if cur_max_x < (self.transition_zone_x_start - eps):
            return DoorDeploymentResult(
                door_phase_started=False,
                door_phase_start_x=round(cur_max_x, 4),
                door_anchor_count=0,
                door_candidates_generated=0,
                door_candidates_valid=0,
                door_candidates_rejected_by_reason={},
                door_placements=[],
                reserve_deployed_by_sku={s.sku_id: 0 for s in door_seal_skus},
                reserve_remaining_by_sku={
                    s.sku_id: qty_mgr.get_remaining(s.sku_id, context=PlacementContext.DOOR_SEAL)
                    for s in door_seal_skus
                },
                reserve_deployed=0,
                reserve_remaining=qty_mgr.get_reserve_remaining(),
                closure_before=closure_before,
                closure_after=closure_before,
                largest_gap_before=largest_gap_before,
                largest_gap_after=largest_gap_before,
                door_occupancy_before=door_occ_before,
                door_occupancy_after=door_occ_before,
                authoritative_transition_start_x=round(self.transition_zone_x_start, 4),
                authoritative_door_start_x=round(self.door_zone_x_start, 4),
                boundary_source=self.boundary_source,
            )

        door_phase_started = True
        door_phase_start_x = cur_max_x
        deployed_placements: List[Placement] = []
        rejected_by_reason: Dict[str, int] = {}
        total_cand_gen = 0
        total_cand_val = 0

        ori_engine = OrientationEngine()
        step_base = len(world_state.placements)
        anchors_set: Set[Tuple[float, float, float]] = set()

        while len(deployed_placements) < effective_max_items:
            # 1. Check remaining reserve SKUs
            eligible_skus = [
                s for s in door_seal_skus
                if qty_mgr.get_remaining(s.sku_id, context=PlacementContext.DOOR_SEAL) > 0
            ]
            if not eligible_skus:
                break

            # 2. Extract front anchors from current placements
            anchors_set.clear()

            front_threshold = max(0.0, world_state.max_x - 0.6)
            existing_front_placements = [
                p for p in world_state.placements
                if p.max_x >= front_threshold - eps
            ]

            if existing_front_placements:
                for p in existing_front_placements:
                    anchors_set.add((round(p.max_x, 4), round(p.min_y, 4), round(p.min_z, 4)))
                    anchors_set.add((round(p.max_x, 4), round(p.min_y, 4), round(p.max_z, 4)))
                    anchors_set.add((round(p.max_x, 4), round(p.max_y, 4), round(p.min_z, 4)))
                    anchors_set.add((round(p.max_x, 4), round(p.max_y, 4), round(p.max_z, 4)))
                    anchors_set.add((round(p.max_x, 4), round(p.min_y, 4), 0.0))

            # Extreme points in front region
            for ep in space_engine.extreme_points:
                if ep.x >= self.transition_zone_x_start - 0.2:
                    anchors_set.add((round(ep.x, 4), round(ep.y, 4), round(ep.z, 4)))

            # Floor anchors dynamically sampled across width at front X
            max_x_seen = max((p.max_x for p in world_state.placements), default=cur_max_x)
            min_dy = min((min(s.box.x, s.box.y) for s in eligible_skus), default=0.30)
            y_step = max(0.10, min(0.35, min_dy))
            num_y_steps = max(2, int(math.ceil(self.container.Ly / y_step)))
            y_samples = set([round(k * (self.container.Ly / num_y_steps), 4) for k in range(num_y_steps)])
            for s in eligible_skus:
                for dy_cand in [s.box.x, s.box.y]:
                    if dy_cand < self.container.Ly:
                        curr_y = 0.0
                        while curr_y < self.container.Ly - 0.05:
                            y_samples.add(round(curr_y, 4))
                            curr_y += dy_cand

            for y_samp in sorted(y_samples):
                if y_samp < self.container.Ly - 0.05:
                    anchors_set.add((round(max_x_seen, 4), round(y_samp, 4), 0.0))

            door_anchors = [
                Point3D(x=ax, y=ay, z=az)
                for ax, ay, az in anchors_set
                if 0.0 <= ax <= self.container.Lx - 0.05
                and 0.0 <= ay <= self.container.Ly - 0.05
                and 0.0 <= az <= self.container.Lz - 0.05
            ]

            # Sort: lowest X first, then lowest Z, then lowest Y
            door_anchors.sort(key=lambda pt: (round(pt.x, 3), round(pt.z, 3), round(pt.y, 3)))

            # 3. Generate and score candidates
            best_candidate = None
            best_score = -float("inf")

            for anch in door_anchors:
                for sku in eligible_skus:
                    oris = sku.orientation_policy.get_legal_orientations(sku.box, context=PlacementContext.DOOR_SEAL)
                    for ori in oris:
                        total_cand_gen += 1
                        cand_aabb = AABB(
                            anch.x, anch.y, anch.z,
                            anch.x + ori.dx, anch.y + ori.dy, anch.z + ori.dz
                        )

                        # A. Boundary check
                        if (cand_aabb.max_x > self.container.Lx + eps or
                            cand_aabb.max_y > self.container.Ly + eps or
                            cand_aabb.max_z > self.container.Lz + eps):
                            rejected_by_reason["OUT_OF_BOUNDS"] = rejected_by_reason.get("OUT_OF_BOUNDS", 0) + 1
                            continue

                        # B. Collision check
                        intersecting = world_state.spatial_index.query_intersect(cand_aabb, eps=eps)
                        if intersecting:
                            rejected_by_reason["COLLISION"] = rejected_by_reason.get("COLLISION", 0) + 1
                            continue

                        # C. Support check
                        is_floor = (anch.z <= eps)
                        if not is_floor:
                            support_box = AABB(
                                anch.x, anch.y, anch.z - 0.05,
                                anch.x + ori.dx, anch.y + ori.dy, anch.z + eps
                            )
                            touching_lower = world_state.spatial_index.query_intersect(support_box, eps=eps)
                            total_sup_area = 0.0
                            for item in touching_lower:
                                p_below = item.data
                                if p_below and abs((p_below.position.z + p_below.orientation.dz) - anch.z) <= eps:
                                    ox = max(0.0, min(cand_aabb.max_x, p_below.max_x) - max(cand_aabb.min_x, p_below.min_x))
                                    oy = max(0.0, min(cand_aabb.max_y, p_below.max_y) - max(cand_aabb.min_y, p_below.min_y))
                                    total_sup_area += ox * oy
                            base_area = ori.dx * ori.dy
                            sup_ratio = (total_sup_area / base_area) if base_area > 0 else 0.0
                            if sup_ratio < sku.stacking_policy.min_support_ratio - eps:
                                rejected_by_reason["INSUFFICIENT_SUPPORT"] = rejected_by_reason.get("INSUFFICIENT_SUPPORT", 0) + 1
                                continue

                        # D. Anti-toppling check
                        slenderness = ori.dz / max(1e-4, ori.dx)
                        if slenderness > 3.0 and not is_floor:
                            rejected_by_reason["ANTI_TOPPLING"] = rejected_by_reason.get("ANTI_TOPPLING", 0) + 1
                            continue

                        total_cand_val += 1

                        # Score candidate
                        prog_score = (cand_aabb.max_x / self.container.Lx) * 500.0
                        floor_score = 100.0 if is_floor else 0.0
                        y_score = 50.0 * (1.0 - (cand_aabb.min_y / self.container.Ly))
                        vol_score = ori.volume * 500.0
                        score = prog_score + floor_score + y_score + vol_score

                        if score > best_score:
                            best_score = score
                            best_candidate = (sku, anch, ori)

            if best_candidate is None:
                break

            # Commit the best candidate
            c_sku, c_pos, c_ori = best_candidate
            p_idx = step_base + len(deployed_placements)
            p_obj = Placement(
                placement_id=f"p_{p_idx:04d}_{c_sku.sku_id}_door",
                instance_id=f"inst_door_{p_idx:04d}",
                sku_id=c_sku.sku_id,
                position=c_pos,
                orientation=c_ori,
                weight_kg=c_sku.weight_kg,
                step_index=p_idx,
                context=PlacementContext.DOOR_SEAL,
            )

            world_state.commit(p_obj)
            space_engine.on_placement_committed(p_obj)
            qty_mgr.record_placement(c_sku.sku_id, context=PlacementContext.DOOR_SEAL)
            deployed_placements.append(p_obj)

            # Check if door readiness criteria are fully satisfied
            check_rep = self.evaluate_door_readiness(
                world_state.placements,
                contact_graph=contact_graph,
                reserve_deployed=qty_mgr.get_reserve_deployed(),
                has_door_reserve_pool=True,
            )

            if check_rep.is_door_ready and len(deployed_placements) >= 6:
                if check_rep.largest_door_gap <= 0.40 and check_rep.door_zone_occupancy >= 0.08:
                    break

        final_readiness = self.evaluate_door_readiness(
            world_state.placements,
            contact_graph=contact_graph,
            reserve_deployed=qty_mgr.get_reserve_deployed(),
            has_door_reserve_pool=True,
        )

        reserve_dep_by_sku = {}
        reserve_rem_by_sku = {}
        for s in door_seal_skus:
            st = qty_mgr.get_state(s.sku_id)
            reserve_dep_by_sku[s.sku_id] = st.reserve_deployed if st else 0
            reserve_rem_by_sku[s.sku_id] = st.reserve_remaining if st else 0

        return DoorDeploymentResult(
            door_phase_started=door_phase_started,
            door_phase_start_x=round(door_phase_start_x, 4),
            door_anchor_count=len(anchors_set),
            door_candidates_generated=total_cand_gen,
            door_candidates_valid=total_cand_val,
            door_candidates_rejected_by_reason=rejected_by_reason,
            door_placements=deployed_placements,
            reserve_deployed_by_sku=reserve_dep_by_sku,
            reserve_remaining_by_sku=reserve_rem_by_sku,
            reserve_deployed=qty_mgr.get_reserve_deployed(),
            reserve_remaining=qty_mgr.get_reserve_remaining(),
            closure_before=round(closure_before, 4),
            closure_after=round(final_readiness.door_closure_coverage, 4),
            largest_gap_before=round(largest_gap_before, 4),
            largest_gap_after=round(final_readiness.largest_door_gap, 4),
            door_occupancy_before=round(door_occ_before, 4),
            door_occupancy_after=round(final_readiness.door_zone_occupancy, 4),
            authoritative_transition_start_x=round(self.transition_zone_x_start, 4),
            authoritative_door_start_x=round(self.door_zone_x_start, 4),
            boundary_source=self.boundary_source,
        )

    def filter_door_skus(self, catalog: List[CargoSKU]) -> List[CargoSKU]:
        """
        Filters and prioritizes SKUs suitable for door closure sealing.
        Prefers SKUs configured with PackingRole.DOOR_SEAL or PackingRole.FLEXIBLE.
        """
        door_skus: List[CargoSKU] = []
        for sku in catalog:
            if (
                PackingRole.DOOR_SEAL in sku.packing_roles
                or PackingRole.FLEXIBLE in sku.packing_roles
                or PackingRole.MAIN_WALL in sku.packing_roles
            ):
                door_skus.append(sku)

        door_skus.sort(
            key=lambda s: (
                0 if PackingRole.DOOR_SEAL in s.packing_roles else 1,
                -(s.box.x * s.box.y),
            )
        )
        return door_skus
