from dataclasses import asdict, dataclass
from typing import Any, Dict, Tuple

from backend.solver_v2.domain.models import CargoSKU
from .CargoRiskClassifier import CargoRisk


SHORT_EDGE_FORWARD = "SHORT_EDGE_FORWARD"
LONG_EDGE_FORWARD = "LONG_EDGE_FORWARD"


@dataclass(frozen=True)
class DoorOrientation:
    policy_name: str
    concrete_orientation: str
    forward_depth: float
    wall_width: float
    height: float

    def to_dict(self) -> Dict[str, Any]: return asdict(self)


class DoorCargoRule:
    """Policy eligibility is explicit; cargo names and SKU ids are never inspected."""

    @staticmethod
    def is_allowed(risk: CargoRisk) -> bool:
        return risk.door_candidate


class DoorOrientationRules:
    def orientation_candidates(self, sku: CargoSKU, risk: CargoRisk) -> Tuple[DoorOrientation, ...]:
        if not DoorCargoRule.is_allowed(risk):
            raise ValueError(risk.rejection_reason or "DOOR_CARGO_NOT_ELIGIBLE")
        x, y, z = sku.box.x, sku.box.y, sku.box.z
        if x <= y:
            short = DoorOrientation(SHORT_EDGE_FORWARD,"UPRIGHT_NORMAL",x,y,z)
            long = DoorOrientation(LONG_EDGE_FORWARD,"UPRIGHT_ROTATED",y,x,z)
        else:
            short = DoorOrientation(SHORT_EDGE_FORWARD,"UPRIGHT_ROTATED",y,x,z)
            long = DoorOrientation(LONG_EDGE_FORWARD,"UPRIGHT_NORMAL",x,y,z)
        return (short,long)

    def orientation_for(self, sku: CargoSKU, risk: CargoRisk) -> DoorOrientation:
        """Legacy short-depth candidate; V2 builders evaluate all candidates."""
        return self.orientation_candidates(sku,risk)[0]

    def is_allowed(self, sku: CargoSKU, risk: CargoRisk, policy_name: str) -> bool:
        return policy_name in {SHORT_EDGE_FORWARD,LONG_EDGE_FORWARD} and DoorCargoRule.is_allowed(risk)

    def constraints_for(self, sku: CargoSKU, risk: CargoRisk) -> Dict[str, Any]:
        orientations=self.orientation_candidates(sku,risk)
        return {
            "sku": sku.sku_id,
            "allowed_orientation": [o.policy_name for o in orientations],
            "allowed_concrete_orientation": [o.concrete_orientation for o in orientations],
            "forbidden": [],
            "dimensions": [o.to_dict() for o in orientations],
            "selection_condition":"DOOR_OPEN_SELF_STABILITY_HARD_GATE",
            "source": "DOOR_SAFETY_PREPACKING",
        }
