"""
3D Spatial Index for Fast Geometric Intersection & Collision Queries.
Uses a 3D Uniform Spatial Grid Hash for deterministic O(1) average-time lookups.
"""
from dataclasses import dataclass
from typing import Dict, Set, List, Tuple, Any, Optional
import math

from backend.solver_v2.domain.models import Point3D
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON


@dataclass
class SpatialItem:
    item_id: str
    aabb: AABB
    data: Any


class SpatialIndex:
    """
    3D Spatial Hash Grid Index.
    Enables rapid spatial bounding queries and deterministic item management.
    """

    def __init__(self, cell_size: float = 0.5):
        if cell_size <= 0:
            raise ValueError(f"Cell size must be strictly positive: {cell_size}")
        self.cell_size: float = cell_size
        self._grid: Dict[Tuple[int, int, int], Set[str]] = {}
        self._items: Dict[str, SpatialItem] = {}

    def _get_cell_coords(self, x: float, y: float, z: float) -> Tuple[int, int, int]:
        return (
            int(math.floor(x / self.cell_size)),
            int(math.floor(y / self.cell_size)),
            int(math.floor(z / self.cell_size)),
        )

    def _get_cells_for_box(
        self,
        min_x: float,
        min_y: float,
        min_z: float,
        max_x: float,
        max_y: float,
        max_z: float,
    ) -> List[Tuple[int, int, int]]:
        min_cx, min_cy, min_cz = self._get_cell_coords(min_x, min_y, min_z)
        max_cx, max_cy, max_cz = self._get_cell_coords(max_x, max_y, max_z)

        cells = []
        for cx in range(min(min_cx, max_cx), max(min_cx, max_cx) + 1):
            for cy in range(min(min_cy, max_cy), max(min_cy, max_cy) + 1):
                for cz in range(min(min_cz, max_cz), max(min_cz, max_cz) + 1):
                    cells.append((cx, cy, cz))
        return cells

    def _get_cells_for_aabb_interior(self, aabb: AABB, eps: float = DEFAULT_GEOM_EPSILON) -> List[Tuple[int, int, int]]:
        return self._get_cells_for_box(
            aabb.min_x + eps,
            aabb.min_y + eps,
            aabb.min_z + eps,
            aabb.max_x - eps,
            aabb.max_y - eps,
            aabb.max_z - eps,
        )

    def insert(self, item_id: str, aabb: AABB, data: Any = None) -> None:
        """Inserts an AABB into the spatial index."""
        if item_id in self._items:
            self.remove(item_id)

        item = SpatialItem(item_id=item_id, aabb=aabb, data=data)
        self._items[item_id] = item

        cells = self._get_cells_for_aabb_interior(aabb)
        for cell in cells:
            if cell not in self._grid:
                self._grid[cell] = set()
            self._grid[cell].add(item_id)

    def remove(self, item_id: str) -> Optional[SpatialItem]:
        """Removes an item by its ID."""
        if item_id not in self._items:
            return None

        item = self._items.pop(item_id)
        cells = self._get_cells_for_aabb_interior(item.aabb)
        for cell in cells:
            if cell in self._grid:
                self._grid[cell].discard(item_id)
                if not self._grid[cell]:
                    del self._grid[cell]
        return item

    def get_item(self, item_id: str) -> Optional[SpatialItem]:
        return self._items.get(item_id)

    def contains(self, item_id: str) -> bool:
        return item_id in self._items

    def all_items(self) -> List[SpatialItem]:
        return list(self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        self._grid.clear()
        self._items.clear()

    def query_candidate_ids(self, aabb: AABB, expand_eps: float = 0.0) -> Set[str]:
        """Returns all item IDs whose grid cells overlap with query aabb."""
        candidate_ids: Set[str] = set()
        cells = self._get_cells_for_box(
            aabb.min_x - expand_eps,
            aabb.min_y - expand_eps,
            aabb.min_z - expand_eps,
            aabb.max_x + expand_eps,
            aabb.max_y + expand_eps,
            aabb.max_z + expand_eps,
        )
        for cell in cells:
            if cell in self._grid:
                candidate_ids.update(self._grid[cell])
        return candidate_ids

    def query_intersect(self, aabb: AABB, eps: float = DEFAULT_GEOM_EPSILON) -> List[SpatialItem]:
        """
        Queries all items strictly penetrating query aabb (volumetric penetration > eps).
        Face/edge/point touching is filtered out.
        """
        candidate_ids = self.query_candidate_ids(aabb, expand_eps=0.0)
        colliding_items = []
        for cid in sorted(candidate_ids):  # Deterministic order
            item = self._items[cid]
            if aabb.intersects(item.aabb, eps=eps):
                colliding_items.append(item)
        return colliding_items

    def query_touching(self, aabb: AABB, eps: float = DEFAULT_GEOM_EPSILON) -> List[Tuple[SpatialItem, Any]]:
        """
        Queries all items touching or contacting query aabb (face, edge, point, penetration).
        Returns list of (SpatialItem, ContactType).
        """
        # Expand query by eps to capture adjacent boundary cells
        candidate_ids = self.query_candidate_ids(aabb, expand_eps=eps)
        contacts = []
        for cid in sorted(candidate_ids):
            item = self._items[cid]
            ctype, cval = aabb.classify_contact(item.aabb, eps=eps)
            if ctype.value != "NONE":
                contacts.append((item, ctype))
        return contacts

    def query_point(self, pt: Point3D, eps: float = DEFAULT_GEOM_EPSILON) -> List[SpatialItem]:
        """Queries all items containing the given 3D point."""
        cell = self._get_cell_coords(pt.x, pt.y, pt.z)
        results = []
        if cell in self._grid:
            for cid in sorted(self._grid[cell]):
                item = self._items[cid]
                if item.aabb.contains_point(pt, eps=eps):
                    results.append(item)
        return results
