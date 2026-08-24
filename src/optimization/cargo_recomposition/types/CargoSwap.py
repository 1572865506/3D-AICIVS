from dataclasses import asdict,dataclass

@dataclass(frozen=True)
class CargoSwap:
    cargo_id:str;original_wall:str;new_wall:str;original_position:tuple;new_position:tuple;swap_reason:str;orientation_change:str;optimization_reason:str
    def to_dict(self): return asdict(self)
