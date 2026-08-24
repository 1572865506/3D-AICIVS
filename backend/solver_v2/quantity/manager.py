"""
Quantity and Spatial Reservation Management for Solver V2 (Agent 04 / BLK-002B).
Handles:
1. SKU Quantity Planning: required, min_quantity, max_quantity, and elasticity.
2. Door Reserve Pool & Door Excess: Distinguishes reserved closure quantity from excess general cargo.
3. Accurate deployment tracking: reserve_deployed, reserve_placed_in_door_zone, excess_placed_in_main, excess_placed_in_transition.
4. Spatial Reservations: 3D bounding box reservations for specific roles (e.g. DOOR_SEAL, TOP_FILL).
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Set, Any
import copy

from backend.solver_v2.domain.models import (
    CargoSKU,
    QuantityPlan,
    PackingRole,
    Placement,
    ContainerSpec,
    PlacementContext,
)
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.door.elastic_frontier import DoorReserveAllocation


@dataclass
class SKUQuantityState:
    """Live state tracking for a single SKU's quantity."""
    sku_id: str
    required: int
    min_quantity: int
    max_quantity: int
    is_elastic: bool
    load_priority: int = 0
    placed_count: int = 0
    reserved_door_qty: int = 0
    excess_door_qty: int = 0
    placed_in_main: int = 0
    placed_in_transition: int = 0
    placed_in_door: int = 0

    @property
    def remaining_required(self) -> int:
        return max(0, self.required - self.placed_count)

    @property
    def remaining_max(self) -> int:
        return max(0, self.max_quantity - self.placed_count)

    @property
    def can_place_more(self) -> bool:
        return self.placed_count < self.max_quantity

    @property
    def is_min_satisfied(self) -> bool:
        return self.placed_count >= self.min_quantity

    @property
    def is_required_satisfied(self) -> bool:
        return self.placed_count >= self.required

    @property
    def reserve_deployed(self) -> int:
        """How many reserved items have been deployed in DOOR_SEAL phase."""
        return self.placed_in_door

    @property
    def reserve_remaining(self) -> int:
        """How many reserved items are still awaiting deployment."""
        if self.reserved_door_qty <= 0:
            return 0
        return max(0, self.reserved_door_qty - self.placed_in_door)

    def remaining_for_context(self, context: PlacementContext) -> int:
        """
        Returns number of items that can be placed in the specified phase context.
        In DOOR_SEAL phase: remaining reserved + remaining unplaced.
        In other phases (FOUNDATION, MAIN_WALL, GAP_FILL, TOP_FILL): only excess can be placed.
        """
        rem_max = self.remaining_max
        if rem_max <= 0:
            return 0

        if context == PlacementContext.DOOR_SEAL:
            return rem_max

        if self.reserved_door_qty > 0:
            # Can only place up to excess_door_qty in non-door phases
            non_door_placed = self.placed_in_main + self.placed_in_transition
            rem_excess = max(0, self.excess_door_qty - non_door_placed)
            return min(rem_max, rem_excess)

        return rem_max


class QuantityManager:
    """
    Tracks and enforces SKU quantity quotas, elastic allocations, and door reserve pool separation.
    """

    def __init__(self, cargo_list: List[CargoSKU]):
        self._states: Dict[str, SKUQuantityState] = {}
        for c in cargo_list:
            max_q = c.quantity.max_quantity if c.quantity.max_quantity is not None else c.quantity.required
            self._states[c.sku_id] = SKUQuantityState(
                sku_id=c.sku_id,
                required=c.quantity.required,
                min_quantity=c.quantity.min_quantity,
                max_quantity=max_q,
                is_elastic=c.quantity.is_elastic,
                load_priority=(c.cargo_profile.placement_policy.load_priority if c.cargo_profile is not None else 0),
                placed_count=0,
                reserved_door_qty=0,
                excess_door_qty=max_q,
                placed_in_main=0,
                placed_in_transition=0,
                placed_in_door=0,
            )
        self._history: List[Tuple[str, Optional[PlacementContext]]] = []

    def set_door_reserve_allocations(self, allocations: Dict[str, DoorReserveAllocation]) -> None:
        """Applies algorithmic door reserve and excess pool allocations."""
        for sku_id, alloc in allocations.items():
            if sku_id in self._states:
                state = self._states[sku_id]
                state.reserved_door_qty = alloc.reserved_qty
                state.excess_door_qty = alloc.excess_qty

    def get_state(self, sku_id: str) -> Optional[SKUQuantityState]:
        return self._states.get(sku_id)

    def get_remaining(self, sku_id: str, context: Optional[PlacementContext] = None) -> int:
        state = self._states.get(sku_id)
        if not state:
            return 0
        if context is not None:
            return state.remaining_for_context(context)
        return state.remaining_max

    def can_place(self, sku_id: str, context: Optional[PlacementContext] = None) -> bool:
        state = self._states.get(sku_id)
        if not state:
            return False
        if context is not None:
            return state.remaining_for_context(context) > 0
        return state.can_place_more

    def record_placement(self, sku_id: str, context: Optional[PlacementContext] = None) -> None:
        state = self._states.get(sku_id)
        if not state:
            raise KeyError(f"Unknown SKU '{sku_id}'")
        state.placed_count += 1
        if context == PlacementContext.DOOR_SEAL:
            state.placed_in_door += 1
        elif context == PlacementContext.GAP_FILL:
            state.placed_in_transition += 1
        else:
            state.placed_in_main += 1
        self._history.append((sku_id, context))

    def rollback_placement(self) -> str:
        if not self._history:
            raise IndexError("Cannot rollback quantity: history empty")
        sku_id, context = self._history.pop()
        state = self._states[sku_id]
        state.placed_count = max(0, state.placed_count - 1)
        if context == PlacementContext.DOOR_SEAL:
            state.placed_in_door = max(0, state.placed_in_door - 1)
        elif context == PlacementContext.GAP_FILL:
            state.placed_in_transition = max(0, state.placed_in_transition - 1)
        else:
            state.placed_in_main = max(0, state.placed_in_main - 1)
        return sku_id

    def all_required_satisfied(self) -> bool:
        """Returns True if every non-elastic SKU has achieved required quantity."""
        for state in self._states.values():
            if not state.is_elastic and not state.is_required_satisfied:
                return False
        return True

    def all_min_satisfied(self) -> bool:
        """Returns True if every SKU has achieved its minimum quantity."""
        return all(s.is_min_satisfied for s in self._states.values())

    def get_reserve_requested(self) -> int:
        return sum(s.reserved_door_qty for s in self._states.values())

    def get_reserve_deployed(self) -> int:
        return sum(s.placed_in_door for s in self._states.values())

    def get_reserve_remaining(self) -> int:
        return sum(s.reserve_remaining for s in self._states.values())

    def get_excess_placed_in_main(self) -> int:
        return sum(s.placed_in_main for s in self._states.values() if s.reserved_door_qty > 0)

    def get_excess_placed_in_transition(self) -> int:
        return sum(s.placed_in_transition for s in self._states.values() if s.reserved_door_qty > 0)

    def get_sku_priorities(self, context: Optional[PlacementContext] = None) -> List[str]:
        """
        Sorts SKU IDs by placement priority:
        1. Non-elastic SKUs with remaining required quota (highest priority).
        2. In MAIN_WALL: non-door required SKUs preferred over door excess items.
        3. Elastic SKUs with remaining required quota.
        4. SKUs with optional additional quota.
        """
        def priority_key(state: SKUQuantityState) -> Tuple[int, int, int, int]:
            rem = state.remaining_for_context(context) if context is not None else state.remaining_max
            if rem <= 0:
                return (4, 0, 0, 0)

            # In MAIN_WALL context, prioritize non-door required SKUs so tiny door excess doesn't starve main body
            if context in (PlacementContext.FOUNDATION, PlacementContext.MAIN_WALL):
                if state.reserved_door_qty == 0 and state.remaining_required > 0 and not state.is_elastic:
                    group = 0  # Urgent core main SKU
                elif state.remaining_required > 0 and not state.is_elastic:
                    group = 1  # Required non-elastic with door excess
                elif state.remaining_required > 0:
                    group = 2  # Elastic required
                else:
                    group = 3  # Optional extra
            elif context == PlacementContext.DOOR_SEAL:
                # In DOOR_SEAL context, prioritize door reserve SKUs first
                if state.reserved_door_qty > 0 and state.reserve_remaining > 0:
                    group = 0
                elif state.remaining_required > 0:
                    group = 1
                else:
                    group = 2
            else:
                if state.remaining_required > 0 and not state.is_elastic:
                    group = 0
                elif state.remaining_required > 0:
                    group = 1
                else:
                    group = 2

            return (group, -state.load_priority, -state.remaining_required, -rem)

        sorted_states = sorted(self._states.values(), key=priority_key)
        if context is not None:
            return [s.sku_id for s in sorted_states if s.remaining_for_context(context) > 0]
        return [s.sku_id for s in sorted_states if s.can_place_more]


@dataclass
class SpatialReservation:
    """A 3D spatial region reserved exclusively for specific SKUs or PackingRoles."""
    reservation_id: str
    aabb: AABB
    reserved_for_sku: Optional[str] = None
    reserved_for_role: Optional[PackingRole] = None
    priority: int = 10
    is_active: bool = True

    def is_allowed(self, sku: CargoSKU) -> bool:
        """Returns True if the given SKU is permitted to occupy this reserved space."""
        if self.reserved_for_sku and sku.sku_id == self.reserved_for_sku:
            return True
        if self.reserved_for_role and (self.reserved_for_role in sku.packing_roles):
            return True
        return False


class SpatialReservationManager:
    """
    Manages 3D bounding box reservations (e.g. door zone for door seals, roof for top-fill).
    """

    def __init__(self, geom_epsilon: float = DEFAULT_GEOM_EPSILON):
        self.geom_epsilon = geom_epsilon
        self._reservations: Dict[str, SpatialReservation] = {}

    def add_reservation(self, reservation: SpatialReservation) -> None:
        self._reservations[reservation.reservation_id] = reservation

    def remove_reservation(self, reservation_id: str) -> None:
        if reservation_id in self._reservations:
            del self._reservations[reservation_id]

    def update_door_reservation(self, container: ContainerSpec, door_zone_length_m: float) -> None:
        """Dynamically adjusts door zone reservation boundary."""
        door_x_start = max(0.0, container.Lx - door_zone_length_m)
        door_aabb = AABB(
            min_x=door_x_start,
            min_y=0.0,
            min_z=0.0,
            max_x=container.Lx,
            max_y=container.Ly,
            max_z=container.Lz,
        )
        self._reservations["DOOR_ZONE_RESERVATION"] = SpatialReservation(
            reservation_id="DOOR_ZONE_RESERVATION",
            aabb=door_aabb,
            reserved_for_role=PackingRole.DOOR_SEAL,
            priority=10,
            is_active=True,
        )

    def reserve_door_zone(
        self,
        container: ContainerSpec,
        door_zone_length_m: Optional[float] = None,
    ) -> None:
        length = door_zone_length_m or container.door_zone_length_m
        self.update_door_reservation(container, length)

    def check_candidate_conflict(
        self,
        candidate_aabb: AABB,
        sku: CargoSKU,
    ) -> Tuple[bool, Optional[str]]:
        eps = self.geom_epsilon
        for res in self._reservations.values():
            if not res.is_active:
                continue

            if candidate_aabb.intersects(res.aabb, eps=eps):
                if not res.is_allowed(sku):
                    return False, (
                        f"Spatial reservation conflict: Placement of SKU '{sku.sku_id}' "
                        f"intersects reservation '{res.reservation_id}' reserved for "
                        f"{res.reserved_for_sku or res.reserved_for_role}"
                    )
        return True, None
