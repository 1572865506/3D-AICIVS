from dataclasses import asdict,dataclass
from typing import Any,Dict
from backend.solver_v2.domain.models import Orientation3D
@dataclass(frozen=True)
class TopCandidate:
    sku_id:str
    region_id:str
    orientation:Orientation3D
    orientation_label:str
    remaining_quantity:int
    max_layers:int
    unit_weight:float
    unit_volume:float
    support_requirement:float
    permission:Dict[str,bool]
    score:float=0.0
    def to_dict(self)->Dict[str,Any]:
        d=asdict(self);d["orientation"]={"name":self.orientation.name,"dx":self.orientation.dx,"dy":self.orientation.dy,"dz":self.orientation.dz};return d
