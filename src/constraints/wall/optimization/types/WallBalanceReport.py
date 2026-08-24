from dataclasses import asdict,dataclass
from typing import Any,Dict
@dataclass(frozen=True)
class WallBalanceReport:
    leftWeight:float
    rightWeight:float
    lateralDifference:float
    balanceScore:float
    centerOfMassX:float
    doorBiasRatio:float
    def to_dict(self)->Dict[str,Any]:return asdict(self)
