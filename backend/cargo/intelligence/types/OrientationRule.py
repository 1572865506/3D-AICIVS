from dataclasses import asdict,dataclass
from typing import Any,Dict,Tuple
@dataclass(frozen=True)
class OrientationRule:
    base:Tuple[str,...]
    top:Tuple[str,...]
    door:Tuple[str,...]
    forbidden:Tuple[str,...]
    source:str
    def to_dict(self)->Dict[str,Any]:return asdict(self)
