from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from backend.solver_v2.domain.models import CargoSKU, PackingRole, ZoneType


@dataclass(frozen=True)
class CargoRisk:
    sku_id: str
    thin: bool
    fragile: bool
    door_candidate: bool
    explicit_door_policy: bool
    wall_formable: bool
    high_unit_weight: bool
    risk_level: str
    thin_ratio: float
    rejection_reason: str = ""

    def to_dict(self) -> Dict[str, Any]: return asdict(self)


class CargoRiskClassifier:
    def __init__(self, thin_ratio_threshold: float = 0.35, max_door_unit_weight_kg: float = 80.0):
        if thin_ratio_threshold <= 0:
            raise ValueError("thin_ratio_threshold must be positive")
        self.thin_ratio_threshold = float(thin_ratio_threshold)
        self.max_door_unit_weight_kg = float(max_door_unit_weight_kg)

    def is_thin_cargo(self, sku: CargoSKU) -> bool:
        return min(sku.box.x, sku.box.y) / max(sku.box.z, 1e-9) < self.thin_ratio_threshold

    # Public compatibility spelling from the block specification.
    def isThinCargo(self, sku: CargoSKU) -> bool:
        return self.is_thin_cargo(sku)

    def classify(self, sku: CargoSKU, container_width: Optional[float] = None, container_height: Optional[float] = None) -> CargoRisk:
        ratio = min(sku.box.x, sku.box.y) / max(sku.box.z, 1e-9)
        thin = ratio < self.thin_ratio_threshold
        fragile = bool(sku.cargo_profile and sku.cargo_profile.handling_policy.fragile)
        explicit = PackingRole.DOOR_SEAL in sku.packing_roles or sku.target_zone == ZoneType.DOOR
        face_width = max(sku.box.x, sku.box.y)
        wall_formable = (
            (container_width is None or face_width <= container_width + 1e-9)
            and (container_height is None or sku.box.z <= container_height + 1e-9)
        )
        heavy = sku.weight_kg > self.max_door_unit_weight_kg
        candidate = explicit and wall_formable and not heavy
        reason = ""
        if not explicit: reason = "DOOR_POLICY_NOT_DECLARED"
        elif not wall_formable: reason = "CANNOT_FORM_DOOR_WALL"
        elif heavy: reason = "HIGH_UNIT_WEIGHT_FOR_DOOR_ZONE"
        level = "HIGH" if thin or fragile else ("MEDIUM" if candidate else "LOW")
        return CargoRisk(
            sku_id=sku.sku_id, thin=thin, fragile=fragile, door_candidate=candidate,
            explicit_door_policy=explicit, wall_formable=wall_formable,
            high_unit_weight=heavy, risk_level=level, thin_ratio=round(ratio, 6),
            rejection_reason=reason,
        )
