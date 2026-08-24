from dataclasses import dataclass
from backend.solver_v2.domain.models import BoxDim
from .AxisDefinition import AxisDefinition

@dataclass(frozen=True)
class NormalizedDimension:
    length:float;width:float;height:float;axisDefinition:AxisDefinition=AxisDefinition();thicknessAxis:str|None=None
    def __post_init__(self):
        if min(self.length,self.width,self.height)<=0:raise ValueError("DIMENSIONS_MUST_BE_POSITIVE")
    def to_box_dim(self):return BoxDim(self.length,self.width,self.height)
    def to_dict(self):return {"dimensions":{"length":self.length,"width":self.width,"height":self.height},"axisDefinition":self.axisDefinition.to_dict(),"thicknessAxis":self.thicknessAxis}
