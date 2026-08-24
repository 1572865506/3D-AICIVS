from dataclasses import asdict, dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class SupportLink:
    source: str
    target: str
    link_type: str
    contact_area: float
    support_ratio: float

    def to_dict(self) -> Dict[str, Any]: return asdict(self)
