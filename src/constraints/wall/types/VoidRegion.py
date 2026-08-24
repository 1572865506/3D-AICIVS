from dataclasses import asdict, dataclass
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class VoidRegion:
    void_id: str
    position: Tuple[float, float, float]
    dimensions: Tuple[float, float, float]
    volume: float
    void_type: str

    def to_dict(self) -> Dict[str, Any]: return asdict(self)
