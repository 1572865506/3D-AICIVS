from dataclasses import asdict,dataclass
from typing import Any,Dict
from backend.solver_v2.domain.models import Orientation3D
@dataclass(frozen=True)
class OrientationCandidate:
    sku_id:str
    orientation:Orientation3D
    orientation_used:str
    score:float
    volume_gain:float
    layer_completion:float
    support_change:float
    stability_change:float
    risk:float
    reason:str
    def to_dict(self)->Dict[str,Any]:
        d=asdict(self);d["orientation"]={"name":self.orientation.name,"dx":self.orientation.dx,"dy":self.orientation.dy,"dz":self.orientation.dz};return d
