from dataclasses import dataclass
from typing import Any,Dict,Tuple
@dataclass(frozen=True)
class LayerOptimizationResult:
    status:str
    layers_before:Tuple[Any,...]
    layers_after:Tuple[Any,...]
    added_placements:Tuple[Any,...]
    orientation_decisions:Tuple[Any,...]
    bridge_candidates:Tuple[Any,...]
    door_seal:Dict[str,Any]
    occupancy_before:float
    occupancy_after:float
    void_before:float
    void_after:float
    structural_lock_preserved:bool
    validation:Any
    def to_dict(self):return {"status":self.status,"layers_before":[x.to_dict() for x in self.layers_before],"layers_after":[x.to_dict() for x in self.layers_after],
        "added_placements":[p.placement_id for p in self.added_placements],"added_count":len(self.added_placements),
        "orientation_decisions":[x.to_dict() for x in self.orientation_decisions],"bridge_candidates":[x.to_dict() for x in self.bridge_candidates],
        "door_seal":self.door_seal,"occupancy_before":self.occupancy_before,"occupancy_after":self.occupancy_after,
        "void_before":self.void_before,"void_after":self.void_after,"structural_lock_preserved":self.structural_lock_preserved,"validation":self.validation.to_dict()}
