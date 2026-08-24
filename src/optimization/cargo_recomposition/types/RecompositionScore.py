from dataclasses import asdict,dataclass

@dataclass(frozen=True)
class RecompositionScore:
    wall_continuity:float;direction_compliance:float;transport_safety:float;space_efficiency:float;door_safety:float;layer_balance:float;global_score:float
    def to_dict(self): return asdict(self)
