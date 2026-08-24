"""
ContactGraph Engine for Solver V2 (Agent 07).
Builds and maintains the 3D contact network between placed cargo and container boundaries.

Contact types & directions:
- BOTTOM (-Z): support from floor or lower items
- TOP (+Z): load from upper items
- LEFT (-Y): lateral contact with left container wall or left neighbor
- RIGHT (+Y): lateral contact with right container wall or right neighbor
- BACK (-X): contact with inner container wall or rear neighbor
- FRONT (+X): contact with front neighbor (towards doors)
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Tuple, Optional, Set, Any
import math

from backend.solver_v2.domain.models import Placement, Point3D, BoxDim, ContainerSpec
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON


class ContactDirection(str, Enum):
    BOTTOM = "BOTTOM"  # -Z (supporting surface)
    TOP = "TOP"        # +Z (top face)
    LEFT = "LEFT"      # -Y (lateral min_y)
    RIGHT = "RIGHT"    # +Y (lateral max_y)
    BACK = "BACK"      # -X (rear min_x, towards inner wall)
    FRONT = "FRONT"    # +X (front max_x, towards doors)


# Boundary virtual node IDs
NODE_FLOOR = "FLOOR"
NODE_ROOF = "ROOF"
NODE_WALL_BACK = "WALL_BACK_X0"
NODE_WALL_FRONT = "WALL_FRONT_XMAX"
NODE_WALL_LEFT = "WALL_LEFT_Y0"
NODE_WALL_RIGHT = "WALL_RIGHT_YMAX"


@dataclass(frozen=True)
class ContactEdge:
    """
    Represents a physical contact interface between two nodes (placements or boundaries).
    """
    node_a: str                  # Target item ID
    node_b: str                  # Neighbor item ID or boundary node ID
    direction: ContactDirection  # Direction from node_a to node_b
    contact_area: float          # Contact surface area in m^2
    contact_box: AABB            # 3D bounding box of the contact interface
    is_boundary: bool = False    # True if node_b is a container boundary wall/floor
    is_lateral: bool = False     # True for LEFT, RIGHT, BACK, FRONT contacts


class ContactGraph:
    """
    3D Spatial Contact Graph.
    Tracks all physical contacts among committed cargo items and container boundary walls.
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
        
        # Adjacency list: node_id -> List[ContactEdge] (outgoing contacts from node_id)
        self._adj: Dict[str, List[ContactEdge]] = {}

    @property
    def placements(self) -> Dict[str, Placement]:
        return dict(self._placements)

    def get_contacts(self, placement_id: str) -> List[ContactEdge]:
        """Returns all contact edges associated with placement_id."""
        return list(self._adj.get(placement_id, []))

    def get_contacts_in_direction(
        self, placement_id: str, direction: ContactDirection
    ) -> List[ContactEdge]:
        """Returns contacts in a specific direction from placement_id."""
        return [
            edge for edge in self._adj.get(placement_id, [])
            if edge.direction == direction
        ]

    def get_lateral_contacts(self, placement_id: str) -> List[ContactEdge]:
        """Returns all lateral contact edges (LEFT, RIGHT, BACK, FRONT)."""
        return [
            edge for edge in self._adj.get(placement_id, [])
            if edge.is_lateral
        ]

    def has_boundary_bracing(self, placement_id: str, direction: ContactDirection) -> bool:
        """Returns True if the placement is in direct contact with a container boundary in direction."""
        for edge in self.get_contacts_in_direction(placement_id, direction):
            if edge.is_boundary:
                return True
        return False

    def add_placement(
        self,
        placement: Placement,
        existing_placements: Optional[List[Placement]] = None,
    ) -> List[ContactEdge]:
        """
        Adds a new placement into ContactGraph and computes all contact edges.
        Returns the newly created contact edges for this placement.
        """
        pid = placement.placement_id
        self._placements[pid] = placement
        if pid not in self._adj:
            self._adj[pid] = []

        other_items = existing_placements if existing_placements is not None else [
            p for p in self._placements.values() if p.placement_id != pid
        ]

        new_edges: List[ContactEdge] = []
        eps = self.geom_epsilon

        p_aabb = AABB.from_placement(placement)
        c_lx, c_ly, c_lz = self.container.Lx, self.container.Ly, self.container.Lz

        # 1. Check Container Boundaries
        # Floor (BOTTOM: z = 0)
        if abs(p_aabb.min_z) <= eps:
            area = placement.orientation.dx * placement.orientation.dy
            box = AABB(p_aabb.min_x, p_aabb.min_y, 0.0, p_aabb.max_x, p_aabb.max_y, 0.0)
            edge = ContactEdge(
                node_a=pid,
                node_b=NODE_FLOOR,
                direction=ContactDirection.BOTTOM,
                contact_area=area,
                contact_box=box,
                is_boundary=True,
                is_lateral=False,
            )
            self._adj[pid].append(edge)
            new_edges.append(edge)

        # Inner Rear Wall (BACK: x = 0)
        if abs(p_aabb.min_x) <= eps:
            area = placement.orientation.dy * placement.orientation.dz
            box = AABB(0.0, p_aabb.min_y, p_aabb.min_z, 0.0, p_aabb.max_y, p_aabb.max_z)
            edge = ContactEdge(
                node_a=pid,
                node_b=NODE_WALL_BACK,
                direction=ContactDirection.BACK,
                contact_area=area,
                contact_box=box,
                is_boundary=True,
                is_lateral=True,
            )
            self._adj[pid].append(edge)
            new_edges.append(edge)

        # Left Container Wall (LEFT: y = 0)
        if abs(p_aabb.min_y) <= eps:
            area = placement.orientation.dx * placement.orientation.dz
            box = AABB(p_aabb.min_x, 0.0, p_aabb.min_z, p_aabb.max_x, 0.0, p_aabb.max_z)
            edge = ContactEdge(
                node_a=pid,
                node_b=NODE_WALL_LEFT,
                direction=ContactDirection.LEFT,
                contact_area=area,
                contact_box=box,
                is_boundary=True,
                is_lateral=True,
            )
            self._adj[pid].append(edge)
            new_edges.append(edge)

        # Right Container Wall (RIGHT: y = Ly)
        if abs(p_aabb.max_y - c_ly) <= eps:
            area = placement.orientation.dx * placement.orientation.dz
            box = AABB(p_aabb.min_x, c_ly, p_aabb.min_z, p_aabb.max_x, c_ly, p_aabb.max_z)
            edge = ContactEdge(
                node_a=pid,
                node_b=NODE_WALL_RIGHT,
                direction=ContactDirection.RIGHT,
                contact_area=area,
                contact_box=box,
                is_boundary=True,
                is_lateral=True,
            )
            self._adj[pid].append(edge)
            new_edges.append(edge)

        # Roof (TOP: z = Lz)
        if abs(p_aabb.max_z - c_lz) <= eps:
            area = placement.orientation.dx * placement.orientation.dy
            box = AABB(p_aabb.min_x, p_aabb.min_y, c_lz, p_aabb.max_x, p_aabb.max_y, c_lz)
            edge = ContactEdge(
                node_a=pid,
                node_b=NODE_ROOF,
                direction=ContactDirection.TOP,
                contact_area=area,
                contact_box=box,
                is_boundary=True,
                is_lateral=False,
            )
            self._adj[pid].append(edge)
            new_edges.append(edge)

        # 2. Check contacts with all other placed items
        for other in other_items:
            oid = other.placement_id
            if oid == pid:
                continue
            o_aabb = AABB.from_placement(other)

            self._compute_pairwise_contacts(pid, p_aabb, oid, o_aabb, new_edges)

        return new_edges

    def _compute_pairwise_contacts(
        self,
        id_a: str,
        box_a: AABB,
        id_b: str,
        box_b: AABB,
        out_edges: List[ContactEdge],
    ):
        """Checks and establishes contact edges between two items in all 6 directions."""
        eps = self.geom_epsilon

        # Overlaps on X, Y, Z projection intervals
        ox = max(0.0, min(box_a.max_x, box_b.max_x) - max(box_a.min_x, box_b.min_x))
        oy = max(0.0, min(box_a.max_y, box_b.max_y) - max(box_a.min_y, box_b.min_y))
        oz = max(0.0, min(box_a.max_z, box_b.max_z) - max(box_a.min_z, box_b.min_z))

        # Vertical Contacts (Z-axis)
        if ox > eps and oy > eps:
            # box_a bottom touches box_b top
            if abs(box_a.min_z - box_b.max_z) <= eps:
                c_box = AABB(
                    max(box_a.min_x, box_b.min_x),
                    max(box_a.min_y, box_b.min_y),
                    box_a.min_z,
                    min(box_a.max_x, box_b.max_x),
                    min(box_a.max_y, box_b.max_y),
                    box_a.min_z,
                )
                e_ab = ContactEdge(id_a, id_b, ContactDirection.BOTTOM, ox * oy, c_box, is_lateral=False)
                e_ba = ContactEdge(id_b, id_a, ContactDirection.TOP, ox * oy, c_box, is_lateral=False)
                self._adj[id_a].append(e_ab)
                self._adj.setdefault(id_b, []).append(e_ba)
                out_edges.extend([e_ab, e_ba])

            # box_a top touches box_b bottom
            elif abs(box_a.max_z - box_b.min_z) <= eps:
                c_box = AABB(
                    max(box_a.min_x, box_b.min_x),
                    max(box_a.min_y, box_b.min_y),
                    box_a.max_z,
                    min(box_a.max_x, box_b.max_x),
                    min(box_a.max_y, box_b.max_y),
                    box_a.max_z,
                )
                e_ab = ContactEdge(id_a, id_b, ContactDirection.TOP, ox * oy, c_box, is_lateral=False)
                e_ba = ContactEdge(id_b, id_a, ContactDirection.BOTTOM, ox * oy, c_box, is_lateral=False)
                self._adj[id_a].append(e_ab)
                self._adj.setdefault(id_b, []).append(e_ba)
                out_edges.extend([e_ab, e_ba])

        # Lateral Contacts: Y-axis (LEFT / RIGHT)
        if ox > eps and oz > eps:
            # box_a left (min_y) touches box_b right (max_y)
            if abs(box_a.min_y - box_b.max_y) <= eps:
                c_box = AABB(
                    max(box_a.min_x, box_b.min_x),
                    box_a.min_y,
                    max(box_a.min_z, box_b.min_z),
                    min(box_a.max_x, box_b.max_x),
                    box_a.min_y,
                    min(box_a.max_z, box_b.max_z),
                )
                e_ab = ContactEdge(id_a, id_b, ContactDirection.LEFT, ox * oz, c_box, is_lateral=True)
                e_ba = ContactEdge(id_b, id_a, ContactDirection.RIGHT, ox * oz, c_box, is_lateral=True)
                self._adj[id_a].append(e_ab)
                self._adj.setdefault(id_b, []).append(e_ba)
                out_edges.extend([e_ab, e_ba])

            # box_a right (max_y) touches box_b left (min_y)
            elif abs(box_a.max_y - box_b.min_y) <= eps:
                c_box = AABB(
                    max(box_a.min_x, box_b.min_x),
                    box_a.max_y,
                    max(box_a.min_z, box_b.min_z),
                    min(box_a.max_x, box_b.max_x),
                    box_a.max_y,
                    min(box_a.max_z, box_b.max_z),
                )
                e_ab = ContactEdge(id_a, id_b, ContactDirection.RIGHT, ox * oz, c_box, is_lateral=True)
                e_ba = ContactEdge(id_b, id_a, ContactDirection.LEFT, ox * oz, c_box, is_lateral=True)
                self._adj[id_a].append(e_ab)
                self._adj.setdefault(id_b, []).append(e_ba)
                out_edges.extend([e_ab, e_ba])

        # Longitudinal Contacts: X-axis (BACK / FRONT)
        if oy > eps and oz > eps:
            # box_a back (min_x) touches box_b front (max_x)
            if abs(box_a.min_x - box_b.max_x) <= eps:
                c_box = AABB(
                    box_a.min_x,
                    max(box_a.min_y, box_b.min_y),
                    max(box_a.min_z, box_b.min_z),
                    box_a.min_x,
                    min(box_a.max_y, box_b.max_y),
                    min(box_a.max_z, box_b.max_z),
                )
                e_ab = ContactEdge(id_a, id_b, ContactDirection.BACK, oy * oz, c_box, is_lateral=True)
                e_ba = ContactEdge(id_b, id_a, ContactDirection.FRONT, oy * oz, c_box, is_lateral=True)
                self._adj[id_a].append(e_ab)
                self._adj.setdefault(id_b, []).append(e_ba)
                out_edges.extend([e_ab, e_ba])

            # box_a front (max_x) touches box_b back (min_x)
            elif abs(box_a.max_x - box_b.min_x) <= eps:
                c_box = AABB(
                    box_a.max_x,
                    max(box_a.min_y, box_b.min_y),
                    max(box_a.min_z, box_b.min_z),
                    box_a.max_x,
                    min(box_a.max_y, box_b.max_y),
                    min(box_a.max_z, box_b.max_z),
                )
                e_ab = ContactEdge(id_a, id_b, ContactDirection.FRONT, oy * oz, c_box, is_lateral=True)
                e_ba = ContactEdge(id_b, id_a, ContactDirection.BACK, oy * oz, c_box, is_lateral=True)
                self._adj[id_a].append(e_ab)
                self._adj.setdefault(id_b, []).append(e_ba)
                out_edges.extend([e_ab, e_ba])

    def remove_placement(self, placement_id: str):
        """
        Removes a placement and all associated contact edges from the ContactGraph (for rollback).
        """
        if placement_id in self._placements:
            del self._placements[placement_id]

        if placement_id in self._adj:
            del self._adj[placement_id]

        # Clean references from other nodes
        for node_id, edges in list(self._adj.items()):
            self._adj[node_id] = [e for e in edges if e.node_b != placement_id]

    def clear(self):
        """Clears all placements and contacts."""
        self._placements.clear()
        self._adj.clear()
