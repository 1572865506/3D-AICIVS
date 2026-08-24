from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class DoorWallPlacement:
    placement_id: str
    sku_id: str
    x: float
    y: float
    z: float
    dx: float
    dy: float
    dz: float
    orientation: str
    layer: int
    column: int
    weight_kg: float
    concrete_orientation: str = ""

    @property
    def max_x(self) -> float: return self.x + self.dx

    @property
    def max_y(self) -> float: return self.y + self.dy

    @property
    def max_z(self) -> float: return self.z + self.dz

    def to_dict(self) -> Dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class DoorWallContinuity:
    coverage: float
    gap_count: int
    max_gap: float
    continuity_score: float

    def to_dict(self) -> Dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class DoorWallStability:
    stable: bool
    risk: str
    individual_stable_ratio: float
    supported_ratio: float
    neighbor_contact_ratio: float
    stack_alignment_ratio: float
    anchor_required: bool
    issues: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class DoorWall:
    wall_id: str
    zone: str
    placements: Tuple[DoorWallPlacement, ...]
    orientation: str
    height: float
    coverage: float
    continuity: DoorWallContinuity
    stability: DoorWallStability
    sku_mix: Dict[str, int] = field(default_factory=dict)
    anchor_x: float = 0.0
    width_coverage: float = 0.0
    height_coverage: float = 0.0
    door_plane_clearance: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["placements"] = [p.to_dict() for p in self.placements]
        return data
