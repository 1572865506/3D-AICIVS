from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class LayoutScore:
    volume_efficiency: float
    wall_continuity: float
    direction_compliance: float
    door_safety: float
    transport_stability: float
    layer_balance: float
    global_score: float

    def to_dict(self): return asdict(self)
