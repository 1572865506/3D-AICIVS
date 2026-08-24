from dataclasses import dataclass
@dataclass(frozen=True)
class WallColumn:
    column_id:str;y:float;placements:tuple;height:float
    def to_dict(self):return {"column_id":self.column_id,"y":self.y,"height":self.height,"placements":[p.placement_id for p in self.placements]}
