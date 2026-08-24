from dataclasses import dataclass
from typing import Dict, Tuple

from backend.solver_v2.domain.models import Placement
from backend.solver_v2.world.state import WorldState
from .DoorAnchorInjector import DoorAnchorInjector
from .DoorPlacementValidator import DoorPlacementValidator
from .ReservedRegionManager import ReservedRegionManager
from .types import PreparedPackingInput


@dataclass(frozen=True)
class CommitResult:
    placements: Tuple[Placement, ...]
    locked_ids: frozenset
    support_links: Tuple[Dict[str, str], ...]


class DoorWallCommitter:
    """Atomic external commit: anchors first, unchanged main-solver placements second."""

    def __init__(self):
        self.validator = DoorPlacementValidator()

    def commit(self, prepared: PreparedPackingInput, main_placements) -> CommitResult:
        main_placements = tuple(main_placements)
        state = WorldState(prepared.original_container, list(prepared.original_cargo))
        injected = DoorAnchorInjector().inject(state, prepared)
        reserved = ReservedRegionManager(prepared.door_context.blocked_area)
        wall_validation = self.validator.validate_wall(
            prepared.door_wall, prepared.door_context.anchor_placements,
            prepared.original_container, reserved,
        )
        if not wall_validation.valid:
            raise ValueError(";".join(wall_validation.reasons))
        for placement in main_placements:
            region_result = reserved.validate(placement)
            if not region_result.valid:
                raise ValueError(region_result.reason)
            state.commit(placement)
        support_links = self._support_links(prepared.door_context.anchor_placements, main_placements)
        return CommitResult(tuple(state.placements), injected.locked_ids, support_links)

    @staticmethod
    def _support_links(doors, mains):
        links = []
        boundary = min(p.min_x for p in doors)
        for main in mains:
            if abs(main.max_x - boundary) > 1e-6:
                continue
            for door in doors:
                y_touch = min(main.max_y, door.max_y) - max(main.min_y, door.min_y) > 1e-9
                z_touch = min(main.max_z, door.max_z) - max(main.min_z, door.min_z) > 1e-9
                if y_touch and z_touch:
                    links.append({"from": main.placement_id, "to": door.placement_id, "type": "DOOR_WALL_SUPPORT", "push_allowed": "false"})
        return tuple(links)
