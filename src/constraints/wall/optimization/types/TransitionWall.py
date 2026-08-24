from dataclasses import dataclass
from typing import Any,Dict,Tuple
from backend.solver_v2.domain.models import Placement

@dataclass(frozen=True)
class TransitionWall:
    id:str
    placements:Tuple[Placement,...]
    x_range:Tuple[float,float]
    source_sku:str
    orientation:str
    coverage:float
    continuity_score:float
    average_unit_weight:float
    role:str="TRANSITION_WALL"
    def to_dict(self)->Dict[str,Any]:
        return {"id":self.id,"placements":[p.placement_id for p in self.placements],"placement_count":len(self.placements),
                "x_range":list(self.x_range),"source_sku":self.source_sku,"orientation":self.orientation,
                "coverage":self.coverage,"continuity_score":self.continuity_score,
                "average_unit_weight":self.average_unit_weight,"role":self.role}
