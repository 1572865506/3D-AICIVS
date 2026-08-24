from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Tuple

from .DoorZone import DoorZone


@dataclass(frozen=True)
class DoorConstraint:
    status: str
    reserved_zone: DoorZone
    forced_orientation: Dict[str, str]
    priority_cargo: Tuple[str, ...]
    blocked_positions: Tuple[Dict[str, float], ...]
    inventory_reservation: Dict[str, int] = field(default_factory=dict)
    reason: str = ""
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["reserved_zone"] = self.reserved_zone.to_dict()
        return data
