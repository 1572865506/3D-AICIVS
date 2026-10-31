from dataclasses import asdict,dataclass
from typing import Any,Dict
@dataclass(frozen=True)
class CompressionRule:
    max_load_kg:float|None
    compression_class:str
    allow_as_support:bool
    source:str
    def to_dict(self)->Dict[str,Any]:return asdict(self)
