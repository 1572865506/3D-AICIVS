from dataclasses import dataclass
@dataclass(frozen=True)
class WallLayer:
    layer_id:str;z:float;placements:tuple;coverage:float
    def to_dict(self):return {"layer_id":self.layer_id,"z":self.z,"coverage":self.coverage,"placements":[p.placement_id for p in self.placements]}
