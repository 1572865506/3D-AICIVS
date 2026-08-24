from dataclasses import dataclass
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class DirectionPlan:
    status: str
    axis_strategy: Any
    facing_rules: Tuple[Any, ...]
    selected_candidates: Tuple[Any, ...]
    orientation_matrix: Tuple[Dict[str, Any], ...]
    cargo_wall_constraints: Dict[str, Any]
    solver_constraints: Dict[str, Any]
    topfill_constraints: Dict[str, Any]
    actual_validation: Dict[str, Any]

    def to_dict(self):
        return {
            "status": self.status, "axis_strategy": self.axis_strategy.to_dict(),
            "facing_rules": [x.to_dict() for x in self.facing_rules],
            "selected_candidates": [x.to_dict() for x in self.selected_candidates],
            "orientation_matrix": list(self.orientation_matrix),
            "constraints": {
                "cargo_wall": self.cargo_wall_constraints,
                "solver": self.solver_constraints,
                "topfill": self.topfill_constraints,
            },
            "actual_validation": self.actual_validation,
        }
