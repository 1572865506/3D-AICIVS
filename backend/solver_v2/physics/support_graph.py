"""
SupportGraph Engine for Solver V2 (Agent 07).
Direct Acyclic Graph (DAG) modeling vertical load-bearing connections:
- Upper cargo items are supported by lower items or the container floor.
- Nodes: Placements + virtual node "FLOOR".
- Directed Edges:
  - Downward: upper item -> lower item / "FLOOR" (supporting relationships)
  - Upward: lower item -> upper item (supported relationships)
- Supports exact support ratio, load ratio, topological ordering, and atomic rollback.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Set, Any
from collections import deque
import math

from backend.solver_v2.domain.models import Placement, Point3D, BoxDim, ContainerSpec
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.physics.contact_graph import NODE_FLOOR


@dataclass(frozen=True)
class SupportEdge:
    """
    Directed vertical support edge between upper item and supporting base (item or FLOOR).
    """
    upper_id: str             # Item on top that requires support
    lower_id: str             # Item below (or "FLOOR") providing support
    contact_area: float       # XY contact surface area in m^2
    support_ratio: float      # contact_area / upper_base_area (0.0 to 1.0)
    load_ratio: float         # contact_area / lower_top_area (0.0 to 1.0, 0.0 for floor)
    overlap_box: AABB         # Contact interface AABB


class SupportGraph:
    """
    Directed Acyclic Graph (DAG) for vertical cargo support and load bearing.
    """

    def __init__(
        self,
        container: ContainerSpec,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
    ):
        self.container = container
        self.geom_epsilon = geom_epsilon
        
        # Placements store: placement_id -> Placement
        self._placements: Dict[str, Placement] = {}

        # Downward edges: upper_id -> List[SupportEdge] (who supports upper_id)
        self._upper_to_lower: Dict[str, List[SupportEdge]] = {}

        # Upward edges: lower_id -> List[SupportEdge] (who rests on top of lower_id)
        self._lower_to_upper: Dict[str, List[SupportEdge]] = {}

    @property
    def placements(self) -> Dict[str, Placement]:
        return dict(self._placements)

    def get_support_edges(self, upper_id: str) -> List[SupportEdge]:
        """Returns all edges pointing downwards from upper_id to its supporting bases."""
        return list(self._upper_to_lower.get(upper_id, []))

    def get_supported_edges(self, lower_id: str) -> List[SupportEdge]:
        """Returns all edges pointing upwards from lower_id to items resting on it."""
        return list(self._lower_to_upper.get(lower_id, []))

    def get_total_support_area(self, upper_id: str) -> float:
        """Returns total contact area supporting upper_id."""
        return sum(e.contact_area for e in self.get_support_edges(upper_id))

    def get_total_support_ratio(self, upper_id: str) -> float:
        """Returns total support ratio (total supporting contact area / upper base area)."""
        return min(1.0, sum(e.support_ratio for e in self.get_support_edges(upper_id)))

    def is_on_floor(self, placement_id: str) -> bool:
        """Returns True if placement_id has direct support from container floor."""
        for edge in self.get_support_edges(placement_id):
            if edge.lower_id == NODE_FLOOR:
                return True
        return False

    def add_placement(
        self,
        placement: Placement,
        existing_placements: Optional[List[Placement]] = None,
    ) -> List[SupportEdge]:
        """
        Adds a placement into the SupportGraph, computes supporting and supported edges.
        Returns the downward support edges created for this placement.
        """
        pid = placement.placement_id
        self._placements[pid] = placement
        self._upper_to_lower[pid] = []
        self._lower_to_upper.setdefault(pid, [])

        other_items = existing_placements if existing_placements is not None else [
            p for p in self._placements.values() if p.placement_id != pid
        ]

        eps = self.geom_epsilon
        p_aabb = AABB.from_placement(placement)
        p_base_area = placement.orientation.dx * placement.orientation.dy
        created_downward_edges: List[SupportEdge] = []

        # 1. Check Floor Support (z = 0)
        if abs(p_aabb.min_z) <= eps:
            c_box = AABB(p_aabb.min_x, p_aabb.min_y, 0.0, p_aabb.max_x, p_aabb.max_y, 0.0)
            floor_edge = SupportEdge(
                upper_id=pid,
                lower_id=NODE_FLOOR,
                contact_area=p_base_area,
                support_ratio=1.0,
                load_ratio=0.0,
                overlap_box=c_box,
            )
            self._upper_to_lower[pid].append(floor_edge)
            self._lower_to_upper.setdefault(NODE_FLOOR, []).append(floor_edge)
            created_downward_edges.append(floor_edge)

        # 2. Check Support from/to other items
        for other in other_items:
            oid = other.placement_id
            if oid == pid:
                continue
            o_aabb = AABB.from_placement(other)
            o_base_area = other.orientation.dx * other.orientation.dy

            ox = max(0.0, min(p_aabb.max_x, o_aabb.max_x) - max(p_aabb.min_x, o_aabb.min_x))
            oy = max(0.0, min(p_aabb.max_y, o_aabb.max_y) - max(p_aabb.min_y, o_aabb.min_y))

            if ox > eps and oy > eps:
                contact_area = ox * oy

                # Case A: other supports placement (placement bottom == other top)
                if abs(p_aabb.min_z - o_aabb.max_z) <= eps:
                    c_box = AABB(
                        max(p_aabb.min_x, o_aabb.min_x),
                        max(p_aabb.min_y, o_aabb.min_y),
                        p_aabb.min_z,
                        min(p_aabb.max_x, o_aabb.max_x),
                        min(p_aabb.max_y, o_aabb.max_y),
                        p_aabb.min_z,
                    )
                    edge = SupportEdge(
                        upper_id=pid,
                        lower_id=oid,
                        contact_area=contact_area,
                        support_ratio=contact_area / p_base_area if p_base_area > 0 else 0.0,
                        load_ratio=contact_area / o_base_area if o_base_area > 0 else 0.0,
                        overlap_box=c_box,
                    )
                    self._upper_to_lower[pid].append(edge)
                    self._lower_to_upper.setdefault(oid, []).append(edge)
                    created_downward_edges.append(edge)

                # Case B: placement supports other (placement top == other bottom)
                elif abs(p_aabb.max_z - o_aabb.min_z) <= eps:
                    c_box = AABB(
                        max(p_aabb.min_x, o_aabb.min_x),
                        max(p_aabb.min_y, o_aabb.min_y),
                        p_aabb.max_z,
                        min(p_aabb.max_x, o_aabb.max_x),
                        min(p_aabb.max_y, o_aabb.max_y),
                        p_aabb.max_z,
                    )
                    edge = SupportEdge(
                        upper_id=oid,
                        lower_id=pid,
                        contact_area=contact_area,
                        support_ratio=contact_area / o_base_area if o_base_area > 0 else 0.0,
                        load_ratio=contact_area / p_base_area if p_base_area > 0 else 0.0,
                        overlap_box=c_box,
                    )
                    self._upper_to_lower.setdefault(oid, []).append(edge)
                    self._lower_to_upper[pid].append(edge)

        return created_downward_edges

    def remove_placement(self, placement_id: str):
        """
        Removes a placement and all associated support edges (for rollback).
        """
        if placement_id in self._placements:
            del self._placements[placement_id]

        if placement_id in self._upper_to_lower:
            del self._upper_to_lower[placement_id]

        if placement_id in self._lower_to_upper:
            del self._lower_to_upper[placement_id]

        # Remove from other nodes' support lists
        for uid, edges in list(self._upper_to_lower.items()):
            self._upper_to_lower[uid] = [e for e in edges if e.lower_id != placement_id]

        for lid, edges in list(self._lower_to_upper.items()):
            self._lower_to_upper[lid] = [e for e in edges if e.upper_id != placement_id]

    def is_grounded_to_floor(self, placement_id: str) -> bool:
        """
        Checks if placement_id has a continuous vertical support path down to "FLOOR".
        Uses BFS over downward support edges.
        """
        if placement_id not in self._placements:
            return False

        visited: Set[str] = set()
        queue: deque = deque([placement_id])

        while queue:
            curr = queue.popleft()
            if curr == NODE_FLOOR:
                return True
            if curr in visited:
                continue
            visited.add(curr)

            for edge in self._upper_to_lower.get(curr, []):
                if edge.lower_id not in visited:
                    queue.append(edge.lower_id)

        return False

    def topological_order_top_down(self) -> List[str]:
        """
        Returns placements in topological order from top layers down to bottom layers (Kahn's algorithm).
        In the top-down graph: an item with no items above it has in-degree 0.
        """
        # in_degree: count of items resting on top of item
        in_degree: Dict[str, int] = {pid: len(self._lower_to_upper.get(pid, [])) for pid in self._placements}
        queue = deque([pid for pid, deg in in_degree.items() if deg == 0])
        order: List[str] = []

        while queue:
            curr = queue.popleft()
            order.append(curr)

            # Move downwards to supporting items
            for edge in self._upper_to_lower.get(curr, []):
                lower = edge.lower_id
                if lower != NODE_FLOOR and lower in in_degree:
                    in_degree[lower] -= 1
                    if in_degree[lower] == 0:
                        queue.append(lower)

        # In case of cycles or disconnected components, add remaining
        if len(order) < len(self._placements):
            remaining = [pid for pid in self._placements if pid not in order]
            order.extend(remaining)

        return order

    def clear(self):
        self._placements.clear()
        self._upper_to_lower.clear()
        self._lower_to_upper.clear()
