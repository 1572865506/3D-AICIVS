from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class LayoutCandidate:
    layout_id: str
    strategy: Any
    wall_plan: Any
    placement_plan: Any
    score: Any
    valid: bool
    validation: Any
    advantages: tuple = ()
    rejected_reason: tuple = ()

    @property
    def placements(self): return self.placement_plan.placements
    def to_dict(self) -> Dict:
        return {"layout_id":self.layout_id,"strategy":self.strategy.to_dict(),"wall_plan":self.wall_plan.to_dict(),
                "placement_plan":self.placement_plan.to_dict(),"score":self.score.to_dict(),"valid":self.valid,
                "advantages":list(self.advantages),"rejected_reason":list(self.rejected_reason),
                "validation":{"is_valid":self.validation.is_valid,"violation_count":len(self.validation.violations)}}
