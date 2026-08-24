from dataclasses import dataclass

@dataclass(frozen=True)
class WallBlueprint:
    wall_id:str;source_wall:str;category:str;members:tuple;start_x:float;end_x:float
    def to_dict(self): return {"wall_id":self.wall_id,"source_wall":self.source_wall,"category":self.category,"members":list(self.members),"x_range":[self.start_x,self.end_x]}
