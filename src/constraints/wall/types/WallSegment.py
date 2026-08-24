from dataclasses import asdict, dataclass
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class WallSegment:
    segment_id: str
    x_range: Tuple[float, float]
    y_range: Tuple[float, float]
    z_range: Tuple[float, float]
    placement_ids: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]: return asdict(self)
