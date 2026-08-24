from dataclasses import dataclass
from typing import Tuple

from backend.solver_v2.domain.models import ContainerSpec, Placement
from src.constraints.door import LONG_EDGE_FORWARD,SHORT_EDGE_FORWARD
from src.constraints.door.types import DoorWall
from .ReservedRegionManager import ReservedRegionManager


@dataclass(frozen=True)
class DoorPlacementValidation:
    valid: bool
    reasons: Tuple[str, ...]


class DoorPlacementValidator:
    def validate_wall(self, wall: DoorWall, placements: Tuple[Placement, ...], container: ContainerSpec,
                      reserved: ReservedRegionManager) -> DoorPlacementValidation:
        reasons = []
        if wall.orientation not in {SHORT_EDGE_FORWARD,LONG_EDGE_FORWARD,"MIXED_DOOR_ORIENTATION"}:
            reasons.append("DOOR_ORIENTATION_FORBIDDEN")
        if len(placements) != len(wall.placements):
            reasons.append("DOOR_PLACEMENT_COUNT_MISMATCH")
        for placement in placements:
            if placement.min_x < reserved.region.x1 - 1e-9 or placement.max_x > reserved.region.x2 + 1e-9:
                reasons.append("DOOR_ANCHOR_OUTSIDE_RESERVED_ZONE")
                break
            if placement.max_y > container.Ly + 1e-9 or placement.max_z > container.Lz + 1e-9:
                reasons.append("DOOR_ANCHOR_OUT_OF_BOUNDS")
                break
        return DoorPlacementValidation(not reasons, tuple(reasons))

    @staticmethod
    def validate_locked_operation(placement_id: str, locked_ids: frozenset, operation: str) -> DoorPlacementValidation:
        if placement_id in locked_ids and operation in {"MOVE", "ROTATE", "REPLACE"}:
            return DoorPlacementValidation(False, ("LOCKED_DOOR_WALL",))
        return DoorPlacementValidation(True, ())
