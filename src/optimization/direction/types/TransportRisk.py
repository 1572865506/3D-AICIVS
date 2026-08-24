from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class TransportRisk:
    forward_risk: float
    side_risk: float
    braking_risk: float
    turning_risk: float
    recommended_facing: str
    transport_score: float

    def to_dict(self):
        return asdict(self)
