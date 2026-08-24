"""
Load Propagation & Compression Engine for Solver V2 (Agent 07).
Implements fractional load distribution through the SupportGraph DAG:
- Upper cargo weights distributed downwards based on actual support/contact contributions.
- Accumulates multi-layer downward loads down to the container floor.
- Strictly never models compression solely by "number of boxes on top".
- Verifies StackingPolicy limits:
  - allow_stacking_on_top
  - max_bearing_kg
  - max_pressure_kg_m2
"""
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Set, Any, Callable
from collections import defaultdict
import math
import time

from backend.solver_v2.domain.models import Placement, CargoSKU, StackingPolicy
from backend.solver_v2.physics.support_graph import SupportGraph, SupportEdge, NODE_FLOOR
from backend.solver_v2.geometry.aabb import DEFAULT_GEOM_EPSILON


@dataclass
class ItemLoadReport:
    """Detailed load distribution and compression metrics for an individual placement."""
    placement_id: str
    sku_id: str
    own_weight_kg: float
    direct_upper_weight_kg: float      # Direct weight of items immediately resting on top
    accumulated_upper_load_kg: float   # Total propagated downward load from all levels above
    top_pressure_kg_m2: float          # accumulated_upper_load_kg / top surface area (m^2)
    max_bearing_kg: Optional[float]
    max_pressure_kg_m2: Optional[float]
    allow_stacking_on_top: bool
    is_bearing_exceeded: bool = False
    is_pressure_exceeded: bool = False
    is_no_stack_violated: bool = False
    violation_message: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return not (self.is_bearing_exceeded or self.is_pressure_exceeded or self.is_no_stack_violated)


@dataclass
class GlobalLoadReport:
    """Complete container load propagation report."""
    is_valid: bool
    total_cargo_weight_kg: float
    total_floor_load_kg: float
    item_reports: Dict[str, ItemLoadReport] = field(default_factory=dict)
    violations: List[str] = field(default_factory=list)


class LoadPropagationEngine:
    """
    Computes exact fractional load distribution and compression through the SupportGraph DAG.
    """

    def __init__(self, geom_epsilon: float = DEFAULT_GEOM_EPSILON):
        self.geom_epsilon = geom_epsilon

    def compute_loads(
        self,
        support_graph: SupportGraph,
        cargo_catalog: Dict[str, CargoSKU],
        timing_hook: Optional[Callable[[str, float], None]] = None,
    ) -> GlobalLoadReport:
        """
        Runs topological multi-layer load propagation down the SupportGraph.
        """
        placements = support_graph.placements
        if not placements:
            return GlobalLoadReport(
                is_valid=True,
                total_cargo_weight_kg=0.0,
                total_floor_load_kg=0.0,
                item_reports={},
                violations=[],
            )

        # 1. Topological order top-down
        propagation_started = time.perf_counter()
        top_down_order = support_graph.topological_order_top_down()

        # accumulated_load_on_top[pid]: total weight resting on top of pid
        accumulated_load_on_top: Dict[str, float] = defaultdict(float)
        direct_load_on_top: Dict[str, float] = defaultdict(float)
        floor_load_kg: float = 0.0

        for pid in top_down_order:
            if pid not in placements:
                continue

            p = placements[pid]
            w_own = p.weight_kg
            w_total_down = w_own + accumulated_load_on_top[pid]

            support_edges = support_graph.get_support_edges(pid)
            total_supp_area = sum(e.contact_area for e in support_edges)
            base_area = p.orientation.dx * p.orientation.dy

            if total_supp_area <= self.geom_epsilon:
                # Floating or unsupported item
                continue

            # Distribute downward load to lower items / floor proportionally to contact area
            for edge in support_edges:
                fraction = edge.contact_area / total_supp_area
                load_share = w_total_down * fraction
                direct_share = w_own * fraction

                if edge.lower_id == NODE_FLOOR:
                    floor_load_kg += load_share
                else:
                    accumulated_load_on_top[edge.lower_id] += load_share
                    direct_load_on_top[edge.lower_id] += direct_share

        if timing_hook is not None:
            timing_hook("load_propagation_ms", (time.perf_counter() - propagation_started) * 1000.0)

        # 2. Build ItemLoadReports and evaluate against StackingPolicy
        compression_started = time.perf_counter()
        item_reports: Dict[str, ItemLoadReport] = {}
        violations: List[str] = []
        is_global_valid = True

        for pid, p in placements.items():
            sku = cargo_catalog.get(p.sku_id)
            policy = sku.stacking_policy if sku else StackingPolicy()

            own_w = p.weight_kg
            direct_up_w = direct_load_on_top[pid]
            accum_up_w = accumulated_load_on_top[pid]
            top_area = p.orientation.dx * p.orientation.dy
            pressure = accum_up_w / top_area if top_area > 0 else 0.0

            is_bearing_exceeded = False
            is_pressure_exceeded = False
            is_no_stack_violated = False
            msg_parts = []

            # Check allow_stacking_on_top
            if not policy.allow_stacking_on_top and accum_up_w > self.geom_epsilon:
                is_no_stack_violated = True
                msg_parts.append(
                    f"Item '{pid}' (SKU: {p.sku_id}) forbids stacking on top, but has {accum_up_w:.1f}kg load"
                )

            # Declarative self/category compatibility is evaluated on actual SupportGraph edges.
            for edge in support_graph.get_supported_edges(pid):
                upper = placements.get(edge.upper_id)
                upper_sku = cargo_catalog.get(upper.sku_id) if upper is not None else None
                if upper_sku is None:
                    continue
                upper_category = upper_sku.cargo_class
                category_forbidden = upper_category in policy.forbidden_above_categories
                category_not_allowed = bool(policy.allowed_above_categories) and upper_category not in policy.allowed_above_categories
                self_forbidden = not policy.stack_on_self and upper.sku_id == p.sku_id
                if category_forbidden or category_not_allowed or self_forbidden:
                    is_no_stack_violated = True
                    reason = "self stacking forbidden" if self_forbidden else f"upper category {upper_category.value} forbidden"
                    msg_parts.append(
                        f"Item '{pid}' (SKU: {p.sku_id}) has incompatible upper item '{edge.upper_id}': {reason}"
                    )

            # Check max_bearing_kg
            if policy.max_bearing_kg is not None:
                if accum_up_w > policy.max_bearing_kg + self.geom_epsilon:
                    is_bearing_exceeded = True
                    msg_parts.append(
                        f"Item '{pid}' (SKU: {p.sku_id}) bearing load {accum_up_w:.1f}kg exceeds limit {policy.max_bearing_kg:.1f}kg"
                    )

            # Check max_pressure_kg_m2
            if policy.max_pressure_kg_m2 is not None:
                if pressure > policy.max_pressure_kg_m2 + self.geom_epsilon:
                    is_pressure_exceeded = True
                    msg_parts.append(
                        f"Item '{pid}' (SKU: {p.sku_id}) top pressure {pressure:.1f}kg/m² exceeds limit {policy.max_pressure_kg_m2:.1f}kg/m²"
                    )

            report = ItemLoadReport(
                placement_id=pid,
                sku_id=p.sku_id,
                own_weight_kg=own_w,
                direct_upper_weight_kg=direct_up_w,
                accumulated_upper_load_kg=accum_up_w,
                top_pressure_kg_m2=pressure,
                max_bearing_kg=policy.max_bearing_kg,
                max_pressure_kg_m2=policy.max_pressure_kg_m2,
                allow_stacking_on_top=policy.allow_stacking_on_top,
                is_bearing_exceeded=is_bearing_exceeded,
                is_pressure_exceeded=is_pressure_exceeded,
                is_no_stack_violated=is_no_stack_violated,
                violation_message="; ".join(msg_parts) if msg_parts else None,
            )

            item_reports[pid] = report
            if not report.is_valid:
                is_global_valid = False
                violations.extend(msg_parts)

        total_cargo_w = sum(p.weight_kg for p in placements.values())
        if timing_hook is not None:
            timing_hook("compression_validation_ms", (time.perf_counter() - compression_started) * 1000.0)

        return GlobalLoadReport(
            is_valid=is_global_valid,
            total_cargo_weight_kg=total_cargo_w,
            total_floor_load_kg=floor_load_kg,
            item_reports=item_reports,
            violations=violations,
        )
