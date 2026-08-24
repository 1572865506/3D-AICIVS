from dataclasses import dataclass
from typing import Optional

from backend.solver_v2.domain.models import ContainerSpec
from .types import DoorZone


@dataclass(frozen=True)
class DoorZoneConfig:
    door_zone_depth: Optional[float] = None


class DoorZoneDetector:
    def __init__(self, config: Optional[DoorZoneConfig] = None):
        self.config = config or DoorZoneConfig()

    def detect(self, container: ContainerSpec) -> DoorZone:
        depth = self.config.door_zone_depth
        if depth is None:
            depth = container.door_zone_length_m
        depth = float(depth)
        if depth <= 0 or depth > container.Lx:
            raise ValueError(f"door_zone_depth must be in (0, {container.Lx}], got {depth}")
        return DoorZone(
            depth=depth,
            start_x=0.0,
            end_x=depth,
            solver_start_x=container.Lx - depth,
            solver_end_x=container.Lx,
            priority="HIGH",
            reserved=True,
        )
