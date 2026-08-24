from dataclasses import asdict, dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class ReservedRegion:
    region_id: str
    x1: float
    x2: float
    reserved: bool = True
    purpose: str = "DOOR_WALL"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
