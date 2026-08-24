from dataclasses import asdict, dataclass
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class DoorAnchor:
    wall_id: str
    placement_ids: Tuple[str, ...]
    state: str = "LOCKED_DOOR_WALL"
    support_type: str = "DOOR_WALL_SUPPORT"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
