"""
Cluster Stability Evaluator for Solver V2 (Agent 07).
Evaluates interconnected cargo groups:
- Connected components in ContactGraph
- Combined Center of Mass (COM) for the cluster
- Collective floor support base polygon
- Lateral interlock score (staggered seams, cross-layer bracing)
"""
from typing import Dict, List, Tuple, Optional, Set, Any
from collections import deque
import math

from backend.solver_v2.domain.models import Placement, Point3D, ContainerSpec
from backend.solver_v2.physics.contact_graph import ContactGraph, NODE_FLOOR
from backend.solver_v2.stability.models import StabilityState, ClusterStabilityReport
from backend.solver_v2.geometry.aabb import DEFAULT_GEOM_EPSILON


class ClusterStabilityEvaluator:
    """
    Evaluates group stability and lateral interlocking of interconnected cargo clusters.
    """

    def __init__(self, geom_epsilon: float = DEFAULT_GEOM_EPSILON):
        self.geom_epsilon = geom_epsilon

    def evaluate_clusters(
        self,
        placements: List[Placement],
        contact_graph: ContactGraph,
        container: ContainerSpec,
    ) -> List[ClusterStabilityReport]:
        """
        Extracts connected cargo clusters and computes collective stability reports.
        """
        if not placements:
            return []

        p_map = {p.placement_id: p for p in placements}
        visited: Set[str] = set()
        cluster_reports: List[ClusterStabilityReport] = []
        cluster_idx = 0

        # Find connected components over item-to-item contacts
        for pid in p_map:
            if pid in visited:
                continue

            cluster_pids: List[str] = []
            queue = deque([pid])
            visited.add(pid)

            while queue:
                curr_id = queue.popleft()
                cluster_pids.append(curr_id)

                for edge in contact_graph.get_contacts(curr_id):
                    neighbor = edge.node_b
                    if neighbor in p_map and neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)

            # Evaluate this cluster
            report = self._evaluate_single_cluster(
                cluster_id=f"cluster_{cluster_idx:03d}",
                pids=cluster_pids,
                p_map=p_map,
                contact_graph=contact_graph,
            )
            cluster_reports.append(report)
            cluster_idx += 1

        return cluster_reports

    def _evaluate_single_cluster(
        self,
        cluster_id: str,
        pids: List[str],
        p_map: Dict[str, Placement],
        contact_graph: ContactGraph,
    ) -> ClusterStabilityReport:
        eps = self.geom_epsilon
        total_w = 0.0
        w_com_x = 0.0
        w_com_y = 0.0
        w_com_z = 0.0

        floor_contact_area = 0.0
        floor_min_x = float("inf")
        floor_max_x = float("-inf")
        floor_min_y = float("inf")
        floor_max_y = float("-inf")

        internal_contact_area = 0.0

        for pid in pids:
            p = p_map[pid]
            w = p.weight_kg
            cx = p.position.x + p.orientation.dx / 2.0
            cy = p.position.y + p.orientation.dy / 2.0
            cz = p.position.z + p.orientation.dz / 2.0

            total_w += w
            w_com_x += w * cx
            w_com_y += w * cy
            w_com_z += w * cz

            # Check contacts
            for edge in contact_graph.get_contacts(pid):
                if edge.node_b == NODE_FLOOR:
                    floor_contact_area += edge.contact_area
                    floor_min_x = min(floor_min_x, edge.contact_box.min_x)
                    floor_max_x = max(floor_max_x, edge.contact_box.max_x)
                    floor_min_y = min(floor_min_y, edge.contact_box.min_y)
                    floor_max_y = max(floor_max_y, edge.contact_box.max_y)
                elif edge.node_b in p_map:
                    internal_contact_area += edge.contact_area

        if total_w > 0:
            comb_com = Point3D(
                x=w_com_x / total_w,
                y=w_com_y / total_w,
                z=w_com_z / total_w,
            )
        else:
            comb_com = Point3D(0.0, 0.0, 0.0)

        # COM inside floor base polygon
        has_floor = floor_contact_area > eps
        com_in_base = False
        if has_floor:
            com_in_base = (
                (floor_min_x - eps <= comb_com.x <= floor_max_x + eps) and
                (floor_min_y - eps <= comb_com.y <= floor_max_y + eps)
            )

        # Interlock score: internal contacts normalized by item count
        item_count = len(pids)
        interlock_score = min(1.0, (internal_contact_area / (item_count * 0.5))) if item_count > 1 else 0.0

        reasons = []
        if not has_floor:
            state = StabilityState.UNSTABLE
            reasons.append("Cluster has zero direct floor contact")
        elif not com_in_base:
            state = StabilityState.UNSTABLE
            reasons.append(f"Combined COM ({comb_com.x:.2f}, {comb_com.y:.2f}) falls outside cluster floor footprint")
        elif interlock_score > 0.3:
            state = StabilityState.SELF_STABLE
            reasons.append(f"Interlocked stable cluster (score: {interlock_score:.2f})")
        else:
            state = StabilityState.SUPPORTED_STABLE
            reasons.append("Stable cargo cluster on floor")

        return ClusterStabilityReport(
            cluster_id=cluster_id,
            placement_ids=pids,
            total_weight_kg=total_w,
            combined_com=comb_com,
            floor_support_area=floor_contact_area,
            com_in_floor_base=com_in_base,
            lateral_interlock_score=interlock_score,
            stability_state=state,
            is_stable=(state != StabilityState.UNSTABLE),
            reasons=reasons,
        )
