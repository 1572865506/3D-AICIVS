from dataclasses import asdict,dataclass
from typing import Any,Dict,Tuple
@dataclass(frozen=True)
class TopLayer:
    region_id:str
    layer_index:int
    base_z:float
    height:float
    placement_ids:Tuple[str,...]
    support_ratio:float
    def to_dict(self)->Dict[str,Any]:return asdict(self)
