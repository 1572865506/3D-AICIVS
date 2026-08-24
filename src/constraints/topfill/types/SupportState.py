from dataclasses import asdict,dataclass
from typing import Any,Dict
@dataclass(frozen=True)
class SupportState:
    supportRatio:float
    contactArea:float
    riskLevel:str
    maxTopLoad:float|None
    projectedLoad:float
    valid:bool
    reason:str=""
    def to_dict(self)->Dict[str,Any]:return asdict(self)
