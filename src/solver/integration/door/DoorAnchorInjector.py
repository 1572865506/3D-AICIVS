from dataclasses import dataclass

from backend.solver_v2.world.state import WorldState
from .DoorPlacementValidator import DoorPlacementValidator
from .ReservedRegionManager import ReservedRegionManager
from .types import PreparedPackingInput


@dataclass(frozen=True)
class InjectionResult:
    committed: int
    locked_ids: frozenset


class DoorAnchorInjector:
    def inject(self, state: WorldState, prepared: PreparedPackingInput) -> InjectionResult:
        manager = ReservedRegionManager(prepared.door_context.blocked_area)
        for placement in prepared.door_context.anchor_placements:
            if not manager.validate(placement, "DOOR_WALL").valid:
                raise ValueError("DOOR_ANCHOR_OUTSIDE_RESERVED_ZONE")
            state.commit(placement)
        ids = frozenset(p.placement_id for p in prepared.door_context.anchor_placements)
        return InjectionResult(len(ids), ids)
