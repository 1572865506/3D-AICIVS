"""
Solver V2 Placement Rules & Constraints
Structured rule objects compiled from UI or business configurations.
No free-text parsing in Solver Core.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple, Set
from backend.solver_v2.domain.models import (
    PlacementRuleMode,
    PlacementContext,
    ZoneType,
    Orientation3D,
    Placement,
    CargoSKU,
    ContainerSpec,
)


class ConstraintType(str, Enum):
    ORIENTATION = "ORIENTATION"
    ZONE = "ZONE"
    STACK_LAYER = "STACK_LAYER"
    BEARING_WEIGHT = "BEARING_WEIGHT"
    PRESSURE = "PRESSURE"
    SUPPORT_RATIO = "SUPPORT_RATIO"
    UNSUPPORTED_SPAN = "UNSUPPORTED_SPAN"
    DOOR_BOUNDARY = "DOOR_BOUNDARY"
    REAR_BOUNDARY = "REAR_BOUNDARY"
    FLOOR_ONLY = "FLOOR_ONLY"


@dataclass(frozen=True)
class ConstraintViolation:
    """Detailed record of a failed constraint evaluation."""
    constraint_type: ConstraintType
    rule_name: str
    sku_id: str
    message: str
    severity: PlacementRuleMode = PlacementRuleMode.REQUIRED
    context: Optional[PlacementContext] = None


@dataclass(frozen=True)
class ZoneConstraint:
    """Restricts SKU placement to specific longitudinal or vertical zones."""
    sku_id: str
    allowed_zones: Tuple[ZoneType, ...]
    mode: PlacementRuleMode = PlacementRuleMode.REQUIRED
    penalty_score: float = 100.0

    def check_position(self, x: float, dx: float, container: ContainerSpec) -> bool:
        """
        Check if a candidate placement along longitudinal axis x satisfies zone rule.
        Rear zone: [0, rear_zone_length_m]
        Door zone: [container.Lx - door_zone_length_m, container.Lx]
        Middle zone: (rear_zone_length_m, container.Lx - door_zone_length_m)
        """
        rear_boundary = container.rear_zone_length_m
        door_boundary = container.Lx - container.door_zone_length_m

        is_rear = (x + dx <= rear_boundary + 1e-4) or (x <= rear_boundary and x + dx <= rear_boundary + 0.3)
        is_door = (x >= door_boundary - 1e-4)

        if ZoneType.REAR in self.allowed_zones:
            # Must stay near rear
            if x > rear_boundary + 0.5:
                return False
        if ZoneType.MIDDLE in self.allowed_zones:
            # Preferred in middle, but not locked out if not strict
            pass
        if ZoneType.DOOR in self.allowed_zones:
            # Door sealed SKU allowed in door zone
            pass

        return True


@dataclass(frozen=True)
class DoorZoneConstraint:
    """Strictly locks out non-door-seal SKUs from the door zone [Lx - door_zone_length, Lx]."""
    door_zone_length_m: float = 1.2
    exempt_skus: Set[str] = field(default_factory=set)

    def is_allowed_in_door_zone(self, sku_id: str, x: float, dx: float, container_lx: float) -> bool:
        door_start = max(0.0, container_lx - self.door_zone_length_m)
        box_end = x + dx
        # If box enters door zone beyond door_start
        if box_end > door_start + 1e-4:
            return sku_id in self.exempt_skus
        return True


@dataclass(frozen=True)
class StackLimitConstraint:
    """Limits the number of identical or total stacked boxes in a vertical column."""
    sku_id: str
    max_layers: int
    mode: PlacementRuleMode = PlacementRuleMode.REQUIRED


@dataclass(frozen=True)
class BearingConstraint:
    """Limits total upper weight (in kg) that can press onto this SKU."""
    sku_id: str
    max_bearing_kg: float
    mode: PlacementRuleMode = PlacementRuleMode.REQUIRED


@dataclass(frozen=True)
class PressureConstraint:
    """Limits pressure (kg/m^2) exerted on top surface of this SKU."""
    sku_id: str
    max_pressure_kg_m2: float
    mode: PlacementRuleMode = PlacementRuleMode.REQUIRED


@dataclass(frozen=True)
class SupportRatioConstraint:
    """Requires minimum contact support ratio (0.0 to 1.0) under bottom face."""
    sku_id: str
    min_ratio: float = 0.70
    max_unsupported_span_m: float = 0.10
    mode: PlacementRuleMode = PlacementRuleMode.REQUIRED
