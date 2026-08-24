from dataclasses import dataclass
from typing import Any,Dict,Tuple

@dataclass(frozen=True)
class WallConnection:
    source:str
    target:str
    gap_m:float
    overlap_ratio:float
    strength:float
    connection_type:str="SUPPORT_CONNECTION"
    def to_dict(self):return dict(self.__dict__)

@dataclass(frozen=True)
class WallChain:
    nodes:Tuple[Dict[str,Any],...]
    connections:Tuple[WallConnection,...]
    chain_length:float
    weak_links:Tuple[str,...]
    broken_points:Tuple[str,...]
    valid:bool
    def to_dict(self):return {"nodes":list(self.nodes),"connections":[c.to_dict() for c in self.connections],
        "chainLength":self.chain_length,"weakLinks":list(self.weak_links),"brokenPoints":list(self.broken_points),"valid":self.valid}
