"""Sequence-aware, geometry-preserving temporary-instability repair engine."""
import hashlib,json,time
from typing import Any,Dict,Optional,Sequence

from backend.solver_v2.domain.models import CargoSKU,ContainerSpec,Placement
from backend.solver_v2.loading.planner import (LoadingDependencyGraph,LoadingGroup as PlannerGroup,
                                               LoadingPlan,LoadingSequenceConfig,LoadingSequencePlanner)
from backend.solver_v2.loading.repair.candidate_generator import RepairCandidateGenerator
from backend.solver_v2.loading.repair.group_builder import LoadingGroupBuilder
from backend.solver_v2.loading.repair.scorer import RepairScorer
from backend.solver_v2.loading.repair.temporary_stability import TemporaryStabilityResolver
from backend.solver_v2.loading.repair.types import RepairAction,RepairRequest,RepairResult,TemporaryDebtPolicy
from backend.solver_v2.loading.repair.validator import RepairValidator


class SequenceRepairEngine:
    SUPPORTED_FAILURE="TEMPORARY_INSTABILITY"
    def __init__(self,container:ContainerSpec,cargo:Sequence[CargoSKU],
                 sequence_config:Optional[LoadingSequenceConfig]=None,
                 thin_ratio_threshold:float=.35,debt_policy:Optional[TemporaryDebtPolicy]=None):
        self.planner=LoadingSequencePlanner(container,cargo,sequence_config)
        self.builder=LoadingGroupBuilder(thin_ratio_threshold)
        self.generator=RepairCandidateGenerator(self.builder)
        self.resolver=TemporaryStabilityResolver(debt_policy)
        self.validator=RepairValidator(self.planner,self.resolver);self.scorer=RepairScorer()
    def repair(self,loading_plan:LoadingPlan,failure_report:Dict[str,Any],
               dependency_graph:LoadingDependencyGraph,placements:Sequence[Placement],stability_graph:Any=None)->RepairResult:
        started=time.perf_counter();request=RepairRequest.from_failure(failure_report)
        before=self._geometry_signature(placements);graph,membership,existing_groups=self.planner.build_dependency_graph(placements)
        candidates=[];groups=[];actions=[];updated=loading_plan;current_request=request
        max_repairs=8
        for _ in range(max_repairs):
            if current_request.failure!=self.SUPPORTED_FAILURE:break
            stage=self.generator.generate(current_request,graph,placements,membership,existing_groups)
            selected=None
            for candidate in stage:
                superseded=[g for g in groups if not g.stability_after
                            and set(g.placement_ids)&set(candidate.group.placement_ids)]
                active=[g for g in groups if g not in superseded]
                self.validator.validate(candidate,graph,placements,membership,active,existing_groups)
                candidate.score=self.scorer.score(candidate.group)
                candidates.append(candidate)
                if candidate.valid:
                    if superseded:
                        removed={g.id for g in superseded};groups=active
                        actions=[a for a in actions if a.group_id not in removed]
                    selected=candidate;break
            if not selected:break
            groups.append(selected.group);updated=selected.repaired_plan
            action_type="CREATE_PAIR_GROUP" if selected.group.type=="PAIR" else "CREATE_ROW_SEGMENT_GROUP"
            actions.append(RepairAction(action_type,selected.group.placement_ids,selected.group.id,selected.group.reason))
            if updated.sequence_feasible:break
            next_failure=updated.infeasible_reasons[0] if updated.infeasible_reasons else {}
            next_request=RepairRequest.from_failure(next_failure)
            if not next_request.placement_ids or next_request.placement_ids==current_request.placement_ids:break
            current_request=next_request
        if updated.sequence_feasible:
            for group in groups:group.stability_after=self.resolver.resolved_inside_group(group,updated)
            resolved=[g for g in groups if g.stability_after]
            if len(resolved)!=len(groups):
                planner_groups=[]
                for group in resolved:
                    gm=membership.get(group.placement_ids[0],{})
                    planner_groups.append(PlannerGroup(group.id,group.placement_ids,group.type,
                                                       gm.get("wall_id"),gm.get("row_id")))
                updated=self.planner.plan(placements,repair_groups=planner_groups,
                                          prepared_graph=graph,prepared_membership=membership,
                                          prepared_groups=existing_groups,static_feasible=True)
                for group in resolved:group.stability_after=self.resolver.resolved_inside_group(group,updated)
                groups=resolved
                keep={g.id for g in groups};actions=[a for a in actions if a.group_id in keep]
        changed=before!=self._geometry_signature(placements)
        repaired=bool(groups and updated.sequence_feasible and not changed and all(g.stability_after for g in groups))
        runtime=time.perf_counter()-started
        signature=hashlib.sha256(json.dumps([a.to_dict() for a in actions],sort_keys=True,separators=(",",":")).encode()).hexdigest()
        validation={"sequence_feasible":updated.sequence_feasible,"geometry_changed":changed,
                    "dependency_dag":not bool(graph.cycles),
                    "temporary_stability_resolved":bool(repaired and all(g.stability_after for g in groups)),
                    "full_sequence_replayed":bool(groups)}
        metrics={"repair_attempts":len(candidates),"repair_success":int(repaired),"repair_failure":int(not repaired),
                 "candidate_count":len(candidates),"valid_candidate_count":sum(c.valid for c in candidates),
                 "average_group_size":sum(len(c.group.placement_ids) for c in candidates)/len(candidates) if candidates else 0.0,
                 "dependency_changes":0,"sequence_improvement":int(repaired and not loading_plan.sequence_feasible),
                 "geometry_changes":int(changed),"changed_steps":len(actions) if repaired else 0,
                 "runtime_sec":runtime,"repair_signature":signature}
        return RepairResult(repaired,actions,updated,validation,metrics,groups,candidates)
    @staticmethod
    def _geometry_signature(placements):
        rows=[(p.placement_id,p.sku_id,p.position.x,p.position.y,p.position.z,
               p.orientation.dx,p.orientation.dy,p.orientation.dz,p.orientation.name) for p in placements]
        return hashlib.sha256(json.dumps(sorted(rows),separators=(",",":")).encode()).hexdigest()
