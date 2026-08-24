from dataclasses import asdict,dataclass
from typing import Any,Dict
@dataclass(frozen=True)
class LoadingPolicy:
    door_priority:int
    main_priority:int
    top_priority:int
    loading_reason:str
    source:str
    def to_dict(self)->Dict[str,Any]:return asdict(self)
