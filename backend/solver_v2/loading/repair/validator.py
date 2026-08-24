"""Candidate DAG checks and full sequence replay."""
from collections import defaultdict,deque
from typing import Dict,Sequence

from backend.solver_v2.domain.models import Placement
from backend.solver_v2.loading.planner import LoadingDependencyGraph,LoadingGroup as PlannerGroup,LoadingSequencePlanner
from backend.solver_v2.loading.repair.temporary_stability import TemporaryStabilityResolver
from backend.solver_v2.loading.repair.types import LoadingGroup,RepairCandidate


class RepairValidator:
    def __init__(self,planner:LoadingSequencePlanner,resolver:TemporaryStabilityResolver):
        self.planner=planner;self.resolver=resolver
    @staticmethod
    def group_preserves_dag(group:LoadingGroup,graph:LoadingDependencyGraph)->bool:
        outgoing,indegree=graph.adjacency();q=deque(sorted(x for x,d in indegree.items() if d==0));seen=0
        while q:
            node=q.popleft();seen+=1
            for nxt in sorted(outgoing[node]):
                indegree[nxt]-=1
                if indegree[nxt]==0:q.append(nxt)
        # Internal dependency edges are legal and are executed in topological
        # order inside PLACE_GROUP. Only an actual graph cycle is rejected.
        return seen==len(graph.nodes)
    def validate(self,candidate:RepairCandidate,graph:LoadingDependencyGraph,
                 placements:Sequence[Placement],membership:Dict[str,Dict[str,str]],
                 active_groups:Sequence[LoadingGroup]=(),base_groups:Sequence[PlannerGroup]=())->RepairCandidate:
        group=candidate.group
        if not self.group_preserves_dag(group,graph):
            candidate.rejection_reason="GROUP_DEPENDENCY_CYCLE";return candidate
        selected=[p for p in placements if p.placement_id in set(group.placement_ids)]
        if len(selected)<2 or not self._has_connected_group_contact(selected):
            candidate.rejection_reason="PAIR_NOT_PHYSICALLY_COHERENT";return candidate
        member=membership.get(group.placement_ids[0],{})
        all_groups=list(active_groups)+[group]
        planner_groups=[]
        for repair_group in all_groups:
            gm=membership.get(repair_group.placement_ids[0],{})
            planner_groups.append(PlannerGroup(repair_group.id,repair_group.placement_ids,
                                  repair_group.type,gm.get("wall_id"),gm.get("row_id")))
        plan=self.planner.plan(placements,repair_groups=planner_groups,
                              prepared_graph=graph,prepared_membership=membership,
                              prepared_groups=base_groups,static_feasible=True)
        group.stability_after=self.resolver.resolved_inside_group(group,plan)
        candidate.repaired_plan=plan
        next_is_distinct_temp=bool(
            plan.infeasible_reasons and
            plan.infeasible_reasons[0].get("reason")=="TEMPORARY_INSTABILITY" and
            not set(plan.infeasible_reasons[0].get("placement_ids",())) & set(group.placement_ids))
        if group.stability_after and (plan.sequence_feasible or next_is_distinct_temp):
            candidate.valid=True
            if not plan.sequence_feasible:candidate.rejection_reason="DOWNSTREAM_TEMPORARY_INSTABILITY"
        elif next_is_distinct_temp:
            # A hard ancestor needs its own group before this pending group can
            # execute. Preserve the candidate and repair that prerequisite.
            candidate.valid=True;candidate.rejection_reason="PREREQUISITE_TEMPORARY_INSTABILITY"
        elif not plan.sequence_feasible:
            candidate.rejection_reason=plan.infeasible_reasons[0]["reason"] if plan.infeasible_reasons else "REPLAY_FAILED"
        else:candidate.rejection_reason="TEMPORARY_DEBT_UNRESOLVED"
        return candidate

    @staticmethod
    def _has_connected_group_contact(placements:Sequence[Placement],eps:float=1e-6)->bool:
        adjacent={p.placement_id:set() for p in placements}
        for index,a in enumerate(placements):
            for b in placements[index+1:]:
                overlap_x=min(a.max_x,b.max_x)-max(a.min_x,b.min_x)
                overlap_y=min(a.max_y,b.max_y)-max(a.min_y,b.min_y)
                overlap_z=min(a.max_z,b.max_z)-max(a.min_z,b.min_z)
                touches_x=abs(a.max_x-b.min_x)<=eps or abs(b.max_x-a.min_x)<=eps
                touches_y=abs(a.max_y-b.min_y)<=eps or abs(b.max_y-a.min_y)<=eps
                touches_z=abs(a.max_z-b.min_z)<=eps or abs(b.max_z-a.min_z)<=eps
                if ((touches_x and overlap_y>eps and overlap_z>eps)
                        or (touches_y and overlap_x>eps and overlap_z>eps)
                        or (touches_z and overlap_x>eps and overlap_y>eps)):
                    adjacent[a.placement_id].add(b.placement_id);adjacent[b.placement_id].add(a.placement_id)
        seen=set();pending=[placements[0].placement_id]
        while pending:
            pid=pending.pop()
            if pid in seen:continue
            seen.add(pid);pending.extend(adjacent[pid]-seen)
        return len(seen)==len(placements)
