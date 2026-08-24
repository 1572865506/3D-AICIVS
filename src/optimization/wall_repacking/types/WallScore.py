from dataclasses import asdict,dataclass
@dataclass(frozen=True)
class WallScore:
    layer_continuity:float;continuity:float;support:float;direction:float;volume:float;void:float;fragmentation:float;final_score:float
    def to_dict(self):return asdict(self)
