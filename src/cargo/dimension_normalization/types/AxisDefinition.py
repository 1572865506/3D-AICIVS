from dataclasses import asdict,dataclass

@dataclass(frozen=True)
class AxisDefinition:
    lengthAxis:str="X"
    widthAxis:str="Y"
    heightAxis:str="Z"
    def to_dict(self):return asdict(self)
