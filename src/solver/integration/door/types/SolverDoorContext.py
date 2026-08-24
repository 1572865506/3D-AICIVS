from dataclasses import asdict, dataclass
from typing import Any, Dict, Tuple

from backend.solver_v2.domain.models import Placement
from src.constraints.door.types import DoorZone
from .DoorAnchor import DoorAnchor
from .ReservedRegion import ReservedRegion


@dataclass(frozen=True)
class SolverDoorContext:
    door_zone: DoorZone
    reserved_placements: Tuple[Placement, ...]
    forced_orientation: Dict[str, str]
    blocked_area: ReservedRegion
    anchor_placements: Tuple[Placement, ...]
    priority_cargo: Tuple[str, ...]
    door_anchor: DoorAnchor

    def to_dict(self) -> Dict[str, Any]:
        return {
            "door_zone": self.door_zone.to_dict(),
            "reserved_placements": [p.placement_id for p in self.reserved_placements],
            "forced_orientation": dict(self.forced_orientation),
            "blocked_area": self.blocked_area.to_dict(),
            "anchor_placements": [p.placement_id for p in self.anchor_placements],
            "priority_cargo": list(self.priority_cargo),
            "door_anchor": self.door_anchor.to_dict(),
        }
