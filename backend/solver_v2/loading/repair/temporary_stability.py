"""Temporary construction-debt policy for atomic loading groups."""
from backend.solver_v2.loading.planner import LoadingPlan
from backend.solver_v2.loading.repair.types import LoadingGroup,TemporaryDebtPolicy


class TemporaryStabilityResolver:
    def __init__(self,policy=None):self.policy=policy or TemporaryDebtPolicy()
    def resolved_inside_group(self,group:LoadingGroup,plan:LoadingPlan)->bool:
        if not self.policy.allowed:return False
        step=next((s for s in plan.steps if s.action=="PLACE_GROUP"
                   and set(s.placement_ids).issubset(set(group.placement_ids))
                   and group.placement_ids[0] in s.placement_ids),None)
        if step is None or step.action!="PLACE_GROUP":return False
        debts=[d for d in plan.debts if set(d.placement_ids).issubset(set(group.placement_ids))]
        return (bool(step.stability_after_step.get("cluster_stable"))
                and all(d.resolved_at_step==d.created_at_step for d in debts)
                and (not self.policy.must_resolve_inside_group or all(
                    (d.resolved_at_step if d.resolved_at_step is not None else 10**9)-d.created_at_step
                    <=self.policy.max_duration_steps for d in debts)))
