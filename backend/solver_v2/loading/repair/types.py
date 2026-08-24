"""Value types for downstream loading-sequence repair."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.solver_v2.loading.planner import LoadingPlan


@dataclass(frozen=True)
class TemporaryDebtPolicy:
    allowed: bool = True
    max_duration_steps: int = 1
    must_resolve_inside_group: bool = True


@dataclass(frozen=True)
class RepairRequest:
    failure: str
    placement_ids: Tuple[str, ...]

    @classmethod
    def from_failure(cls, failure: Dict[str, Any]) -> "RepairRequest":
        ids = failure.get("placement_ids") or failure.get("blocked_placements") or ()
        return cls(str(failure.get("reason") or failure.get("failure") or ""), tuple(ids))


@dataclass
class LoadingGroup:
    id: str
    placement_ids: Tuple[str, ...]
    type: str
    reason: str
    created_by: str = "REPAIR_ENGINE"
    temporary_stability_required: bool = True
    stability_before: bool = False
    stability_after: bool = False
    scope: str = ""
    distance: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "placement_ids": list(self.placement_ids), "type": self.type,
            "reason": self.reason, "created_by": self.created_by,
            "temporary_stability_required": self.temporary_stability_required,
            "stability_before": self.stability_before, "stability_after": self.stability_after,
            "scope": self.scope, "distance": self.distance,
        }


@dataclass(frozen=True)
class RepairAction:
    type: str
    placements: Tuple[str, ...]
    group_id: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "placements": list(self.placements),
                "group_id": self.group_id, "reason": self.reason}


@dataclass(frozen=True)
class RepairScore:
    stability_gain: float
    added_complexity: float
    group_size_penalty: float
    dependency_change_penalty: float

    @property
    def total(self) -> float:
        return self.stability_gain-self.added_complexity-self.group_size_penalty-self.dependency_change_penalty

    def to_dict(self) -> Dict[str, float]:
        return {"stability_gain":self.stability_gain,"added_complexity":self.added_complexity,
                "group_size_penalty":self.group_size_penalty,
                "dependency_change_penalty":self.dependency_change_penalty,"total":self.total}


@dataclass
class RepairCandidate:
    group: LoadingGroup
    score: Optional[RepairScore] = None
    valid: bool = False
    rejection_reason: Optional[str] = None
    repaired_plan: Optional[LoadingPlan] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"group":self.group.to_dict(),"valid":self.valid,
                "rejection_reason":self.rejection_reason,
                "score":self.score.to_dict() if self.score else None}


@dataclass
class RepairResult:
    repaired: bool
    repair_actions: List[RepairAction]
    updated_loading_plan: LoadingPlan
    validation_result: Dict[str, Any]
    metrics: Dict[str, Any]
    groups: List[LoadingGroup] = field(default_factory=list)
    candidates: List[RepairCandidate] = field(default_factory=list)

    def to_dict(self, include_plan: bool = True) -> Dict[str, Any]:
        return {"repaired":self.repaired,"repair_actions":[a.to_dict() for a in self.repair_actions],
                "updated_loading_plan":self.updated_loading_plan.to_dict(False) if include_plan else None,
                "validation_result":self.validation_result,"metrics":self.metrics,
                "groups":[g.to_dict() for g in self.groups],
                "candidates":[c.to_dict() for c in self.candidates]}
