from dataclasses import asdict,dataclass
from typing import Any,Dict,Optional
@dataclass(frozen=True)
class TopRegion:
    id:str
    logical_wall_id:str
    x:float
    y:float
    z:float
    width:float
    depth:float
    height:float
    volume:float
    supportArea:float
    classification:str
    base_sku:str
    support_score:float
    max_top_load:Optional[float]
    structural_lock:str="LOCKED_WALL"
    def to_dict(self)->Dict[str,Any]:return asdict(self)
