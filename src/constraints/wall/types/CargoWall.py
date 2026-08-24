from dataclasses import dataclass
from typing import Any, Dict, Tuple

from backend.solver_v2.domain.models import Placement
from .WallLayer import WallLayer
from .WallSegment import WallSegment


@dataclass(frozen=True)
class CargoWall:
    id: str
    region: str
    layers: Tuple[WallLayer, ...]
    segments: Tuple[WallSegment, ...]
    placements: Tuple[Placement, ...]
    width: float
    height: float
    depth: float
    continuity: Dict[str, Any]
    stability: Dict[str, Any]
    void_ratio: float
    wall_score: float
    risk: str
    role: str = "CARGO_WALL"

    @property
    def x_start(self): return min((p.min_x for p in self.placements), default=0.0)
    @property
    def x_end(self): return max((p.max_x for p in self.placements), default=0.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "region": self.region,
            "x_range": [self.x_start, self.x_end],
            "layers": [layer.to_dict() for layer in self.layers],
            "segments": [segment.to_dict() for segment in self.segments],
            "placements": [p.placement_id for p in self.placements],
            "sku_mix": {sku: sum(p.sku_id == sku for p in self.placements) for sku in sorted({p.sku_id for p in self.placements})},
            "width": self.width, "height": self.height, "depth": self.depth,
            "continuity": self.continuity, "stability": self.stability,
            "void_ratio": self.void_ratio, "wall_score": self.wall_score,
            "risk": self.risk, "role": self.role,
        }
