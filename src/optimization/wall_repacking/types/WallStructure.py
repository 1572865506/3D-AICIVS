from dataclasses import dataclass
@dataclass(frozen=True)
class WallStructure:
    wall_id:str;placements:tuple;columns:tuple;layers:tuple;cargo_count:int;sku_mix:dict;display_wall:bool;x_range:tuple
    def to_dict(self):return {"wall_id":self.wall_id,"columns":len(self.columns),"layers":len(self.layers),"cargo_count":self.cargo_count,
        "sku_mix":self.sku_mix,"display_wall":self.display_wall,"x_range":list(self.x_range),
        "column_detail":[x.to_dict() for x in self.columns],"layer_detail":[x.to_dict() for x in self.layers]}
