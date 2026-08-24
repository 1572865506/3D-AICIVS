"""Generic minimal-change score for sequence repair."""
from backend.solver_v2.loading.repair.types import LoadingGroup,RepairScore


class RepairScorer:
    def score(self,group:LoadingGroup,dependency_changes:int=0)->RepairScore:
        return RepairScore(100.0 if group.stability_after and not group.stability_before else 0.0,
                           5.0,max(0,len(group.placement_ids)-2)*10.0,dependency_changes*20.0)
