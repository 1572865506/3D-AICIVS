from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class DirectionScore:
    space_efficiency: float
    wall_continuity: float
    transport_safety: float
    door_safety: float
    layer_compatibility: float
    risk: float
    final_score: float

    def to_dict(self):
        return asdict(self)
