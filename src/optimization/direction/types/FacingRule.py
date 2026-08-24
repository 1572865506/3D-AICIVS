from dataclasses import asdict, dataclass
from typing import Tuple


@dataclass(frozen=True)
class FacingRule:
    sku: str
    wall_role: str
    preferred_facing: str
    allowed_facing: Tuple[str, ...]
    forbidden_facing: Tuple[str, ...]
    reason: str
    source: str
    hard: bool = False

    def to_dict(self):
        data = asdict(self)
        data["allowed_facing"] = list(self.allowed_facing)
        data["forbidden_facing"] = list(self.forbidden_facing)
        return data
