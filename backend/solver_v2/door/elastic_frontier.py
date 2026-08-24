"""
Elastic Door Reservation and Door Closure Feasibility Subsystem for Solver V2 (Agent 08 / BLK-002).
Provides:
1. Dynamic Door Reserve Pool & Door Excess separation based on real 3D carton geometry.
2. ElasticDoorFrontier: Dynamic boundary computation replacing static door zone lockout.
3. DoorClosureFeasibilityProbe: Ultra-fast probe evaluating FEASIBLE, RISKY, and INFEASIBLE candidate states.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
import math

from backend.solver_v2.domain.models import (
    ContainerSpec,
    CargoSKU,
    PackingRole,
    ZoneType,
    PlacementContext,
    Orientation3D,
)
from backend.solver_v2.geometry.aabb import DEFAULT_GEOM_EPSILON


class ProbeStatus(str, Enum):
    FEASIBLE = "FEASIBLE"
    RISKY = "RISKY"
    INFEASIBLE = "INFEASIBLE"


@dataclass(frozen=True)
class DoorReserveAllocation:
    """Quantity and depth allocation for a single Door SKU."""
    sku_id: str
    total_qty: int
    reserved_qty: int
    excess_qty: int
    unit_depth_m: float
    layer_capacity: int
    estimated_coverage_pct: float


@dataclass(frozen=True)
class ElasticDoorFrontierMetrics:
    """Quantitative metrics for the dynamic door frontier at current packing state."""
    required_door_volume: float
    required_door_depth: float
    minimum_closure_depth: float
    preferred_closure_depth: float
    transition_margin_m: float
    latest_safe_main_x: float
    transition_start_x: float
    door_closure_start_x: float
    door_reserve_total_qty: int
    door_excess_total_qty: int
    door_sku_remaining: Dict[str, int]


@dataclass(frozen=True)
class ProbeResult:
    """Result returned by DoorClosureFeasibilityProbe."""
    status: ProbeStatus
    candidate_max_x: float
    latest_safe_main_x: float
    remaining_depth: float
    required_depth: float
    estimated_wall_coverage: float
    penalty: float
    reason: Optional[str] = None


class ElasticDoorFrontier:
    """
    Manages dynamic door reservations and feasibility probes.
    Eliminates static door length lockout and coordinates cooperative packing.
    """

    def __init__(
        self,
        container: ContainerSpec,
        door_skus: List[CargoSKU],
        min_closure_layers: int = 1,
        preferred_closure_layers: int = 2,
        transition_margin_m: float = 0.50,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
    ):
        self.container = container
        self.geom_epsilon = geom_epsilon
        self.door_skus = door_skus
        self.door_sku_map = {s.sku_id: s for s in door_skus}
        self.min_closure_layers = min_closure_layers
        self.preferred_closure_layers = preferred_closure_layers
        self.transition_margin_m = transition_margin_m

        # Compute initial allocations
        self.allocations: Dict[str, DoorReserveAllocation] = self._compute_reserve_allocation()

    def _compute_reserve_allocation(self) -> Dict[str, DoorReserveAllocation]:
        """
        Computes the minimum door closure set based on container cross section and carton geometry.
        Cross section: Ly * Lz.
        """
        allocations: Dict[str, DoorReserveAllocation] = {}
        if not self.door_skus:
            return allocations

        cross_section_area = self.container.Ly * self.container.Lz
        if cross_section_area <= 0:
            return allocations

        for sku in self.door_skus:
            total_qty = sku.quantity.required
            w, d, h = sku.box.x, sku.box.y, sku.box.z

            # Calculate layer capacity in upright orientations
            # Ori A: dx=w, dy=d, dz=h
            cap_a = (math.floor(self.container.Ly / max(1e-4, d))) * (math.floor(self.container.Lz / max(1e-4, h)))
            depth_a = w

            # Ori B: dx=d, dy=w, dz=h
            cap_b = (math.floor(self.container.Ly / max(1e-4, w))) * (math.floor(self.container.Lz / max(1e-4, h)))
            depth_b = d

            # Choose orientation with best tiling capacity / reasonable depth
            if cap_b > 0 and (depth_b < depth_a or cap_a <= 0):
                layer_cap = max(1, cap_b)
                unit_depth = depth_b
                face_area = w * h
            else:
                layer_cap = max(1, cap_a)
                unit_depth = depth_a
                face_area = d * h

            # We reserve enough cartons for min_closure_layers to preferred_closure_layers, capped by total_qty
            # For multiple door SKUs, each contributes proportionally to the reserve pool
            num_door_skus = len(self.door_skus)
            share_of_cross_section = 1.0 / num_door_skus
            target_layer_share = max(1, int(math.ceil(layer_cap * share_of_cross_section)))

            # If the SKU is elastic (like SKU-14), it can reserve fewer if needed
            is_elastic = sku.quantity.is_elastic
            min_layers = 1 if is_elastic else self.min_closure_layers
            pref_layers = self.preferred_closure_layers

            # Target reserve quantity: min(total_qty, target_layer_share * pref_layers)
            # Ensure at least enough for 1 layer partition
            res_qty = min(total_qty, max(min_layers * target_layer_share, min(total_qty, pref_layers * target_layer_share)))
            
            # If total_qty is small (e.g. <= 20), reserve at most 50% so excess can flow to main
            if total_qty > 0 and res_qty >= total_qty and total_qty > 10:
                res_qty = max(min_layers * target_layer_share, int(total_qty * 0.4))

            excess_qty = max(0, total_qty - res_qty)
            cov_pct = min(100.0, (res_qty * face_area / cross_section_area) * 100.0)

            allocations[sku.sku_id] = DoorReserveAllocation(
                sku_id=sku.sku_id,
                total_qty=total_qty,
                reserved_qty=res_qty,
                excess_qty=excess_qty,
                unit_depth_m=unit_depth,
                layer_capacity=layer_cap,
                estimated_coverage_pct=round(cov_pct, 2),
            )

        return allocations

    def get_metrics(
        self,
        current_placed_door_counts: Optional[Dict[str, int]] = None,
    ) -> ElasticDoorFrontierMetrics:
        """
        Computes dynamic metrics and boundaries for current state.
        """
        placed_counts = current_placed_door_counts or {}
        lx = self.container.Lx

        door_sku_remaining: Dict[str, int] = {}
        total_reserve_remaining = 0
        total_excess_remaining = 0
        total_reserve_vol = 0.0
        total_remaining_reserve_depth = 0.0

        for sku_id, alloc in self.allocations.items():
            sku = self.door_sku_map[sku_id]
            placed = placed_counts.get(sku_id, 0)
            rem_total = max(0, alloc.total_qty - placed)
            door_sku_remaining[sku_id] = rem_total

            # How much of the reserve pool is still unplaced?
            # Cartons placed first consume excess, then reserve
            placed_excess = min(placed, alloc.excess_qty)
            rem_excess = max(0, alloc.excess_qty - placed_excess)
            placed_res = max(0, placed - alloc.excess_qty)
            rem_res = max(0, alloc.reserved_qty - placed_res)

            total_reserve_remaining += rem_res
            total_excess_remaining += rem_excess

            sku_vol = sku.box.volume
            total_reserve_vol += rem_res * sku_vol

            # Estimate required longitudinal depth for remaining reserve
            layers_needed = math.ceil(rem_res / max(1, alloc.layer_capacity))
            total_remaining_reserve_depth = max(total_remaining_reserve_depth, layers_needed * alloc.unit_depth_m)

        # Minimum closure depth: depth of at least 1 layer of reserved SKUs
        min_depth = max(0.20, total_remaining_reserve_depth * 0.7)
        # Preferred closure depth: comfortable depth for multi-layer closure
        pref_depth = max(min_depth + 0.20, total_remaining_reserve_depth * 1.2)

        # Ensure reasonable bounds relative to container length
        min_depth = min(min_depth, lx * 0.25)
        pref_depth = min(pref_depth, lx * 0.35)

        latest_safe_main_x = max(0.0, lx - min_depth)
        door_closure_start_x = max(0.0, lx - pref_depth)
        transition_start_x = max(0.0, door_closure_start_x - self.transition_margin_m)

        return ElasticDoorFrontierMetrics(
            required_door_volume=round(total_reserve_vol, 4),
            required_door_depth=round(total_remaining_reserve_depth, 4),
            minimum_closure_depth=round(min_depth, 4),
            preferred_closure_depth=round(pref_depth, 4),
            transition_margin_m=round(self.transition_margin_m, 4),
            latest_safe_main_x=round(latest_safe_main_x, 4),
            transition_start_x=round(transition_start_x, 4),
            door_closure_start_x=round(door_closure_start_x, 4),
            door_reserve_total_qty=total_reserve_remaining,
            door_excess_total_qty=total_excess_remaining,
            door_sku_remaining=door_sku_remaining,
        )

    def evaluate_probe(
        self,
        candidate_max_x: float,
        current_max_x: float,
        is_door_sku: bool,
        placed_door_counts: Optional[Dict[str, int]] = None,
        context: Optional[PlacementContext] = None,
    ) -> ProbeResult:
        """
        Fast probe evaluating feasibility of candidate placement.
        """
        metrics = self.get_metrics(placed_door_counts)
        lx = self.container.Lx
        eps = self.geom_epsilon

        # Door seal placements in DOOR_SEAL phase are allowed to advance up to Lx
        if is_door_sku and (context == PlacementContext.DOOR_SEAL or candidate_max_x > metrics.door_closure_start_x):
            if candidate_max_x <= lx + eps:
                rem_d = max(0.0, lx - candidate_max_x)
                return ProbeResult(
                    status=ProbeStatus.FEASIBLE,
                    candidate_max_x=candidate_max_x,
                    latest_safe_main_x=metrics.latest_safe_main_x,
                    remaining_depth=rem_d,
                    required_depth=metrics.minimum_closure_depth,
                    estimated_wall_coverage=95.0,
                    penalty=0.0,
                    reason=None,
                )
            else:
                return ProbeResult(
                    status=ProbeStatus.INFEASIBLE,
                    candidate_max_x=candidate_max_x,
                    latest_safe_main_x=metrics.latest_safe_main_x,
                    remaining_depth=0.0,
                    required_depth=metrics.minimum_closure_depth,
                    estimated_wall_coverage=0.0,
                    penalty=10000.0,
                    reason=f"Candidate exceeds container length ({candidate_max_x:.3f} > {lx:.3f})",
                )

        # For MAIN cargo (or DOOR_EXCESS participating in main/transition):
        # Must respect latest_safe_main_x
        rem_depth_after = lx - candidate_max_x

        if candidate_max_x > metrics.latest_safe_main_x + eps:
            # Encroaches into minimum closure depth: INFEASIBLE
            return ProbeResult(
                status=ProbeStatus.INFEASIBLE,
                candidate_max_x=candidate_max_x,
                latest_safe_main_x=metrics.latest_safe_main_x,
                remaining_depth=rem_depth_after,
                required_depth=metrics.minimum_closure_depth,
                estimated_wall_coverage=0.0,
                penalty=5000.0,
                reason=f"Candidate encroaches on dynamic door reservation (x_end={candidate_max_x:.3f} > safe_limit={metrics.latest_safe_main_x:.3f})",
            )
        elif candidate_max_x > metrics.door_closure_start_x + eps:
            # Between door_closure_start_x and latest_safe_main_x: RISKY
            overshoot = candidate_max_x - metrics.door_closure_start_x
            penalty = 30.0 + overshoot * 50.0
            return ProbeResult(
                status=ProbeStatus.RISKY,
                candidate_max_x=candidate_max_x,
                latest_safe_main_x=metrics.latest_safe_main_x,
                remaining_depth=rem_depth_after,
                required_depth=metrics.minimum_closure_depth,
                estimated_wall_coverage=80.0,
                penalty=penalty,
                reason=f"Candidate enters door transition zone (x_end={candidate_max_x:.3f} > closure_start={metrics.door_closure_start_x:.3f})",
            )
        else:
            # Completely safe
            return ProbeResult(
                status=ProbeStatus.FEASIBLE,
                candidate_max_x=candidate_max_x,
                latest_safe_main_x=metrics.latest_safe_main_x,
                remaining_depth=rem_depth_after,
                required_depth=metrics.minimum_closure_depth,
                estimated_wall_coverage=100.0,
                penalty=0.0,
                reason=None,
            )
