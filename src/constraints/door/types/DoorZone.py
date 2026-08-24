from dataclasses import asdict, dataclass
from typing import Dict, Any


@dataclass(frozen=True)
class DoorZone:
    """Door-relative and solver-canonical representation of the reserved zone."""

    depth: float
    start_x: float
    end_x: float
    solver_start_x: float
    solver_end_x: float
    priority: str = "HIGH"
    reserved: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
