from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class PlacementPlan:
    placements: Tuple[object, ...]
    sequence: Tuple[str, ...]

    def to_dict(self): return {"placement_count": len(self.placements), "sequence": list(self.sequence)}
