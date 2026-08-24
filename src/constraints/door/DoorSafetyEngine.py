from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, Optional, Tuple

from backend.solver_v2.domain.models import CargoSKU, ContainerSpec
from .CargoRiskClassifier import CargoRisk, CargoRiskClassifier
from .DoorOrientationRules import DoorOrientationRules, SHORT_EDGE_FORWARD
from .DoorSafetyScore import DoorSafetyScore, DoorSafetyScoreResult
from .DoorWallBuilder import DoorWallBuilder
from .DoorWallValidator import DoorWallValidator
from .DoorZoneDetector import DoorZoneConfig, DoorZoneDetector
from .TransportForceModel import TransportForceConfig
from .types import DoorConstraint, DoorValidationResult, DoorWall, DoorZone


@dataclass(frozen=True)
class DoorSafetyConfig:
    door_zone_depth: Optional[float] = None
    thin_ratio_threshold: float = 0.35
    max_door_unit_weight_kg: float = 80.0
    min_wall_coverage: float = 0.75
    max_wall_gap_m: float = 0.40
    min_support_ratio: float = 0.70
    min_width_coverage: float = 0.0
    min_height_coverage: float = 0.0
    door_plane_clearance_m: Optional[float] = None
    max_door_restraint_gap_m: float = 0.10
    max_door_depth_spread_m: Optional[float] = None
    preferred_wall_sku_diversity: int = 1

    @classmethod
    def formation_v2(cls, door_zone_depth: Optional[float] = None):
        return cls(door_zone_depth=door_zone_depth,min_wall_coverage=.90,max_wall_gap_m=.20,
                   min_support_ratio=.70,min_width_coverage=.95,min_height_coverage=.80,
                   door_plane_clearance_m=.05,max_door_restraint_gap_m=.12,
                   max_door_depth_spread_m=.08,preferred_wall_sku_diversity=2)


@dataclass(frozen=True)
class DoorSafetyPlan:
    status: str
    zone: DoorZone
    classifications: Dict[str, CargoRisk]
    orientation_rules: Dict[str, Dict[str, Any]]
    constraints: DoorConstraint
    wall: Optional[DoorWall]
    validation: Optional[DoorValidationResult]
    safety_score: Optional[DoorSafetyScoreResult]
    reason: str = ""
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "zone": self.zone.to_dict(),
            "classifications": {sku: value.to_dict() for sku, value in self.classifications.items()},
            "orientation_rules": self.orientation_rules,
            "constraints": self.constraints.to_dict(),
            "wall": self.wall.to_dict() if self.wall else None,
            "validation": self.validation.to_dict() if self.validation else None,
            "safety_score": self.safety_score.to_dict() if self.safety_score else None,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PreparedPackingInput:
    """Immutable hand-off object for the packing orchestration layer in BLK007E-2."""

    container: ContainerSpec
    cargo: Tuple[CargoSKU, ...]
    door_constraints: DoorConstraint
    door_wall: Optional[DoorWall]


class DoorSafetyEngine:
    """Pre-packing planner. It never mutates CargoSKU, ContainerSpec, or solver state."""

    def __init__(self, config: Optional[DoorSafetyConfig] = None):
        self.config = config or DoorSafetyConfig.formation_v2()
        self.zone_detector = DoorZoneDetector(DoorZoneConfig(self.config.door_zone_depth))
        self.classifier = CargoRiskClassifier(
            self.config.thin_ratio_threshold, self.config.max_door_unit_weight_kg,
        )
        self.orientation_rules = DoorOrientationRules()
        self.wall_builder = DoorWallBuilder(
            self.config.min_wall_coverage,self.config.min_support_ratio,
            self.config.min_width_coverage,self.config.min_height_coverage,
            self.config.door_plane_clearance_m,max_depth_spread_m=self.config.max_door_depth_spread_m,
            preferred_sku_diversity=self.config.preferred_wall_sku_diversity,
        )
        self.wall_validator = DoorWallValidator(
            self.config.min_wall_coverage,self.config.max_wall_gap_m,self.config.min_support_ratio,
            self.config.min_width_coverage,self.config.min_height_coverage,
            (TransportForceConfig(max_door_restraint_gap_m=self.config.max_door_restraint_gap_m)
             if self.config.door_plane_clearance_m is not None else None),
        )
        self.scorer = DoorSafetyScore()

    def plan(self, container: ContainerSpec, cargo: Iterable[CargoSKU]) -> DoorSafetyPlan:
        cargo_tuple = tuple(cargo)
        zone = self.zone_detector.detect(container)
        classifications = {
            sku.sku_id: self.classifier.classify(sku, container.Ly, container.Lz)
            for sku in cargo_tuple
        }
        candidates = [sku for sku in cargo_tuple if classifications[sku.sku_id].door_candidate]
        orientation_rules = {
            sku.sku_id: self.orientation_rules.constraints_for(sku, classifications[sku.sku_id])
            for sku in candidates
        }
        wall = self.wall_builder.build(container, zone, candidates, classifications)
        priority = tuple(sku.sku_id for sku in sorted(candidates, key=lambda item: item.sku_id))
        selected_orientation={}
        if wall is not None:
            for placement in wall.placements:
                previous=selected_orientation.get(placement.sku_id)
                selected_orientation[placement.sku_id]=(placement.orientation if previous in {None,placement.orientation} else "MIXED_DOOR_ORIENTATION")
        forced = selected_orientation
        blocked = ({
            "x_start": round(zone.solver_start_x, 6), "x_end": round(zone.solver_end_x, 6),
            "door_distance_start": zone.start_x, "door_distance_end": zone.end_x,
        },)

        if wall is None:
            detail = "No explicitly door-eligible, wall-formable inventory can cover the reserved zone"
            constraints = DoorConstraint(
                status="FAILED", reserved_zone=zone, forced_orientation=forced,
                priority_cargo=priority, blocked_positions=blocked,
                reason="NO_VALID_DOOR_WALL", detail=detail,
            )
            return DoorSafetyPlan(
                status="FAILED", zone=zone, classifications=classifications,
                orientation_rules=orientation_rules, constraints=constraints,
                wall=None, validation=None, safety_score=None,
                reason="NO_VALID_DOOR_WALL", detail=detail,
            )

        validation = self.wall_validator.validate(wall, zone, container)
        score = self.scorer.calculate(validation, container.Ly)
        status = "READY" if validation.valid else "FAILED"
        reason = "" if validation.valid else "NO_VALID_DOOR_WALL"
        detail = "" if validation.valid else "; ".join(validation.issues)
        constraints = DoorConstraint(
            status=status, reserved_zone=zone, forced_orientation=forced,
            priority_cargo=priority, blocked_positions=blocked,
            inventory_reservation=dict(wall.sku_mix), reason=reason, detail=detail,
        )
        return DoorSafetyPlan(
            status=status, zone=zone, classifications=classifications,
            orientation_rules=orientation_rules, constraints=constraints,
            wall=wall, validation=validation, safety_score=score,
            reason=reason, detail=detail,
        )

    def get_door_constraints(self, container: ContainerSpec, cargo: Iterable[CargoSKU]) -> Dict[str, Any]:
        return self.plan(container, cargo).constraints.to_dict()

    def getDoorConstraints(self, container: ContainerSpec, cargo: Iterable[CargoSKU]) -> Dict[str, Any]:
        return self.get_door_constraints(container, cargo)

    def prepare_solver_input(self, container: ContainerSpec, cargo: Iterable[CargoSKU]) -> PreparedPackingInput:
        cargo_tuple = tuple(cargo)
        plan = self.plan(container, cargo_tuple)
        return PreparedPackingInput(container, cargo_tuple, plan.constraints, plan.wall)
