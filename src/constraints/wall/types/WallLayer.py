from dataclasses import asdict, dataclass
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class WallLayer:
    layer_index: int
    z_start: float
    z_end: float
    placement_ids: Tuple[str, ...]
    coverage: float
    gap_count: int
    largest_gap: float

    def to_dict(self) -> Dict[str, Any]: return asdict(self)
