"""
Wall Stability Evaluator for Solver V2 (Agent 07).
Evaluates stability of transverse packing walls / vertical columns along the longitudinal X-axis:
- Wall slice grouping along X
- Height-to-thickness ratio (H / delta_X)
- Center of Mass (COM) and floor footprint
- Tipping moment resistance under transport deceleration
- Container rear inner wall and side wall bracing
"""
from enum import Enum
from typing import Dict, List, Tuple, Optional, Set, Any
import math

from backend.solver_v2.domain.models import Placement, Point3D, ContainerSpec
from backend.solver_v2.physics.contact_graph import ContactGraph, ContactDirection, NODE_FLOOR, NODE_WALL_BACK
from backend.solver_v2.stability.models import StabilityState, WallStabilityReport
from backend.solver_v2.geometry.aabb import DEFAULT_GEOM_EPSILON


class TransportMode(Enum):
    """
    Standard International Freight Acceleration Profiles (ISO 1496-1 / EN 12195-1 / IMO CTU Code):
    - ROAD_STANDARD (ISO/EN 12195-1): 0.5g braking
    - ROAD_EMERGENCY (EN 12195-1 / DIN EN 283): 0.8g emergency braking
    - RAIL_INTERMODAL (UIC 592 / AAR): 1.0g shunting / longitudinal impact
    - MARITIME_ISO1496 (IMO/ILO/UNECE CTU Code): 0.4g pitch/roll surge
    """
    ROAD_STANDARD = "ROAD_STANDARD"
    ROAD_EMERGENCY = "ROAD_EMERGENCY"
    RAIL_INTERMODAL = "RAIL_INTERMODAL"
    MARITIME_ISO1496 = "MARITIME_ISO1496"


TRANSPORT_ACCELERATION_G: Dict[TransportMode, float] = {
    TransportMode.ROAD_STANDARD: 0.5,
    TransportMode.ROAD_EMERGENCY: 0.8,
    TransportMode.RAIL_INTERMODAL: 1.0,
    TransportMode.MARITIME_ISO1496: 0.4,
}


class WallStabilityEvaluator:
    """
    Evaluates transverse wall stability and tipping risk along longitudinal container body.
    Supports configurable ISO 1496-1 / EN 12195-1 transport mode acceleration profiles.
    """

    def __init__(
        self,
        slice_tolerance_m: float = 0.3,
        deceleration_g: float = 0.5,
        transport_mode: Optional[TransportMode] = None,
        max_ht_ratio_warning: float = 3.0,
        max_ht_ratio_fatal: float = 4.0,
        min_tipping_moment_ratio_warning: float = 1.0,
        min_tipping_moment_ratio_fatal: float = 0.8,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
    ):
        self.slice_tolerance_m = slice_tolerance_m
        if transport_mode is not None:
            self.deceleration_g = TRANSPORT_ACCELERATION_G.get(transport_mode, deceleration_g)
        else:
            self.deceleration_g = deceleration_g
        self.transport_mode = transport_mode
        self.max_ht_ratio_warning = max_ht_ratio_warning
        self.max_ht_ratio_fatal = max_ht_ratio_fatal
        self.min_tipping_moment_ratio_warning = min_tipping_moment_ratio_warning
        self.min_tipping_moment_ratio_fatal = min_tipping_moment_ratio_fatal
        self.geom_epsilon = geom_epsilon

    def evaluate_walls(
        self,
        placements: List[Placement],
        contact_graph: ContactGraph,
        container: ContainerSpec,
    ) -> List[WallStabilityReport]:
        """
        Groups placements into transverse wall slices along X and computes stability reports.
        """
        if not placements:
            return []

        # 1. Group placements into wall slices by X intervals
        slices = self._group_placements_by_x_slices(placements)
        wall_reports: List[WallStabilityReport] = []

        for idx, (x_range, wall_items) in enumerate(slices):
            report = self._evaluate_single_wall(
                wall_id=f"wall_{idx:02d}",
                x_range=x_range,
                wall_items=wall_items,
                contact_graph=contact_graph,
                container=container,
            )
            wall_reports.append(report)

        return wall_reports

    def _group_placements_by_x_slices(
        self, placements: List[Placement]
    ) -> List[Tuple[Tuple[float, float], List[Placement]]]:
        """Groups placements with overlapping X spans into wall slices."""
        if not placements:
            return []

        sorted_p = sorted(placements, key=lambda p: (p.position.x, p.position.z))
        slices: List[Tuple[float, float, List[Placement]]] = []

        for p in sorted_p:
            px_min = p.position.x
            px_max = p.position.x + p.orientation.dx

            merged = False
            for i, (sx_min, sx_max, s_items) in enumerate(slices):
                # If placement X overlaps or is within slice_tolerance_m of the slice
                if not (px_max < sx_min - self.slice_tolerance_m or px_min > sx_max + self.slice_tolerance_m):
                    new_min = min(sx_min, px_min)
                    new_max = max(sx_max, px_max)
                    s_items.append(p)
                    slices[i] = (new_min, new_max, s_items)
                    merged = True
                    break

            if not merged:
                slices.append((px_min, px_max, [p]))

        return [((s[0], s[1]), s[2]) for s in slices]

    def _evaluate_single_wall(
        self,
        wall_id: str,
        x_range: Tuple[float, float],
        wall_items: List[Placement],
        contact_graph: ContactGraph,
        container: ContainerSpec,
    ) -> WallStabilityReport:
        eps = self.geom_epsilon
        x_min, x_max = x_range
        thickness_x = max(0.01, x_max - x_min)

        total_w = 0.0
        w_x, w_y, w_z = 0.0, 0.0, 0.0
        max_z = 0.0
        pids = [p.placement_id for p in wall_items]

        # Bracing checks
        rear_wall_braced = False
        side_left_braced = False
        side_right_braced = False

        for p in wall_items:
            w = p.weight_kg
            cx = p.position.x + p.orientation.dx / 2.0
            cy = p.position.y + p.orientation.dy / 2.0
            cz = p.position.z + p.orientation.dz / 2.0
            top_z = p.position.z + p.orientation.dz

            total_w += w
            w_x += w * cx
            w_y += w * cy
            w_z += w * cz
            max_z = max(max_z, top_z)

            pid = p.placement_id
            if contact_graph.has_boundary_bracing(pid, ContactDirection.BACK):
                rear_wall_braced = True
            if contact_graph.has_boundary_bracing(pid, ContactDirection.LEFT):
                side_left_braced = True
            if contact_graph.has_boundary_bracing(pid, ContactDirection.RIGHT):
                side_right_braced = True

        if total_w > 0:
            wall_com = Point3D(w_x / total_w, w_y / total_w, w_z / total_w)
        else:
            wall_com = Point3D(0.0, 0.0, 0.0)

        # Height to thickness ratio
        ht_ratio = max_z / thickness_x

        # Tipping Moment calculation:
        # Under longitudinal braking deceleration a_x = self.deceleration_g * g
        # Front toe pivot is at x_toe = x_max, z_pivot = 0.0
        # Restoring Moment: M_res = sum( m_i * g * (x_toe - cx_i) )
        # Overturning Moment: M_over = sum( m_i * (a_x) * cz_i ) = 0.5 * sum( m_i * g * cz_i )
        g = 9.81
        m_restore = 0.0
        m_overturn = 0.0

        for p in wall_items:
            m = p.weight_kg
            cx = p.position.x + p.orientation.dx / 2.0
            cz = p.position.z + p.orientation.dz / 2.0
            m_restore += m * g * max(0.0, x_max - cx)
            m_overturn += m * (self.deceleration_g * g) * cz

        tipping_moment_ratio = (m_restore / max(1e-4, m_overturn)) if m_overturn > 0 else 2.0

        # Evaluate Stability State
        reasons: List[str] = []
        if ht_ratio > self.max_ht_ratio_fatal and not rear_wall_braced and tipping_moment_ratio < self.min_tipping_moment_ratio_fatal:
            state = StabilityState.UNSTABLE
            reasons.append(f"Tall slender wall (H/T={ht_ratio:.1f} > {self.max_ht_ratio_fatal:.1f}) with high tipping risk (moment ratio={tipping_moment_ratio:.2f} < {self.min_tipping_moment_ratio_fatal:.2f})")
        elif ht_ratio > self.max_ht_ratio_warning and tipping_moment_ratio < self.min_tipping_moment_ratio_warning:
            state = StabilityState.WARNING
            reasons.append(f"High wall slenderness (H/T={ht_ratio:.1f} > {self.max_ht_ratio_warning:.1f}), tipping ratio={tipping_moment_ratio:.2f} < {self.min_tipping_moment_ratio_warning:.2f}")
        elif rear_wall_braced or (side_left_braced and side_right_braced):
            state = StabilityState.SELF_STABLE
            reasons.append(f"Wall firmly braced (H/T={ht_ratio:.1f}, tipping ratio={tipping_moment_ratio:.2f})")
        else:
            state = StabilityState.SUPPORTED_STABLE
            reasons.append(f"Stable transverse wall (H/T={ht_ratio:.1f}, tipping ratio={tipping_moment_ratio:.2f})")

        return WallStabilityReport(
            wall_id=wall_id,
            x_slice_range=x_range,
            placement_ids=pids,
            total_weight_kg=total_w,
            wall_com=wall_com,
            height_to_thickness_ratio=ht_ratio,
            tipping_moment_ratio=tipping_moment_ratio,
            rear_wall_braced=rear_wall_braced,
            stability_state=state,
            is_stable=(state != StabilityState.UNSTABLE),
            reasons=reasons,
        )
