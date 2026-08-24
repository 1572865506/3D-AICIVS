from dataclasses import asdict,dataclass
from typing import Any,Dict
@dataclass(frozen=True)
class LayerGap:
    gap_id:str
    layer_id:str
    x:float;y:float;z:float
    dx:float;dy:float;dz:float
    volume:float
    supported:bool
    def to_dict(self)->Dict[str,Any]:return asdict(self)
