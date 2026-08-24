from dataclasses import dataclass
from typing import Optional, Tuple

from backend.solver_v2.domain.models import Placement
from .types import ReservedRegion


@dataclass(frozen=True)
class RegionValidation:
    valid: bool
    reason: str = ""


class ReservedRegionManager:
    """Exact door-zone broad phase; collision narrow-phase remains in WorldState."""

    def __init__(self, region: ReservedRegion, epsilon: float = 1e-9):
        self.region = region
        self.epsilon = epsilon

    def validate(self, placement: Placement, placement_role: str = "MAIN_CARGO") -> RegionValidation:
        if placement_role == "DOOR_WALL":
            return RegionValidation(True)
        intersects = placement.max_x > self.region.x1 + self.epsilon and placement.min_x < self.region.x2 - self.epsilon
        return RegionValidation(not intersects, "DOOR_ZONE_RESERVED" if intersects else "")

    def filter(self, placements: Tuple[Placement, ...]) -> Tuple[bool, Optional[str]]:
        for placement in placements:
            result = self.validate(placement)
            if not result.valid:
                return False, result.reason
        return True, None
