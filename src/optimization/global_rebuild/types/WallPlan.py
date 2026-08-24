from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class WallPlan:
    wall_order: Tuple[str, ...]
    wall_count: int
    reconstructed: bool
    door_wall_regenerated: bool = True

    def to_dict(self): return {"wall_order": list(self.wall_order), "wall_count": self.wall_count, "reconstructed": self.reconstructed,
                               "door_wall_regenerated":self.door_wall_regenerated}
