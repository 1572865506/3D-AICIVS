from dataclasses import dataclass
from src.constraints.topfill import TopFillEngine

@dataclass(frozen=True)
class PreparedTopFill:
    result:object

class TopFillOptimizationAdapter:
    def __init__(self,engine=None):self.engine=engine or TopFillEngine()
    def optimize(self,container,cargo,existing,optimized_walls):
        result=self.engine.fill(container,cargo,existing,optimized_walls)
        if result.status!="SUCCESS":
            reasons=",".join(f"{v.violation_type.value}:{v.placement_id or ''}" for v in result.validation.violations[:8])
            raise ValueError(f"TOP_FILL_OPTIMIZATION_FAILED:{reasons or 'STRUCTURAL_FINGERPRINT_CHANGED'}")
        return PreparedTopFill(result)
