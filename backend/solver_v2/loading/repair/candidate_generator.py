"""Bounded local candidates for temporary-instability repair."""
from typing import Dict,List,Sequence

from backend.solver_v2.domain.models import Placement
from backend.solver_v2.loading.planner import LoadingDependencyGraph,LoadingGroup as PlannerGroup
from backend.solver_v2.loading.repair.group_builder import LoadingGroupBuilder
from backend.solver_v2.loading.repair.types import RepairCandidate,RepairRequest


class RepairCandidateGenerator:
    SCOPE_PRIORITY=("SAME_ROW","SAME_LAYER","SAME_WALL","SAME_SKU","SIMILAR_DIMENSION")
    def __init__(self,group_builder:LoadingGroupBuilder,max_candidates:int=16):
        self.group_builder=group_builder;self.max_candidates=max_candidates

    def generate(self,request:RepairRequest,graph:LoadingDependencyGraph,
                 placements:Sequence[Placement],membership:Dict[str,Dict[str,str]],
                 existing_groups:Sequence[PlannerGroup]=())->List[RepairCandidate]:
        by_id={p.placement_id:p for p in placements}
        if not request.placement_ids or request.placement_ids[0] not in by_id:return []
        target=by_id[request.placement_ids[0]];tm=membership.get(target.placement_id,{})
        ranked=[]
        for neighbor in placements:
            if neighbor.placement_id==target.placement_id:continue
            nm=membership.get(neighbor.placement_id,{})
            scope=self._scope(target,neighbor,tm,nm)
            dist=self.group_builder.manhattan_distance(target,neighbor)
            similarity=self._dimension_similarity(target,neighbor)
            ranked.append((self.SCOPE_PRIORITY.index(scope),dist,-similarity,neighbor.placement_id,scope,neighbor))
        out=[];seen=set()
        for _,distance,_,_,scope,neighbor in sorted(ranked):
            selected=[target,neighbor];group_type="PAIR"
            ids=tuple(sorted(p.placement_id for p in selected))
            if ids in seen:continue
            seen.add(ids)
            group=self.group_builder.build(selected,group_type,"resolve temporary thin-cargo instability",scope,distance)
            out.append(RepairCandidate(group))
            if len(out)>=self.max_candidates:break
        return out

    @staticmethod
    def _scope(a,b,am,bm):
        if am.get("row_id") and am.get("row_id")==bm.get("row_id"):return "SAME_ROW"
        if am.get("layer_id") and am.get("layer_id")==bm.get("layer_id"):return "SAME_LAYER"
        if am.get("wall_id") and am.get("wall_id")==bm.get("wall_id"):return "SAME_WALL"
        if a.sku_id==b.sku_id:return "SAME_SKU"
        return "SIMILAR_DIMENSION"

    @staticmethod
    def _dimension_similarity(a,b):
        ad=(a.orientation.dx,a.orientation.dy,a.orientation.dz);bd=(b.orientation.dx,b.orientation.dy,b.orientation.dz)
        return sum(min(x,y)/max(x,y,1e-9) for x,y in zip(ad,bd))/3.0
