from dataclasses import asdict,dataclass
@dataclass(frozen=True)
class WallPattern:
    pattern_id:str;wall_id:str;family:str;reason:str
    def to_dict(self):return asdict(self)
