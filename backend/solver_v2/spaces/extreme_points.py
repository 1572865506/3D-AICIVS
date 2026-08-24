"""
Extreme Points (EP) Manager for Solver V2.
Generates and maintains 3D anchor points for candidate placement generation.
"""
from typing import List, Tuple, Optional, Set, Dict
import math

from backend.solver_v2.domain.models import ContainerSpec, Point3D, Placement
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.spaces.types import ExtremePoint


class ExtremePointsManager:
    """
    Manages 3D Extreme Points (anchor points) in container space.
    """

    def __init__(
        self,
        container: ContainerSpec,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
    ):
        self.container = container
        self.geom_epsilon = geom_epsilon

        # Initial point is the container origin (0, 0, 0)
        self._initial_ep = ExtremePoint(point=Point3D(0.0, 0.0, 0.0), source_placement_id=None, created_step=0)
        self._points: List[ExtremePoint] = [self._initial_ep]
        self._history: List[List[ExtremePoint]] = []

    @property
    def points(self) -> List[ExtremePoint]:
        """Returns current list of extreme points."""
        return list(self._points)

    @property
    def count(self) -> int:
        return len(self._points)

    def on_placement_committed(self, placement: Placement, all_placements: List[Placement], step_index: int) -> None:
        """
        Updates Extreme Points when a new placement is committed.
        Saves snapshot for rollback.
        """
        self._history.append(list(self._points))
        self._points = self.generate_updated_points(self._points, placement, all_placements, step_index)

    def rollback(self) -> None:
        """Restores previous Extreme Points state atomically."""
        if not self._history:
            raise IndexError("ExtremePoints history stack is empty; cannot rollback.")
        self._points = self._history.pop()

    def reset(self) -> None:
        """Resets to initial origin point."""
        self._points = [self._initial_ep]
        self._history.clear()

    def generate_updated_points(
        self,
        current_points: List[ExtremePoint],
        new_placement: Placement,
        all_placements: List[Placement],
        step_index: int,
    ) -> List[ExtremePoint]:
        """
        Generates updated extreme points after committing new_placement.
        1. Filters out existing points that are covered or inside new_placement.
        2. Generates new extreme points projected from new_placement faces and existing items.
        3. Validates against bounds and existing placements.
        4. Deduplicates.
        """
        new_aabb = AABB.from_placement(new_placement)
        all_aabbs = [AABB.from_placement(p) for p in all_placements]

        # 1. Filter out points strictly covered or inside new_placement
        surviving_points: List[ExtremePoint] = []
        for ep in current_points:
            pt = ep.point
            # If point is inside new box (beyond touching surface), remove it
            if (new_aabb.min_x - self.geom_epsilon < pt.x < new_aabb.max_x - self.geom_epsilon and
                new_aabb.min_y - self.geom_epsilon < pt.y < new_aabb.max_y - self.geom_epsilon and
                new_aabb.min_z - self.geom_epsilon < pt.z < new_aabb.max_z - self.geom_epsilon):
                continue
            # If point coincides with min corner of new_placement, it has been used
            if (abs(pt.x - new_aabb.min_x) <= self.geom_epsilon and
                abs(pt.y - new_aabb.min_y) <= self.geom_epsilon and
                abs(pt.z - new_aabb.min_z) <= self.geom_epsilon):
                continue
            surviving_points.append(ep)

        # 2. Generate candidate points from new placement
        raw_candidates: List[Point3D] = []

        # Standard 3 base projection points
        raw_candidates.append(Point3D(new_aabb.max_x, new_aabb.min_y, new_aabb.min_z))
        raw_candidates.append(Point3D(new_aabb.min_x, new_aabb.max_y, new_aabb.min_z))
        raw_candidates.append(Point3D(new_aabb.min_x, new_aabb.min_y, new_aabb.max_z))

        # Additional orthogonal projections against existing item boundaries
        for other_aabb in all_aabbs:
            if other_aabb == new_aabb:
                continue

            # Project along X onto other item's max_x
            if other_aabb.max_x < new_aabb.min_x:
                raw_candidates.append(Point3D(other_aabb.max_x, new_aabb.min_y, new_aabb.min_z))
            # Project along Y onto other item's max_y
            if other_aabb.max_y < new_aabb.min_y:
                raw_candidates.append(Point3D(new_aabb.min_x, other_aabb.max_y, new_aabb.min_z))
            # Project along Z onto other item's max_z
            if other_aabb.max_z < new_aabb.min_z:
                raw_candidates.append(Point3D(new_aabb.min_x, new_aabb.min_y, other_aabb.max_z))

            # New box max face projections intersecting other boundaries
            if new_aabb.max_x <= other_aabb.max_x and other_aabb.min_y <= new_aabb.min_y <= other_aabb.max_y:
                raw_candidates.append(Point3D(new_aabb.max_x, other_aabb.max_y, new_aabb.min_z))
            if new_aabb.max_y <= other_aabb.max_y and other_aabb.min_x <= new_aabb.min_x <= other_aabb.max_x:
                raw_candidates.append(Point3D(other_aabb.max_x, new_aabb.max_y, new_aabb.min_z))

        # 3. Validate candidates against bounds and penetration
        valid_new_eps: List[ExtremePoint] = []
        for cand in raw_candidates:
            # Bounds check
            if cand.x < -self.geom_epsilon or cand.x > self.container.Lx - self.geom_epsilon:
                continue
            if cand.y < -self.geom_epsilon or cand.y > self.container.Ly - self.geom_epsilon:
                continue
            if cand.z < -self.geom_epsilon or cand.z > self.container.Lz - self.geom_epsilon:
                continue

            # Collision check: point must not be strictly inside any committed box
            inside_any = False
            for box in all_aabbs:
                if (box.min_x + self.geom_epsilon < cand.x < box.max_x - self.geom_epsilon and
                    box.min_y + self.geom_epsilon < cand.y < box.max_y - self.geom_epsilon and
                    box.min_z + self.geom_epsilon < cand.z < box.max_z - self.geom_epsilon):
                    inside_any = True
                    break
            if inside_any:
                continue

            valid_new_eps.append(ExtremePoint(
                point=cand,
                source_placement_id=new_placement.placement_id,
                created_step=step_index,
            ))

        # 4. Deduplicate all points within geometric tolerance
        all_candidates = surviving_points + valid_new_eps
        unique_eps: List[ExtremePoint] = []

        for ep in all_candidates:
            is_dup = False
            for existing in unique_eps:
                if (abs(ep.x - existing.x) <= self.geom_epsilon and
                    abs(ep.y - existing.y) <= self.geom_epsilon and
                    abs(ep.z - existing.z) <= self.geom_epsilon):
                    is_dup = True
                    break
            if not is_dup:
                unique_eps.append(ep)

        # Sort canonically by (x, y, z)
        unique_eps.sort(key=lambda p: (round(p.x, 5), round(p.y, 5), round(p.z, 5)))
        return unique_eps
