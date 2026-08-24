from dataclasses import dataclass
from src.optimization.residual_filling import ResidualSpaceFillingEngine

@dataclass(frozen=True)
class PreparedResidualFill:
    result:object

class ResidualFillingAdapter:
    def __init__(self,engine=None):self.engine=engine or ResidualSpaceFillingEngine()
    def optimize(self,container,cargo,existing,intelligence=None):
        result=self.engine.fill(container,cargo,existing,intelligence)
        if result.status!="SUCCESS":raise ValueError("RESIDUAL_FILLING_FAILED")
        return PreparedResidualFill(result)
