from dataclasses import asdict, dataclass
from typing import Any, Dict, Tuple

from backend.solver_v2.domain.models import ContainerSpec


@dataclass(frozen=True)
class WallRegion:
    region_id: str
    x_start: float
    x_end: float
    region_type: str

    def to_dict(self) -> Dict[str, Any]: return asdict(self)


class WallRegionPlanner:
    def __init__(self, region_depth: float = 1.2, transition_depth: float = 1.2):
        self.region_depth = region_depth
        self.transition_depth = transition_depth

    def plan(self, container: ContainerSpec) -> Tuple[WallRegion, ...]:
        regions = []
        cursor = 0.0
        index = 1
        transition_start = max(0.0, container.Lx - self.transition_depth)
        while cursor < container.Lx - 1e-9:
            end = min(container.Lx, cursor + self.region_depth)
            kind = "TRANSITION_WALL" if cursor >= transition_start - 1e-9 else "MAIN_CARGO_WALL"
            regions.append(WallRegion(f"LOGICAL_WALL_{index:03d}", round(cursor, 6), round(end, 6), kind))
            cursor = end
            index += 1
        return tuple(regions)
