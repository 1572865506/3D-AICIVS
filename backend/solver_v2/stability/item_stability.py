"""
Item-level Stability Evaluator for Solver V2 (Agent 07).
Evaluates individual placement stability:
- Support ratio and contact surface coverage
- 2D Center of Mass (COM) projection against support polygon
- Cantilever overhang / unsupported span
- Edge margin from COM to support boundaries
- Slenderness ratio (H / min(W, D)) and tipping risk
- Lateral contact and boundary wall bracing
"""
from typing import Dict, List, Tuple, Optional, Set, Any
import math

from backend.solver_v2.domain.models import Placement, CargoSKU, StackingPolicy, ContainerSpec
from backend.solver_v2.physics.contact_graph import ContactGraph, ContactDirection
from backend.solver_v2.physics.support_graph import SupportGraph, SupportEdge, NODE_FLOOR
from backend.solver_v2.stability.models import StabilityState, ItemStabilityReport
from backend.solver_v2.geometry.aabb import DEFAULT_GEOM_EPSILON


class ItemStabilityEvaluator:
    """
    Evaluates physical stability of individual cargo placements.
    """

    def __init__(self, geom_epsilon: float = DEFAULT_GEOM_EPSILON):
        self.geom_epsilon = geom_epsilon

    def evaluate_placement(
        self,
        placement: Placement,
        sku: Optional[CargoSKU],
        support_graph: SupportGraph,
        contact_graph: ContactGraph,
        container: ContainerSpec,
    ) -> ItemStabilityReport:
        """
        Evaluates stability metrics for a committed placement.
        """
        pid = placement.placement_id
        dx, dy, dz = placement.orientation.dx, placement.orientation.dy, placement.orientation.dz
        x, y, z = placement.position.x, placement.position.y, placement.position.z
        eps = self.geom_epsilon

        policy = sku.stacking_policy if sku else StackingPolicy()
        min_supp_ratio = policy.min_support_ratio
        max_span = policy.max_unsupported_span_m

        # COM 3D coordinates (assuming uniform mass distribution)
        com_x = x + dx / 2.0
        com_y = y + dy / 2.0
        com_z = z + dz / 2.0

        # Slenderness: Height / min(Length, Width)
        min_base_dim = max(0.01, min(dx, dy))
        slenderness = dz / min_base_dim

        # Lateral contacts & bracing
        lateral_contacts = contact_graph.get_lateral_contacts(pid)
        has_lateral_bracing = len(lateral_contacts) > 0
        lateral_count = len(lateral_contacts)

        # 1. Floor placement (z = 0)
        if abs(z) <= eps:
            edge_margin = min(dx / 2.0, dy / 2.0)
            reasons = ["Direct floor support"]
            if slenderness > 2.5:
                if has_lateral_bracing:
                    state = StabilityState.SUPPORTED_STABLE
                    reasons.append(f"High slenderness ({slenderness:.2f}), supported by lateral contacts")
                else:
                    state = StabilityState.WARNING
                    reasons.append(f"High slenderness ({slenderness:.2f}) without lateral bracing")
            elif has_lateral_bracing:
                state = StabilityState.SELF_STABLE
                reasons.append("Floor supported with lateral contacts")
            else:
                state = StabilityState.SELF_STABLE

            return ItemStabilityReport(
                placement_id=pid,
                sku_id=placement.sku_id,
                stability_state=state,
                support_ratio=1.0,
                com_projection_in_base=True,
                edge_margin_m=edge_margin,
                max_overhang_m=0.0,
                slenderness=slenderness,
                has_lateral_bracing=has_lateral_bracing,
                lateral_contact_count=lateral_count,
                is_stable=(state in (StabilityState.SELF_STABLE, StabilityState.SUPPORTED_STABLE, StabilityState.WARNING)),
                reasons=reasons,
            )

        # 2. Elevated placement (z > 0)
        support_edges = support_graph.get_support_edges(pid)
        base_area = dx * dy
        total_supp_area = sum(e.contact_area for e in support_edges)
        supp_ratio = (total_supp_area / base_area) if base_area > 0 else 0.0

        if not support_edges or supp_ratio < eps:
            return ItemStabilityReport(
                placement_id=pid,
                sku_id=placement.sku_id,
                stability_state=StabilityState.UNSTABLE,
                support_ratio=0.0,
                com_projection_in_base=False,
                edge_margin_m=-min(dx, dy) / 2.0,
                max_overhang_m=max(dx, dy),
                slenderness=slenderness,
                has_lateral_bracing=has_lateral_bracing,
                lateral_contact_count=lateral_count,
                is_stable=False,
                reasons=["Floating box: zero supporting contact"],
            )

        # Compute bounding rectangle of supporting contact interfaces
        supp_min_x = min(e.overlap_box.min_x for e in support_edges)
        supp_max_x = max(e.overlap_box.max_x for e in support_edges)
        supp_min_y = min(e.overlap_box.min_y for e in support_edges)
        supp_max_y = max(e.overlap_box.max_y for e in support_edges)

        # Overhang calculations along X and Y
        overhang_x = max(0.0, supp_min_x - x) + max(0.0, (x + dx) - supp_max_x)
        overhang_y = max(0.0, supp_min_y - y) + max(0.0, (y + dy) - supp_max_y)
        max_overhang = max(overhang_x, overhang_y)

        # COM projection check
        com_in_base = (
            (supp_min_x - eps <= com_x <= supp_max_x + eps) and
            (supp_min_y - eps <= com_y <= supp_max_y + eps)
        )

        # Edge margin: positive if inside, negative if outside
        margin_x = min(com_x - supp_min_x, supp_max_x - com_x)
        margin_y = min(com_y - supp_min_y, supp_max_y - com_y)
        edge_margin = min(margin_x, margin_y)

        # Determine Stability State
        reasons: List[str] = []
        state: StabilityState

        if supp_ratio < min_supp_ratio - eps:
            if has_lateral_bracing and supp_ratio >= min_supp_ratio * 0.7:
                state = StabilityState.CONDITIONALLY_STABLE
                reasons.append(f"Sub-threshold support ({supp_ratio*100:.1f}%), conditionally braced by lateral neighbors")
            else:
                state = StabilityState.UNSTABLE
                reasons.append(f"Insufficient support ratio ({supp_ratio*100:.1f}% < {min_supp_ratio*100:.1f}%)")

        elif not com_in_base or edge_margin < -eps:
            if has_lateral_bracing:
                state = StabilityState.CONDITIONALLY_STABLE
                reasons.append("COM outside support base, laterally braced")
            else:
                state = StabilityState.UNSTABLE
                reasons.append(f"COM outside support base (edge margin = {edge_margin:.3f}m)")

        elif max_overhang > max_span + eps:
            if has_lateral_bracing:
                state = StabilityState.CONDITIONALLY_STABLE
                reasons.append(f"Overhang ({max_overhang:.3f}m > {max_span:.3f}m), laterally braced")
            else:
                state = StabilityState.UNSTABLE
                reasons.append(f"Excessive unsupported overhang ({max_overhang:.3f}m > {max_span:.3f}m)")

        elif slenderness > 2.5:
            if has_lateral_bracing:
                state = StabilityState.SUPPORTED_STABLE
                reasons.append(f"High slenderness ({slenderness:.2f}), safely supported by lateral contacts")
            else:
                state = StabilityState.WARNING
                reasons.append(f"High slenderness ({slenderness:.2f}) without lateral bracing")

        elif has_lateral_bracing:
            state = StabilityState.SUPPORTED_STABLE
            reasons.append("Supported with lateral interlocking")
        else:
            state = StabilityState.SELF_STABLE
            reasons.append("Self-stable on lower surface")

        is_stable = (state in (StabilityState.SELF_STABLE, StabilityState.SUPPORTED_STABLE, StabilityState.WARNING))

        return ItemStabilityReport(
            placement_id=pid,
            sku_id=placement.sku_id,
            stability_state=state,
            support_ratio=supp_ratio,
            com_projection_in_base=com_in_base,
            edge_margin_m=edge_margin,
            max_overhang_m=max_overhang,
            slenderness=slenderness,
            has_lateral_bracing=has_lateral_bracing,
            lateral_contact_count=lateral_count,
            is_stable=is_stable,
            reasons=reasons,
        )
