from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RebuildStrategy:
    strategy_id: str
    family: str
    description: str

    def to_dict(self): return asdict(self)
