"""Deterministic, local loading-group construction."""
import hashlib
from typing import Sequence

from backend.solver_v2.domain.models import Placement
from backend.solver_v2.loading.repair.types import LoadingGroup


class LoadingGroupBuilder:
    def __init__(self, thin_ratio_threshold: float = 0.35):
        if thin_ratio_threshold <= 0: raise ValueError("thin_ratio_threshold must be positive")
        self.thin_ratio_threshold=thin_ratio_threshold

    def is_thin_cargo(self, placement: Placement) -> bool:
        o=placement.orientation
        return min(o.dx,o.dy)/max(o.dz,1e-9) < self.thin_ratio_threshold

    @staticmethod
    def manhattan_distance(a:Placement,b:Placement)->float:
        return abs(a.position.x-b.position.x)+abs(a.position.y-b.position.y)+abs(a.position.z-b.position.z)

    def build(self, placements:Sequence[Placement], group_type:str, reason:str,
              scope:str, distance:float)->LoadingGroup:
        ids=tuple(p.placement_id for p in placements)
        digest=hashlib.sha256("|".join(sorted(ids)).encode()).hexdigest()[:12]
        return LoadingGroup(f"REPAIR_{group_type}_{digest}",ids,group_type,reason,
                            scope=scope,distance=round(distance,6))
