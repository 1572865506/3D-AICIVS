from dataclasses import asdict,dataclass
from typing import Any,Dict
@dataclass(frozen=True)
class BridgeCandidate:
    bridge_id:str
    sku_id:str
    left_wall_id:str
    right_wall_id:str
    support_ratio:float
    compression_pass:bool
    profile_allowed:bool
    score:float
    valid:bool
    reason:str=""
    def to_dict(self)->Dict[str,Any]:return asdict(self)
