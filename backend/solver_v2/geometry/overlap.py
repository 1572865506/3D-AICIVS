"""
Independent Overlap and Collision Query Engine for Solver V2.
Acts as an authoritative standalone geometric verification referee.
Zero tolerance: Overlap is a hard invalid condition, never handled by soft penalty.
"""
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any, Optional
import math

from backend.solver_v2.domain.models import ContainerSpec, Placement
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON


@dataclass
class OverlapReport:
    is_valid: bool
    overlap_pair_count: int
    penetration_volume: float
    out_of_bounds_count: int
    overlapping_pairs: List[Tuple[str, str, float]] = field(default_factory=list)
    out_of_bounds_ids: List[str] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "overlap_pair_count": self.overlap_pair_count,
            "penetration_volume": round(self.penetration_volume, 8),
            "out_of_bounds_count": self.out_of_bounds_count,
            "overlapping_pairs": self.overlapping_pairs,
            "out_of_bounds_ids": self.out_of_bounds_ids,
        }


class OverlapDetector:
    """
    Independent Overlap Detector.
    Runs brute-force / exact pairwise O(N^2) or spatial verification sweep
    without relying on search heuristics.
    """

    @staticmethod
    def check_bounds(
        container: ContainerSpec,
        placement: Placement,
        eps: float = DEFAULT_GEOM_EPSILON
    ) -> Tuple[bool, Optional[str]]:
        aabb = AABB.from_placement(placement)
        if not aabb.is_within_bounds(container.Lx, container.Ly, container.Lz, eps=eps):
            return False, (
                f"Placement {placement.placement_id} out of container bounds: "
                f"box=[({aabb.min_x:.4f}, {aabb.min_y:.4f}, {aabb.min_z:.4f}) -> "
                f"({aabb.max_x:.4f}, {aabb.max_y:.4f}, {aabb.max_z:.4f})], "
                f"container=[(0, 0, 0) -> ({container.Lx:.4f}, {container.Ly:.4f}, {container.Lz:.4f})]"
            )
        return True, None

    @staticmethod
    def check_pairwise_collision(
        p1: Placement,
        p2: Placement,
        eps: float = DEFAULT_GEOM_EPSILON
    ) -> Tuple[bool, float]:
        """
        Returns (is_colliding, penetration_volume).
        is_colliding is True ONLY when volumetric penetration > eps.
        """
        aabb1 = AABB.from_placement(p1)
        aabb2 = AABB.from_placement(p2)
        if aabb1.intersects(aabb2, eps=eps):
            vol = aabb1.penetration_volume(aabb2, eps=eps)
            return True, vol
        return False, 0.0

    @classmethod
    def check_against_all(
        cls,
        candidate: Placement,
        existing: List[Placement],
        eps: float = DEFAULT_GEOM_EPSILON
    ) -> Tuple[bool, List[Tuple[str, float]]]:
        """
        Checks candidate against a list of existing placements.
        Returns (has_collision, list_of_colliding_ids_and_penetration_volumes).
        """
        cand_aabb = AABB.from_placement(candidate)
        collisions: List[Tuple[str, float]] = []

        for p in existing:
            if p.placement_id == candidate.placement_id:
                continue
            other_aabb = AABB.from_placement(p)
            if cand_aabb.intersects(other_aabb, eps=eps):
                vol = cand_aabb.penetration_volume(other_aabb, eps=eps)
                collisions.append((p.placement_id, vol))

        return len(collisions) > 0, collisions

    @classmethod
    def run_independent_sweep(
        cls,
        container: ContainerSpec,
        placements: List[Placement],
        eps: float = DEFAULT_GEOM_EPSILON
    ) -> OverlapReport:
        """
        Executes a rigorous independent pairwise and boundary sweep on all placements.
        """
        out_of_bounds_ids: List[str] = []
        overlapping_pairs: List[Tuple[str, str, float]] = []
        total_penetration_volume = 0.0

        n = len(placements)
        aabbs = [AABB.from_placement(p) for p in placements]

        # 1. Bounds check
        for i in range(n):
            if not aabbs[i].is_within_bounds(container.Lx, container.Ly, container.Lz, eps=eps):
                out_of_bounds_ids.append(placements[i].placement_id)

        # 2. Pairwise collision check
        for i in range(n):
            for j in range(i + 1, n):
                if aabbs[i].intersects(aabbs[j], eps=eps):
                    vol = aabbs[i].penetration_volume(aabbs[j], eps=eps)
                    overlapping_pairs.append((placements[i].placement_id, placements[j].placement_id, vol))
                    total_penetration_volume += vol

        is_valid = (len(out_of_bounds_ids) == 0) and (len(overlapping_pairs) == 0)

        return OverlapReport(
            is_valid=is_valid,
            overlap_pair_count=len(overlapping_pairs),
            penetration_volume=total_penetration_volume,
            out_of_bounds_count=len(out_of_bounds_ids),
            overlapping_pairs=overlapping_pairs,
            out_of_bounds_ids=out_of_bounds_ids,
        )
