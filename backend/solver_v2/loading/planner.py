"""BLK-007 read-only physical loading sequence and operability planner."""
from __future__ import annotations

import hashlib
import json
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from backend.solver_v2.domain.models import (
    CargoSKU, ContainerSpec, PackingRole, Placement, PlacementContext, ZoneType,
)
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.geometry.spatial_index import SpatialIndex
from backend.solver_v2.physics.support_graph import NODE_FLOOR, SupportGraph
from backend.solver_v2.stability.item_stability import ItemStabilityEvaluator
from backend.solver_v2.stability.cluster_stability import ClusterStabilityEvaluator
from backend.solver_v2.structure.wall_model import WallStructureAnalyzer
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from backend.solver_v2.world.state import WorldState


class LoadingMode(str, Enum):
    MANUAL_CARTON = "MANUAL_CARTON"


class LoadingFailureReason(str, Enum):
    INSERTION_BLOCKED = "INSERTION_BLOCKED"
    INSUFFICIENT_CLEARANCE = "INSUFFICIENT_CLEARANCE"
    SUPPORT_DEPENDENCY_CYCLE = "SUPPORT_DEPENDENCY_CYCLE"
    BLOCKING_DEPENDENCY_CYCLE = "BLOCKING_DEPENDENCY_CYCLE"
    DEPENDENCY_CYCLE = "DEPENDENCY_CYCLE"
    TEMPORARY_INSTABILITY = "TEMPORARY_INSTABILITY"
    STABILITY_DEBT_UNRESOLVED = "STABILITY_DEBT_UNRESOLVED"
    DOOR_SEAL_TOO_EARLY = "DOOR_SEAL_TOO_EARLY"
    TOP_FILL_UNREACHABLE = "TOP_FILL_UNREACHABLE"
    NO_VALID_SEQUENCE = "NO_VALID_SEQUENCE"


@dataclass(frozen=True)
class LoadingSequenceConfig:
    loading_mode: LoadingMode = LoadingMode.MANUAL_CARTON
    x_clearance_m: float = 0.0
    y_clearance_m: float = 0.0
    z_clearance_m: float = 0.0
    clearance_risk_threshold_m: float = 0.02
    max_stability_debt_steps: int = 1
    beam_width: int = 4
    max_candidate_checks_per_step: int = 32
    geom_epsilon: float = DEFAULT_GEOM_EPSILON

    def __post_init__(self):
        if min(self.x_clearance_m, self.y_clearance_m, self.z_clearance_m) < 0:
            raise ValueError("Insertion clearance cannot be negative")


@dataclass(frozen=True)
class DependencyEdge:
    before_id: str
    after_id: str
    dependency_type: str
    hard: bool = True

    def to_dict(self):
        return {"before": self.before_id, "after": self.after_id,
                "type": self.dependency_type, "hard": self.hard}


@dataclass
class LoadingDependencyGraph:
    nodes: Dict[str, Placement]
    edges: List[DependencyEdge]
    cycles: List[Dict[str, Any]] = field(default_factory=list)

    def adjacency(self):
        outgoing = defaultdict(set); indegree = {pid: 0 for pid in self.nodes}
        for edge in self.edges:
            if edge.after_id not in outgoing[edge.before_id]:
                outgoing[edge.before_id].add(edge.after_id); indegree[edge.after_id] += 1
        return outgoing, indegree

    def to_dict(self):
        return {"node_count": len(self.nodes), "edge_count": len(self.edges),
                "nodes": sorted(self.nodes), "edges": [e.to_dict() for e in self.edges],
                "cycles": self.cycles}


@dataclass(frozen=True)
class InsertionPath:
    mode: str
    start_x: float
    target_x: float
    swept_aabb: Tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class AccessibilityResult:
    status: str
    blocking_placement_ids: Tuple[str, ...]
    blocked_axis: Optional[str]
    required_clearance: Dict[str, float]
    available_clearance: Dict[str, float]
    insertion_path: InsertionPath

    @property
    def accessible(self):
        return self.status != "BLOCKED"


@dataclass(frozen=True)
class LoadingGroup:
    group_id: str
    placement_ids: Tuple[str, ...]
    group_type: str
    wall_id: Optional[str]
    row_id: Optional[str]

    def to_dict(self):
        return {"group_id": self.group_id, "placement_ids": list(self.placement_ids),
                "group_type": self.group_type, "wall_id": self.wall_id, "row_id": self.row_id}


@dataclass
class TemporaryStabilityDebt:
    placement_ids: Tuple[str, ...]
    reason: str
    created_at_step: int
    required_resolution_step: int
    max_allowed_steps: int
    resolved_at_step: Optional[int] = None

    def to_dict(self):
        return self.__dict__.copy()


@dataclass
class LoadingStep:
    step_index: int
    placement_ids: Tuple[str, ...]
    action: str
    insertion_paths: List[Dict[str, Any]]
    required_clearance: Dict[str, float]
    blocking_check: Dict[str, Any]
    support_after_step: Dict[str, Any]
    stability_after_step: Dict[str, Any]
    wall_id: Optional[str]
    row_id: Optional[str]
    layer_id: Optional[str]
    phase: str

    def to_dict(self):
        return self.__dict__.copy()


@dataclass
class LoadingPlan:
    static_feasible: bool
    sequence_feasible: bool
    steps: List[LoadingStep]
    graph: LoadingDependencyGraph
    groups: List[LoadingGroup]
    infeasible_reasons: List[Dict[str, Any]]
    debts: List[TemporaryStabilityDebt]
    metrics: Dict[str, Any]
    repair_requests: List[Dict[str, Any]]
    runtime_sec: float

    def to_dict(self, include_graph=True):
        return {
            "static_feasible": self.static_feasible, "sequence_feasible": self.sequence_feasible,
            "steps": [s.to_dict() for s in self.steps],
            "dependencies": [e.to_dict() for e in self.graph.edges],
            "dependency_graph": self.graph.to_dict() if include_graph else None,
            "groups": [g.to_dict() for g in self.groups],
            "infeasible_reasons": self.infeasible_reasons,
            "temporary_stability_debts": [d.to_dict() for d in self.debts],
            "metrics": self.metrics, "repair_requests": self.repair_requests,
            "runtime_sec": self.runtime_sec,
        }


class OperabilityValidator:
    """Exact straight-X swept-volume broad/narrow phase over current loaded state."""
    def __init__(self, container: ContainerSpec, config: LoadingSequenceConfig):
        self.container = container; self.config = config

    def insertion_path(self, placement: Placement, loaded_index: SpatialIndex) -> AccessibilityResult:
        c = self.config; eps = c.geom_epsilon
        swept = AABB(
            placement.min_x,
            placement.min_y - c.y_clearance_m,
            placement.min_z,
            self.container.Lx + placement.orientation.dx + c.x_clearance_m,
            placement.max_y + c.y_clearance_m,
            placement.max_z + c.z_clearance_m,
        )
        blockers = []
        for item in loaded_index.query_intersect(swept, eps=eps):
            other = item.aabb
            # Only cargo between the target's front face and the door obstructs
            # the -X insertion. Cargo fully deeper than the target is irrelevant.
            if other.max_x <= placement.min_x + eps:
                continue
            blockers.append(item.item_id)
        available = {
            "x": max(0.0, self.container.Lx - placement.max_x),
            "y": max(0.0, min(placement.min_y, self.container.Ly - placement.max_y)),
            # Floor contact is intended and does not require under-carton clearance.
            "z": max(0.0, self.container.Lz - placement.max_z),
        }
        required = {"x": c.x_clearance_m, "y": c.y_clearance_m, "z": c.z_clearance_m}
        insufficient = [axis for axis in ("y", "z") if available[axis] + eps < required[axis]]
        if blockers or insufficient:
            status = "BLOCKED"
        elif min(available.values()) < c.clearance_risk_threshold_m:
            status = "ACCESSIBLE_WITH_CLEARANCE_RISK"
        else:
            status = "ACCESSIBLE"
        return AccessibilityResult(
            status=status, blocking_placement_ids=tuple(sorted(blockers)),
            blocked_axis="X" if blockers else (insufficient[0].upper() if insufficient else None),
            required_clearance=required, available_clearance=available,
            insertion_path=InsertionPath(
                "STRAIGHT_X_INSERTION", self.container.Lx, placement.min_x,
                (swept.min_x, swept.min_y, swept.min_z, swept.max_x, swept.max_y, swept.max_z),
            ),
        )


class LoadingSequencePlanner:
    def __init__(self, container: ContainerSpec, cargo: Sequence[CargoSKU],
                 config: Optional[LoadingSequenceConfig] = None):
        self.container = container; self.cargo = list(cargo)
        self.catalog = {s.sku_id: s for s in cargo}
        self.config = config or LoadingSequenceConfig()
        self.validator = OperabilityValidator(container, self.config)
        self.item_stability = ItemStabilityEvaluator()
        self.cluster_stability = ClusterStabilityEvaluator()

    def build_dependency_graph(self, placements: Sequence[Placement]) -> Tuple[LoadingDependencyGraph, Dict[str, Dict[str, str]], List[LoadingGroup]]:
        nodes = {p.placement_id: p for p in placements}
        edges: Dict[Tuple[str, str, str], DependencyEdge] = {}
        support = SupportGraph(self.container)
        for p in placements: support.add_placement(p)
        for upper in placements:
            for edge in support.get_support_edges(upper.placement_id):
                if edge.lower_id != NODE_FLOOR:
                    dep = DependencyEdge(edge.lower_id, upper.placement_id, "SUPPORT")
                    edges[(dep.before_id, dep.after_id, dep.dependency_type)] = dep

        final_index = SpatialIndex(cell_size=0.5)
        for p in placements: final_index.insert(p.placement_id, AABB.from_placement(p), p)
        empty = SpatialIndex(cell_size=0.5)
        for target in placements:
            swept = self.validator.insertion_path(target, empty).insertion_path.swept_aabb
            query = AABB(*swept)
            for item in final_index.query_intersect(query):
                blocker = item.data
                if blocker.placement_id == target.placement_id:
                    continue
                if blocker.min_x >= target.max_x - self.config.geom_epsilon:
                    dep_type = "CEILING_CLOSURE" if target.context == PlacementContext.TOP_FILL else "BLOCKING"
                    dep = DependencyEdge(target.placement_id, blocker.placement_id, dep_type)
                    edges[(dep.before_id, dep.after_id, dep.dependency_type)] = dep

        door_ids = [p.placement_id for p in placements if p.context == PlacementContext.DOOR_SEAL]
        for door_id in door_ids:
            door = nodes[door_id]
            door_corridor = AABB(0.0, door.min_y, door.min_z, max(0.0, door.min_x), door.max_y, door.max_z)
            for item in final_index.query_intersect(door_corridor):
                p = item.data
                overlap_y = min(p.max_y, door.max_y) - max(p.min_y, door.min_y)
                overlap_z = min(p.max_z, door.max_z) - max(p.min_z, door.min_z)
                requires_passage = (
                    p.max_x <= door.min_x + self.config.geom_epsilon
                    and overlap_y > self.config.geom_epsilon
                    and overlap_z > self.config.geom_epsilon
                )
                if p.placement_id != door_id and p.context != PlacementContext.DOOR_SEAL and requires_passage:
                    dep = DependencyEdge(p.placement_id, door_id, "DOOR_SEAL_LAST")
                    edges[(dep.before_id, dep.after_id, dep.dependency_type)] = dep

        analyzer = WallStructureAnalyzer(self.container)
        walls = analyzer.extract_walls(list(placements))
        membership: Dict[str, Dict[str, str]] = {}
        groups: List[LoadingGroup] = []
        for wall in walls:
            for layer in wall.layers:
                for p in layer.placements:
                    membership.setdefault(p.placement_id, {})["layer_id"] = layer.layer_id
            for row in wall.rows:
                ordered = sorted(row.placements, key=lambda p: (p.min_y, p.placement_id))
                for p in ordered:
                    membership.setdefault(p.placement_id, {}).update({"wall_id": wall.wall_id, "row_id": row.row_id})
                thin = [p for p in ordered if p.orientation.dz / max(min(p.orientation.dx, p.orientation.dy), .01) > 2.5]
                for index in range(0, len(thin) - 1, 2):
                    pair = thin[index:index+2]
                    groups.append(LoadingGroup(
                        f"THIN_PAIR_{wall.wall_id}_{row.row_id}_{index//2}",
                        tuple(p.placement_id for p in pair), "THIN_CARGO_PAIR", wall.wall_id, row.row_id,
                    ))
        graph = LoadingDependencyGraph(nodes, sorted(edges.values(), key=lambda e: (e.before_id, e.after_id, e.dependency_type)))
        graph.cycles = self._find_cycles(graph)
        return graph, membership, groups

    def _find_cycles(self, graph: LoadingDependencyGraph) -> List[Dict[str, Any]]:
        outgoing, indegree = graph.adjacency(); queue = deque(sorted(pid for pid, d in indegree.items() if d == 0)); seen=[]
        while queue:
            node=queue.popleft(); seen.append(node)
            for nxt in sorted(outgoing[node]):
                indegree[nxt]-=1
                if indegree[nxt]==0: queue.append(nxt)
        remaining=sorted(pid for pid,d in indegree.items() if d>0)
        if not remaining: return []
        types=sorted({e.dependency_type for e in graph.edges if e.before_id in remaining and e.after_id in remaining})
        return [{"placement_ids": remaining, "dependency_types": types}]

    def plan(
        self,
        placements: Sequence[Placement],
        repair_groups: Optional[Sequence[LoadingGroup]] = None,
        prepared_graph: Optional[LoadingDependencyGraph] = None,
        prepared_membership: Optional[Dict[str, Dict[str, str]]] = None,
        prepared_groups: Optional[Sequence[LoadingGroup]] = None,
        static_feasible: Optional[bool] = None,
    ) -> LoadingPlan:
        started=time.perf_counter(); placements=list(placements)
        static=(IndependentGlobalValidator.validate(self.container, placements, self.cargo, options={"tipping_moment_constraint": False}).is_valid
                if static_feasible is None else static_feasible)
        if prepared_graph is not None and prepared_membership is not None and prepared_groups is not None:
            graph=prepared_graph;membership=prepared_membership;groups=list(prepared_groups)
        else:
            graph,membership,groups=self.build_dependency_graph(placements)
        # Repair groups may use an already stable neighbor as a construction
        # anchor. Keep the original heuristic group that made that anchor
        # stable; the repair group controls only its failed target's step.
        repair_group_list: List[LoadingGroup] = []
        if repair_groups:
            repair_group_list = list(repair_groups)
            groups = groups + repair_group_list
        failures=[]; repairs=[]; steps=[]; debts=[]; blocked_checks=0
        if not static:
            failures.append({"reason":"STATIC_LAYOUT_INVALID","placement_ids":[]})
        if graph.cycles:
            types={t for c in graph.cycles for t in c["dependency_types"]}
            reason=(LoadingFailureReason.SUPPORT_DEPENDENCY_CYCLE.value if types=={"SUPPORT"}
                    else LoadingFailureReason.BLOCKING_DEPENDENCY_CYCLE.value if types <= {"BLOCKING","CEILING_CLOSURE"}
                    else LoadingFailureReason.DEPENDENCY_CYCLE.value)
            failures.append({"reason":reason,"cycles":graph.cycles})
            repairs.append({
                "failure": reason,
                "blocked_placements": graph.cycles[0]["placement_ids"],
                "dependency_types": graph.cycles[0]["dependency_types"],
                "suggested_region": "preserve deep-to-door corridor or avoid support/blocking inversion",
            })

        outgoing,indegree=graph.adjacency(); loaded=WorldState(self.container,self.cargo); remaining=set(graph.nodes)
        default_group_by_pid={pid:g for g in groups if g not in repair_group_list for pid in g.placement_ids}
        repair_group_by_pid={pid:g for g in repair_group_list for pid in g.placement_ids}
        # While a failed thin target waits for its stable anchor, complete only
        # the anchor's existing hard-dependency chain ahead of unrelated phases.
        # This is a topological priority, never a dependency override.
        repair_targets={g.placement_ids[0] for g in repair_group_list if g.placement_ids}
        unlock_seeds=set()
        for g in repair_group_list:
            for anchor in g.placement_ids[1:]:
                unlock_seeds.add(anchor)
                prior=default_group_by_pid.get(anchor)
                if prior:unlock_seeds.update(prior.placement_ids)
        incoming=defaultdict(set)
        for edge in graph.edges:incoming[edge.after_id].add(edge.before_id)
        repair_unlock_ids=set(unlock_seeds);stack=list(unlock_seeds)
        while stack:
            node=stack.pop()
            for prior in incoming[node]:
                if prior not in repair_unlock_ids:
                    repair_unlock_ids.add(prior);stack.append(prior)
        repair_unlock_ids-=repair_targets
        last_wall=last_row=last_phase=None; wall_switch=row_switch=phase_switch=0; clearances=[]
        while remaining and not failures:
            available=sorted((pid for pid in remaining if indegree[pid]==0),
                             key=lambda pid:(0 if pid in repair_unlock_ids else 1,
                                             self._priority(graph.nodes[pid],membership.get(pid,{}),last_wall)))
            chosen=None; chosen_access=[]; chosen_group=None
            for pid in available[:self.config.max_candidate_checks_per_step]:
                repair_group=repair_group_by_pid.get(pid)
                pending_repair=tuple(x for x in repair_group.placement_ids if x in remaining) if repair_group else ()
                loaded_anchors=tuple(x for x in repair_group.placement_ids if x not in remaining) if repair_group else ()
                repair_ready=bool(repair_group and all(
                    indegree[x]-sum(parent in pending_repair for parent in incoming[x])==0
                    for x in pending_repair))
                anchor_has_original_group=bool(repair_group and any(
                    x!=repair_group.placement_ids[0] and x in remaining and x in default_group_by_pid
                    for x in repair_group.placement_ids))
                if (repair_group and pid==repair_group.placement_ids[0] and not loaded_anchors
                        and (not repair_ready or anchor_has_original_group)):
                    # The failed target cannot leak out before its intended
                    # anchor has been made stable by the original sequence.
                    continue
                use_repair=bool(repair_group and repair_ready and
                                (loaded_anchors or (len(pending_repair)>1 and not anchor_has_original_group)))
                group=repair_group if use_repair else default_group_by_pid.get(pid)
                if use_repair:
                    ids=self._group_topological_order(pending_repair,graph.edges)
                else:
                    ids=tuple(x for x in group.placement_ids if x in remaining) if group and all(indegree[x]==0 for x in group.placement_ids if x in remaining) else (pid,)
                local_index=self._clone_index(loaded.spatial_index)
                accesses=[]; ok=True
                for item_id in ids:
                    access=self.validator.insertion_path(graph.nodes[item_id],local_index); accesses.append(access)
                    if not access.accessible: ok=False; blocked_checks+=1; break
                    local_index.insert(item_id,AABB.from_placement(graph.nodes[item_id]),graph.nodes[item_id])
                if ok: chosen=ids; chosen_access=accesses; chosen_group=group if len(ids)>1 or use_repair else None; break
            if chosen is None:
                reason=LoadingFailureReason.NO_VALID_SEQUENCE.value
                blocked=[]
                for pid in available:
                    access=self.validator.insertion_path(graph.nodes[pid],loaded.spatial_index)
                    blocked.extend(access.blocking_placement_ids)
                    if graph.nodes[pid].context==PlacementContext.TOP_FILL: reason=LoadingFailureReason.TOP_FILL_UNREACHABLE.value
                    elif graph.nodes[pid].context==PlacementContext.DOOR_SEAL: reason=LoadingFailureReason.DOOR_SEAL_TOO_EARLY.value
                    elif access.blocked_axis in ("Y","Z"): reason=LoadingFailureReason.INSUFFICIENT_CLEARANCE.value
                    elif access.blocking_placement_ids: reason=LoadingFailureReason.INSERTION_BLOCKED.value
                failures.append({"reason":reason,"candidate_ids":available,"blocking_placement_ids":sorted(set(blocked))})
                repairs.append({"failure":reason,"blocked_placements":available,"blockers":sorted(set(blocked)),"suggested_region":"retain insertion corridor from door"})
                break
            step_index=len(steps)+1; unstable=[]
            for pid in chosen:
                p=graph.nodes[pid]; loaded.commit(p)
                report=self.item_stability.evaluate_placement(p,self.catalog.get(p.sku_id),loaded.support_graph,loaded.contact_graph,self.container)
                thin_unbraced = report.slenderness > 2.5 and not report.has_lateral_bracing and chosen_group is None
                if not report.is_stable or thin_unbraced: unstable.append(pid)
            group_requires_debt = bool(chosen_group and any(
                graph.nodes[pid].orientation.dz /
                max(min(graph.nodes[pid].orientation.dx, graph.nodes[pid].orientation.dy), .01) > 2.5
                for pid in chosen
            ))
            if group_requires_debt:
                debts.append(TemporaryStabilityDebt(
                    tuple(chosen), "thin pair requires consecutive placement",
                    step_index, step_index, self.config.max_stability_debt_steps, step_index,
                ))
            cluster_ok = True
            if unstable:
                cluster_reports = self.cluster_stability.evaluate_clusters(loaded.placements, loaded.contact_graph, self.container)
                cluster_ok = all(r.is_stable for r in cluster_reports)
                if chosen_group and cluster_ok:
                    if not group_requires_debt:
                        debts.append(TemporaryStabilityDebt(tuple(unstable),"paired cargo requires consecutive bracing",step_index,step_index,1,step_index))
                else:
                    failures.append({"reason":LoadingFailureReason.TEMPORARY_INSTABILITY.value,"placement_ids":unstable})
                    repairs.append({"failure":LoadingFailureReason.TEMPORARY_INSTABILITY.value,"blocked_placements":unstable,"suggested_region":"same-row paired loading"})
                    break
            member=membership.get(chosen[0],{}); phase=self._phase(graph.nodes[chosen[0]])
            wall=member.get("wall_id"); row=member.get("row_id")
            wall_switch+=int(last_wall is not None and wall!=last_wall); row_switch+=int(last_row is not None and row!=last_row); phase_switch+=int(last_phase is not None and phase!=last_phase)
            last_wall,last_row,last_phase=wall,row,phase
            for access in chosen_access: clearances.append(min(access.available_clearance.values()))
            steps.append(LoadingStep(
                step_index,chosen,"PLACE_GROUP" if chosen_group else ("DOOR_SEAL" if phase=="DOOR_SEAL" else "PLACE"),
                [{"mode":a.insertion_path.mode,"start_x":a.insertion_path.start_x,"target_x":a.insertion_path.target_x,"swept_aabb":a.insertion_path.swept_aabb} for a in chosen_access],
                chosen_access[0].required_clearance,
                {"status":"PASS","blocking_placement_ids":[]},
                {"grounded":all(loaded.support_graph.is_grounded_to_floor(pid) for pid in chosen)},
                {"item_stable":not unstable,"cluster_stable":cluster_ok,"temporary_debt_created":bool(unstable)},
                wall,row,member.get("layer_id"),phase,
            ))
            for pid in chosen:
                remaining.remove(pid)
                for nxt in outgoing[pid]: indegree[nxt]-=1

        unresolved=[d for d in debts if d.resolved_at_step is None]
        if unresolved: failures.append({"reason":LoadingFailureReason.STABILITY_DEBT_UNRESOLVED.value,"placement_ids":[p for d in unresolved for p in d.placement_ids]})
        feasible=static and not failures and not remaining
        max_depth=self._max_dependency_depth(graph)
        metrics={
            "total_steps":len(steps),"group_steps":sum(s.action=="PLACE_GROUP" for s in steps),
            "individual_steps":sum(len(s.placement_ids) for s in steps if s.action!="PLACE_GROUP"),
            "wall_switch_count":wall_switch,"row_switch_count":row_switch,"phase_switch_count":phase_switch,
            "max_dependency_depth":max_depth,"dependency_edges":len(graph.edges),
            "blocked_candidate_steps":blocked_checks,"temporary_stability_debt_count":len(debts),
            "max_stability_debt_duration":max((d.resolved_at_step-d.created_at_step for d in debts if d.resolved_at_step is not None),default=0),
            "min_path_clearance":min(clearances,default=0.0),"average_path_clearance":sum(clearances)/max(len(clearances),1),
            "sequence_complexity_score":len(steps)+wall_switch*2+row_switch+len(debts)*5+blocked_checks*3,
            "placements_planned":sum(len(s.placement_ids) for s in steps),
        }
        runtime=time.perf_counter()-started; metrics["runtime_sec"]=runtime
        metrics["sequence_signature"]=hashlib.sha256(json.dumps([
            (s.action,s.placement_ids,s.phase) for s in steps],separators=(",",":"),sort_keys=True).encode()).hexdigest()
        return LoadingPlan(static,feasible,steps,graph,groups,failures,debts,metrics,repairs,runtime)

    @staticmethod
    def _clone_index(index:SpatialIndex)->SpatialIndex:
        clone=SpatialIndex(cell_size=index.cell_size)
        for item in index.all_items(): clone.insert(item.item_id,item.aabb,item.data)
        return clone

    @staticmethod
    def _phase(p:Placement)->str:
        if p.context==PlacementContext.DOOR_SEAL:return "DOOR_SEAL"
        if p.context==PlacementContext.TOP_FILL:return "TOP_FILL"
        if p.context==PlacementContext.GAP_FILL:return "TRANSITION"
        return "MAIN"

    def _priority(self,p:Placement,member:Dict[str,str],last_wall:Optional[str]):
        phase={"MAIN":0,"TOP_FILL":1,"TRANSITION":2,"DOOR_SEAL":3}[self._phase(p)]
        continuity=0 if last_wall and member.get("wall_id")==last_wall else 1
        return (phase,round(p.min_x,6),round(p.min_z,6),continuity,-p.volume,p.placement_id)

    @staticmethod
    def _max_dependency_depth(graph:LoadingDependencyGraph)->int:
        outgoing,indegree=graph.adjacency(); q=deque(sorted(x for x,d in indegree.items() if d==0)); depth={x:0 for x in q}
        while q:
            n=q.popleft()
            for nxt in sorted(outgoing[n]):
                depth[nxt]=max(depth.get(nxt,0),depth[n]+1);indegree[nxt]-=1
                if indegree[nxt]==0:q.append(nxt)
        return max(depth.values(),default=0)

    @staticmethod
    def _group_topological_order(ids:Sequence[str],edges:Sequence[DependencyEdge])->Tuple[str,...]:
        members=set(ids);outgoing=defaultdict(set);indegree={pid:0 for pid in ids}
        for edge in edges:
            if edge.before_id in members and edge.after_id in members and edge.after_id not in outgoing[edge.before_id]:
                outgoing[edge.before_id].add(edge.after_id);indegree[edge.after_id]+=1
        q=deque(sorted(pid for pid,d in indegree.items() if d==0));ordered=[]
        while q:
            node=q.popleft();ordered.append(node)
            for nxt in sorted(outgoing[node]):
                indegree[nxt]-=1
                if indegree[nxt]==0:q.append(nxt)
        return tuple(ordered) if len(ordered)==len(ids) else tuple()
