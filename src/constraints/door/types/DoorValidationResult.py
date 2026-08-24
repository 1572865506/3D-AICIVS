from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class DoorValidationResult:
    valid: bool
    stable: bool
    forbidden_orientation_count: int
    coverage: float
    gap_count: int
    max_gap: float
    support_ratio: float
    continuity_score: float
    stability_risk: str
    issues: Tuple[str, ...]
    width_coverage: float = 0.0
    height_coverage: float = 0.0
    door_plane_clearance: float = 0.0
    transport_stable: bool = False
    transport: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]: return asdict(self)
