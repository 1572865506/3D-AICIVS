from dataclasses import dataclass
from typing import Any,Dict,Tuple
@dataclass(frozen=True)
class TopFillResult:
    status:str
    regions:Tuple[Any,...]
    candidates:Tuple[Any,...]
    placements:Tuple[Any,...]
    layers:Tuple[Any,...]
    support_states:Tuple[Any,...]
    rejected:Tuple[Dict[str,Any],...]
    top_volume_added:float
    top_fill_score:float
    remaining_unused_volume:float
    structural_lock_preserved:bool
    validation:Any
    def to_dict(self):return {"status":self.status,"top_fill_used":bool(self.placements),"regions":[r.to_dict() for r in self.regions],
        "candidates":[c.to_dict() for c in self.candidates],"placements":[p.placement_id for p in self.placements],
        "placement_count":len(self.placements),"layers":[l.to_dict() for l in self.layers],"top_layers":max((l.layer_index for l in self.layers),default=0),
        "support_states":[s.to_dict() for s in self.support_states],"rejected":list(self.rejected),
        "top_volume_added":self.top_volume_added,"top_fill_score":self.top_fill_score,
        "remaining_unused_volume":self.remaining_unused_volume,"structural_lock_preserved":self.structural_lock_preserved,
        "validation":self.validation.to_dict()}
