from dataclasses import asdict,dataclass
from typing import Any,Dict
@dataclass(frozen=True)
class StackRule:
    base_max_layers:int|None
    top_max_layers:int
    top_allowed:bool
    stack_on_self:bool
    source:str
    def to_dict(self)->Dict[str,Any]:return asdict(self)
