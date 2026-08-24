"""
Empty Maximal Spaces (EMS) Engine for Solver V2.
Maintains the exact set of maximal non-overlapping/maximal-bounding free spaces in 3D container.
Strictly obeys Clean-Room Solver V2 rules with zero-penetration and robust rollback.
"""
from typing import List, Tuple, Optional, Set
import copy

from backend.solver_v2.domain.models import ContainerSpec, Placement
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON


class EMSManager:
    """
    Manages Empty Maximal Spaces (EMS) in 3D container coordinates.
    """

    def __init__(
        self,
        container: ContainerSpec,
        min_space_dim: float = 0.05,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
    ):
        self.container = container
        self.min_space_dim = min_space_dim
        self.geom_epsilon = geom_epsilon

        # Initial single maximal empty space is the whole container
        self._initial_ems = AABB(
            min_x=0.0,
            min_y=0.0,
            min_z=0.0,
            max_x=container.Lx,
            max_y=container.Ly,
            max_z=container.Lz,
        )
        self._ems_list: List[AABB] = [self._initial_ems]
        self._history: List[List[AABB]] = []

    @property
    def spaces(self) -> List[AABB]:
        """Returns current list of Empty Maximal Spaces."""
        return list(self._ems_list)

    @property
    def count(self) -> int:
        return len(self._ems_list)

    def total_ems_volume(self) -> float:
        """Sum of EMS volumes (note: EMS can overlap each other)."""
        return sum(s.volume for s in self._ems_list)

    def on_placement_committed(self, placement: Placement) -> None:
        """
        Updates EMS set when a placement is committed.
        Saves snapshot to history for atomic rollback.
        """
        # Save snapshot
        self._history.append(list(self._ems_list))

        placement_aabb = AABB.from_placement(placement)
        self._ems_list = self.compute_split_ems(self._ems_list, placement_aabb)

    def rollback(self) -> None:
        """Restores previous EMS state atomically."""
        if not self._history:
            raise IndexError("EMS history stack is empty; cannot rollback.")
        self._ems_list = self._history.pop()

    def reset(self) -> None:
        """Resets EMS state to full empty container."""
        self._ems_list = [self._initial_ems]
        self._history.clear()

    def compute_split_ems(self, current_ems: List[AABB], box: AABB) -> List[AABB]:
        """
        Splits existing EMS list against box AABB and removes subsumed spaces.
        """
        new_candidates: List[AABB] = []

        for ems in current_ems:
            if not ems.intersects(box, eps=self.geom_epsilon):
                # No intersection, keep intact
                new_candidates.append(ems)
                continue

            # Box intersects EMS: generate up to 6 orthogonal child spaces
            # 1. Left of box (x < box.min_x)
            if box.min_x - ems.min_x > self.min_space_dim:
                new_candidates.append(AABB(
                    min_x=ems.min_x,
                    min_y=ems.min_y,
                    min_z=ems.min_z,
                    max_x=box.min_x,
                    max_y=ems.max_y,
                    max_z=ems.max_z,
                ))

            # 2. Right of box (x > box.max_x)
            if ems.max_x - box.max_x > self.min_space_dim:
                new_candidates.append(AABB(
                    min_x=box.max_x,
                    min_y=ems.min_y,
                    min_z=ems.min_z,
                    max_x=ems.max_x,
                    max_y=ems.max_y,
                    max_z=ems.max_z,
                ))

            # 3. Behind box (y < box.min_y)
            if box.min_y - ems.min_y > self.min_space_dim:
                new_candidates.append(AABB(
                    min_x=ems.min_x,
                    min_y=ems.min_y,
                    min_z=ems.min_z,
                    max_x=ems.max_x,
                    max_y=box.min_y,
                    max_z=ems.max_z,
                ))

            # 4. In front of box (y > box.max_y)
            if ems.max_y - box.max_y > self.min_space_dim:
                new_candidates.append(AABB(
                    min_x=ems.min_x,
                    min_y=box.max_y,
                    min_z=ems.min_z,
                    max_x=ems.max_x,
                    max_y=ems.max_y,
                    max_z=ems.max_z,
                ))

            # 5. Below box (z < box.min_z)
            if box.min_z - ems.min_z > self.min_space_dim:
                new_candidates.append(AABB(
                    min_x=ems.min_x,
                    min_y=ems.min_y,
                    min_z=ems.min_z,
                    max_x=ems.max_x,
                    max_y=ems.max_y,
                    max_z=box.min_z,
                ))

            # 6. Above box (z > box.max_z)
            if ems.max_z - box.max_z > self.min_space_dim:
                new_candidates.append(AABB(
                    min_x=ems.min_x,
                    min_y=ems.min_y,
                    min_z=box.max_z,
                    max_x=ems.max_x,
                    max_y=ems.max_y,
                    max_z=ems.max_z,
                ))

        # Eliminate subsumed and duplicate spaces
        return self._eliminate_subsumed(new_candidates)

    def _eliminate_subsumed(self, candidates: List[AABB]) -> List[AABB]:
        """
        Removes any candidate EMS that is completely contained in another candidate EMS.
        """
        if not candidates:
            return []

        # Sort by volume descending so larger spaces are processed first
        sorted_candidates = sorted(candidates, key=lambda b: b.volume, reverse=True)
        survivors: List[AABB] = []

        for candidate in sorted_candidates:
            is_subsumed = False
            for parent in survivors:
                # If parent volume is close or larger and parent contains candidate
                if parent.contains_aabb(candidate, eps=self.geom_epsilon):
                    is_subsumed = True
                    break
            if not is_subsumed:
                survivors.append(candidate)

        return survivors

    def simulate_placement(self, box: AABB) -> List[AABB]:
        """
        Simulates what the EMS list would become if box were placed,
        without mutating the manager state.
        """
        return self.compute_split_ems(self._ems_list, box)
