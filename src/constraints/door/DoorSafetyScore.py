from dataclasses import asdict, dataclass
from typing import Any, Dict, Tuple

from .types import DoorValidationResult


@dataclass(frozen=True)
class DoorSafetyScoreResult:
    score: float
    coverage_component: float
    continuity_component: float
    orientation_component: float
    stability_component: float
    gap_penalty: float
    issues: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]: return asdict(self)


class DoorSafetyScore:
    def calculate(self, result: DoorValidationResult, container_width: float) -> DoorSafetyScoreResult:
        coverage = 40.0 * max(0.0, min(1.0, result.coverage))
        continuity = 25.0 * max(0.0, min(1.0, result.continuity_score / 100.0))
        orientation = 15.0 if result.forbidden_orientation_count == 0 else 0.0
        stability = 20.0 if result.stable else 0.0
        gap_penalty = min(20.0, 20.0 * result.max_gap / max(container_width, 1e-9))
        score = max(0.0, min(100.0, coverage + continuity + orientation + stability - gap_penalty))
        return DoorSafetyScoreResult(
            score=round(score, 2), coverage_component=round(coverage, 2),
            continuity_component=round(continuity, 2), orientation_component=orientation,
            stability_component=stability, gap_penalty=round(gap_penalty, 2), issues=result.issues,
        )
