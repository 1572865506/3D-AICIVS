from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AxisStrategy:
    loading_axis: str
    door_axis: str
    rear_axis: str
    vertical_axis: str
    canonical_x: str
    loading_vector: str

    def to_dict(self):
        return asdict(self)
