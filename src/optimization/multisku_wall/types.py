from dataclasses import dataclass
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class WallProblemRegion:
    region_id: str
    wall_ids: Tuple[str, ...]
    x_range: Tuple[float, float]
    problem_types: Tuple[str, ...]
    inter_wall_gap_m: float
    left_edge_gap_m: float
    right_edge_gap_m: float
    incomplete_layers: int
    isolated_columns: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "region_id": self.region_id, "wall_ids": list(self.wall_ids),
            "x_range": list(self.x_range), "problem_types": list(self.problem_types),
            "inter_wall_gap_m": self.inter_wall_gap_m,
            "left_edge_gap_m": self.left_edge_gap_m,
            "right_edge_gap_m": self.right_edge_gap_m,
            "incomplete_layers": self.incomplete_layers,
            "isolated_columns": self.isolated_columns,
        }


@dataclass(frozen=True)
class WallCargoPool:
    placement_ids: Tuple[str, ...]
    sku_mix: Dict[str, int]
    remaining_inventory: Dict[str, int]

    def to_dict(self):
        return {"placement_ids": list(self.placement_ids), "sku_mix": self.sku_mix,
                "remaining_inventory": self.remaining_inventory}


@dataclass(frozen=True)
class MixedWallBlueprint:
    blueprint_id: str
    region_id: str
    family: str
    side_anchor: str
    source_wall_ids: Tuple[str, ...]
    sku_mix: Dict[str, int]
    layer_count: int
    column_count: int
    target_width: float
    predicted_gap_m: float

    def to_dict(self):
        return dict(self.__dict__, source_wall_ids=list(self.source_wall_ids))


@dataclass(frozen=True)
class JointWallScore:
    wall_coverage: float
    interface_continuity: float
    side_fill_quality: float
    layer_completion: float
    top_surface_continuity: float
    mixed_inventory_fit: float
    gap_penalty: float
    isolated_column_penalty: float
    final_score: float

    def to_dict(self): return dict(self.__dict__)


@dataclass(frozen=True)
class JointWallCandidate:
    candidate_id: str
    blueprint: MixedWallBlueprint
    placements: Tuple[Any, ...]
    score: JointWallScore
    valid: bool
    rejection_reason: str
    validation: Any

    def to_dict(self):
        return {"candidate_id": self.candidate_id, "blueprint": self.blueprint.to_dict(),
                "score": self.score.to_dict(), "valid": self.valid,
                "rejection_reason": self.rejection_reason}


@dataclass(frozen=True)
class JointWallResult:
    status: str
    placements: Tuple[Any, ...]
    problem_regions: Tuple[WallProblemRegion, ...]
    pools: Tuple[WallCargoPool, ...]
    blueprints: Tuple[MixedWallBlueprint, ...]
    candidates: Tuple[JointWallCandidate, ...]
    selected: Tuple[JointWallCandidate, ...]
    metrics: Dict[str, Any]
    validation: Any

    def to_dict(self):
        return {"status": self.status,
                "problem_regions": [x.to_dict() for x in self.problem_regions],
                "pools": [x.to_dict() for x in self.pools],
                "blueprints": [x.to_dict() for x in self.blueprints],
                "candidates": [x.to_dict() for x in self.candidates],
                "selected": [x.candidate_id for x in self.selected],
                "metrics": self.metrics,
                "validation": {"is_valid": self.validation.is_valid,
                               "violations": len(self.validation.violations)}}
