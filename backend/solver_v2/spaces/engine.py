"""
Free Space Engine for Solver V2.
Orchestrates:
- Empty Maximal Spaces (EMS) management
- Extreme Points (EP) generation
- Reachability classification
- Cavity detection
- Dead space identification
- Fragmentation scoring
- Candidate residual space quality evaluation
"""
from typing import List, Tuple, Optional, Dict, Any

from backend.solver_v2.domain.models import (
    ContainerSpec,
    CargoSKU,
    Placement,
    Point3D,
    Orientation3D,
)
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.spaces.types import (
    SpaceClass,
    ExtremePoint,
    FreeSpaceBox,
    ResidualSpaceMetrics,
    AnchorCategory,
    ClassifiedAnchor,
)
from backend.solver_v2.spaces.ems import EMSManager
from backend.solver_v2.spaces.extreme_points import ExtremePointsManager
from backend.solver_v2.spaces.reachability import ReachabilityAnalyzer


class FreeSpaceEngine:
    """
    Unified Free Space Engine for Solver V2.
    """

    def __init__(
        self,
        container: ContainerSpec,
        grid_resolution: float = 0.1,
        min_space_dim: float = 0.05,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
    ):
        self.container = container
        self.geom_epsilon = geom_epsilon

        self.ems_manager = EMSManager(
            container=container,
            min_space_dim=min_space_dim,
            geom_epsilon=geom_epsilon,
        )
        self.ep_manager = ExtremePointsManager(
            container=container,
            geom_epsilon=geom_epsilon,
        )
        self.reachability_analyzer = ReachabilityAnalyzer(
            container=container,
            grid_resolution=grid_resolution,
            geom_epsilon=geom_epsilon,
        )

        self._current_placements: List[Placement] = []
        self._step_index: int = 0

    @property
    def ems_spaces(self) -> List[AABB]:
        """Returns current list of Empty Maximal Spaces."""
        return self.ems_manager.spaces

    @property
    def extreme_points(self) -> List[ExtremePoint]:
        """Returns current list of 3D Extreme Points (candidate anchor positions)."""
        return self.ep_manager.points

    def on_placement_committed(
        self,
        placement: Placement,
        remaining_skus: Optional[List[CargoSKU]] = None,
    ) -> ResidualSpaceMetrics:
        """
        Updates internal EMS and EP state when a placement is committed to WorldState.
        Returns the updated ResidualSpaceMetrics.
        """
        self._current_placements.append(placement)
        self._step_index += 1

        # Update EMS
        self.ems_manager.on_placement_committed(placement)

        # Update Extreme Points
        self.ep_manager.on_placement_committed(placement, self._current_placements, self._step_index)

        # Compute current residual metrics
        metrics, _ = self.reachability_analyzer.analyze(
            placements=self._current_placements,
            remaining_skus=remaining_skus,
            ems_list=self.ems_manager.spaces,
        )
        return metrics

    def on_placement_replayed(self, placement: Placement) -> None:
        """Replay an already validated placement without redundant analysis.

        EMS and extreme-point state are updated identically to a normal commit.
        Reachability metrics are intentionally omitted because reconstruction
        callers do not consume them; hard validation remains in WorldState and
        the candidate/final validators.
        """
        self._current_placements.append(placement)
        self._step_index += 1
        self.ems_manager.on_placement_committed(placement)
        self.ep_manager.on_placement_committed(
            placement, self._current_placements, self._step_index,
        )

    def rebuild_frontier_view(self, placements: List[Placement]) -> None:
        """Build the read-only anchor view used by global wall expansion.

        `get_classified_anchors` derives floor/wall/top anchors directly from
        this exact placement geometry. Replaying every historical EMS split and
        every transient extreme point is unnecessary for frontier-aligned wall
        templates and was the dominant BLK-006C reconstruction cost.
        """
        self._current_placements = list(placements)
        self._step_index = len(placements)

    def rollback(self) -> None:
        """
        Atomically rolls back the last committed placement from EMS and ExtremePoints managers.
        """
        if not self._current_placements:
            raise IndexError("Cannot rollback FreeSpaceEngine: no committed placements.")
        self._current_placements.pop()
        self._step_index = max(0, self._step_index - 1)

        self.ems_manager.rollback()
        self.ep_manager.rollback()

    def reset(self) -> None:
        """Resets engine to empty container state."""
        self._current_placements.clear()
        self._step_index = 0
        self.ems_manager.reset()
        self.ep_manager.reset()

    def evaluate_candidate_residual(
        self,
        candidate_placement: Placement,
        remaining_skus: Optional[List[CargoSKU]] = None,
    ) -> ResidualSpaceMetrics:
        """
        Evaluates the residual space quality IF candidate_placement were placed,
        without permanently modifying the engine state.
        """
        # 1. Simulate placements list
        simulated_placements = self._current_placements + [candidate_placement]

        # 2. Simulate EMS split
        cand_aabb = AABB.from_placement(candidate_placement)
        simulated_ems = self.ems_manager.simulate_placement(cand_aabb)

        # 3. Analyze reachability, cavities, dead space, slivers, and fragmentation
        metrics, _ = self.reachability_analyzer.analyze(
            placements=simulated_placements,
            remaining_skus=remaining_skus,
            ems_list=simulated_ems,
        )

        return metrics

    def get_classified_anchors(
        self,
        world_state: Optional[Any] = None,
    ) -> Dict[AnchorCategory, List[ClassifiedAnchor]]:
        """
        Classifies all active anchors into distinct geometric categories:
        - FLOOR_FRONTIER: z ≈ 0 advancing from rear to door
        - SUPPORTED_FRONTIER: z > 0 with verified supporting box top below
        - WALL_FRONTIER: on the active advancing packing front (max_x)
        - TOP_SURFACE: top face corners of placed boxes
        - EMS_CORNER: Empty Maximal Space corners
        - EXTREME_POINT: standard geometric extreme points
        - GAP_FILL: confined / residual anchors
        """
        eps = self.geom_epsilon
        result: Dict[AnchorCategory, List[ClassifiedAnchor]] = {cat: [] for cat in AnchorCategory}

        # 1. Determine active packing front (max committed X)
        committed = self._current_placements
        max_committed_x = max([p.position.x + p.orientation.dx for p in committed], default=0.0)

        # 2. Gather raw candidate points
        raw_ep_points: List[Point3D] = [ep.point for ep in self.ep_manager.points]
        raw_ems_points: List[Point3D] = [Point3D(ems.min_x, ems.min_y, ems.min_z) for ems in self.ems_manager.spaces]

        # Top surface corners from committed placements
        raw_top_points: List[Point3D] = []
        for p in committed:
            px, py, pz = p.position.x, p.position.y, p.position.z
            pdx, pdy, pdz = p.orientation.dx, p.orientation.dy, p.orientation.dz
            raw_top_points.append(Point3D(px, py, pz + pdz))
            raw_top_points.append(Point3D(px + pdx, py, pz + pdz))
            raw_top_points.append(Point3D(px, py + pdy, pz + pdz))

        # Deduplicate all raw points
        all_unique_points: List[Point3D] = []
        for pt in raw_ep_points + raw_ems_points + raw_top_points:
            if pt.x < -eps or pt.x > self.container.Lx - eps or pt.y < -eps or pt.y > self.container.Ly - eps or pt.z < -eps or pt.z > self.container.Lz - eps:
                continue
            if not any(
                abs(pt.x - u.x) <= eps and
                abs(pt.y - u.y) <= eps and
                abs(pt.z - u.z) <= eps
                for u in all_unique_points
            ):
                all_unique_points.append(pt)

        if not all_unique_points and not committed:
            all_unique_points = [Point3D(0.0, 0.0, 0.0)]

        # 3. Classify each point
        for pt in all_unique_points:
            is_floor = (pt.z <= eps)
            is_on_wall_front = (abs(pt.x - max_committed_x) <= 0.05 or pt.x >= max_committed_x - eps) and len(committed) > 0

            # Check if point is supported by any placed box
            has_support = is_floor
            support_z = 0.0
            if not is_floor:
                for p in committed:
                    p_top_z = p.position.z + p.orientation.dz
                    if abs(p_top_z - pt.z) <= eps:
                        p_min_x, p_max_x = p.position.x, p.position.x + p.orientation.dx
                        p_min_y, p_max_y = p.position.y, p.position.y + p.orientation.dy
                        if (p_min_x - eps <= pt.x <= p_max_x + eps) and (p_min_y - eps <= pt.y <= p_max_y + eps):
                            has_support = True
                            support_z = p_top_z
                            break

            # Assign to primary categories
            if is_floor:
                result[AnchorCategory.FLOOR_FRONTIER].append(
                    ClassifiedAnchor(point=pt, category=AnchorCategory.FLOOR_FRONTIER, support_z=0.0, priority_score=pt.x * 10.0 + pt.y)
                )
            elif has_support:
                result[AnchorCategory.SUPPORTED_FRONTIER].append(
                    ClassifiedAnchor(point=pt, category=AnchorCategory.SUPPORTED_FRONTIER, support_z=support_z, priority_score=pt.x * 10.0 + pt.z)
                )

            if is_on_wall_front and (is_floor or has_support):
                result[AnchorCategory.WALL_FRONTIER].append(
                    ClassifiedAnchor(point=pt, category=AnchorCategory.WALL_FRONTIER, support_z=support_z, priority_score=pt.y * 10.0 + pt.z)
                )

            if any(abs(pt.x - ep.x) <= eps and abs(pt.y - ep.y) <= eps and abs(pt.z - ep.z) <= eps for ep in self.ep_manager.points):
                result[AnchorCategory.EXTREME_POINT].append(
                    ClassifiedAnchor(point=pt, category=AnchorCategory.EXTREME_POINT, support_z=support_z)
                )

            if any(abs(pt.x - ems.min_x) <= eps and abs(pt.y - ems.min_y) <= eps and abs(pt.z - ems.min_z) <= eps for ems in self.ems_manager.spaces):
                result[AnchorCategory.EMS_CORNER].append(
                    ClassifiedAnchor(point=pt, category=AnchorCategory.EMS_CORNER, support_z=support_z)
                )

            if not is_floor and has_support:
                result[AnchorCategory.TOP_SURFACE].append(
                    ClassifiedAnchor(point=pt, category=AnchorCategory.TOP_SURFACE, support_z=support_z)
                )

            result[AnchorCategory.EXPLORATION].append(
                ClassifiedAnchor(point=pt, category=AnchorCategory.EXPLORATION, support_z=support_z)
            )

        # Sort each category deterministically
        # Floor: lowest X first (inner to door), then Y
        result[AnchorCategory.FLOOR_FRONTIER].sort(key=lambda a: (round(a.x, 4), round(a.y, 4)))
        # Supported: lowest X first, then lowest Z, then Y
        result[AnchorCategory.SUPPORTED_FRONTIER].sort(key=lambda a: (round(a.x, 4), round(a.z, 4), round(a.y, 4)))
        # Wall: lowest X first, then Y, then Z
        result[AnchorCategory.WALL_FRONTIER].sort(key=lambda a: (round(a.x, 4), round(a.y, 4), round(a.z, 4)))
        # Top surface: lowest X first, then Z, then Y
        result[AnchorCategory.TOP_SURFACE].sort(key=lambda a: (round(a.x, 4), round(a.z, 4), round(a.y, 4)))
        # EP & EMS: sorted by (x, y, z)
        result[AnchorCategory.EXTREME_POINT].sort(key=lambda a: (round(a.x, 4), round(a.y, 4), round(a.z, 4)))
        result[AnchorCategory.EMS_CORNER].sort(key=lambda a: (round(a.x, 4), round(a.y, 4), round(a.z, 4)))
        result[AnchorCategory.EXPLORATION].sort(key=lambda a: (round(a.x, 4), round(a.y, 4), round(a.z, 4)))

        return result

    def get_candidate_anchors(self) -> List[Point3D]:
        """
        Returns 3D anchor points for candidate generation.
        Combines Extreme Points with EMS lower-left-front corners.
        Prioritizes floor anchors (z ≈ 0) and supported anchors before high floating points.
        """
        classified = self.get_classified_anchors()
        ordered_points: List[Point3D] = []
        seen = set()

        # Prioritized order: Floor frontier -> Supported frontier -> Wall frontier -> EMS -> EP -> Exploration
        priority_categories = [
            AnchorCategory.FLOOR_FRONTIER,
            AnchorCategory.SUPPORTED_FRONTIER,
            AnchorCategory.WALL_FRONTIER,
            AnchorCategory.EMS_CORNER,
            AnchorCategory.TOP_SURFACE,
            AnchorCategory.EXTREME_POINT,
            AnchorCategory.EXPLORATION,
        ]

        for cat in priority_categories:
            for anch in classified.get(cat, []):
                key = (round(anch.x, 4), round(anch.y, 4), round(anch.z, 4))
                if key not in seen:
                    seen.add(key)
                    ordered_points.append(anch.point)

        return ordered_points

    def get_current_metrics(self, remaining_skus: Optional[List[CargoSKU]] = None) -> ResidualSpaceMetrics:
        """Computes and returns current residual metrics."""
        metrics, _ = self.reachability_analyzer.analyze(
            placements=self._current_placements,
            remaining_skus=remaining_skus,
            ems_list=self.ems_manager.spaces,
        )
        return metrics
