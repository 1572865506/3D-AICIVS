from typing import List

from backend.solver_v2.domain.models import ContainerSpec
from .types import DoorValidationResult, DoorWall, DoorZone
from .TransportForceModel import TransportForceConfig, TransportForceDirectionModel
from .DoorOrientationRules import LONG_EDGE_FORWARD,SHORT_EDGE_FORWARD


class DoorWallStabilityValidator:
    def __init__(self, min_support_ratio: float = 0.70):
        self.min_support_ratio = float(min_support_ratio)

    def validate(self, wall: DoorWall) -> bool:
        stability = wall.stability
        return (
            stability.supported_ratio >= self.min_support_ratio
            and stability.neighbor_contact_ratio >= 0.50
            and stability.stack_alignment_ratio >= self.min_support_ratio
            and stability.anchor_required
        )


class DoorWallValidator:
    def __init__(self, min_coverage: float = 0.75, max_gap_m: float = 0.40, min_support_ratio: float = 0.70,
                 min_width_coverage: float = 0.0, min_height_coverage: float = 0.0,
                 transport_config: TransportForceConfig = None):
        self.min_coverage = float(min_coverage)
        self.max_gap_m = float(max_gap_m)
        self.min_width_coverage=float(min_width_coverage)
        self.min_height_coverage=float(min_height_coverage)
        self.stability_validator = DoorWallStabilityValidator(min_support_ratio)
        self.transport_model=TransportForceDirectionModel(transport_config) if transport_config is not None else None

    def validate(self, wall: DoorWall, zone: DoorZone, container: ContainerSpec) -> DoorValidationResult:
        issues: List[str] = []
        forbidden = sum(1 for p in wall.placements if p.orientation not in {SHORT_EDGE_FORWARD,LONG_EDGE_FORWARD})
        if forbidden: issues.append("FORBIDDEN_DOOR_ORIENTATION")
        outside = sum(1 for p in wall.placements if p.x < zone.solver_start_x - 1e-9 or p.max_x > zone.solver_end_x + 1e-9)
        if outside: issues.append("PLACEMENT_OUTSIDE_DOOR_ZONE")
        if wall.coverage < self.min_coverage: issues.append("INSUFFICIENT_DOOR_COVERAGE")
        if wall.width_coverage < self.min_width_coverage:issues.append("INSUFFICIENT_DOOR_WIDTH_COVERAGE")
        if wall.height_coverage < self.min_height_coverage:issues.append("INSUFFICIENT_DOOR_HEIGHT_COVERAGE")
        if wall.continuity.max_gap > self.max_gap_m: issues.append("DOOR_WALL_GAP_TOO_LARGE")
        stable = self.stability_validator.validate(wall)
        if not stable: issues.append("DOOR_WALL_STABILITY_FAILED")
        transport=self.transport_model.evaluate(wall,container) if self.transport_model else None
        if transport is not None and not transport.valid:issues.extend(transport.rejection_reasons)
        return DoorValidationResult(
            valid=not issues, stable=stable, forbidden_orientation_count=forbidden,
            coverage=round(wall.coverage, 6), gap_count=wall.continuity.gap_count,
            max_gap=round(wall.continuity.max_gap, 6),
            support_ratio=round(wall.stability.supported_ratio, 6),
            continuity_score=round(wall.continuity.continuity_score, 4),
            stability_risk=wall.stability.risk,issues=tuple(issues),
            width_coverage=round(wall.width_coverage,6),height_coverage=round(wall.height_coverage,6),
            door_plane_clearance=round(wall.door_plane_clearance,6),transport_stable=transport.valid if transport else True,
            transport=transport.to_dict() if transport else {},
        )
