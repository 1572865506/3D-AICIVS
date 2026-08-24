"""
Wall Surface Map and Active Packing Frontier for Solver V2 (Agent 08 / P0 BLK-001 Phase 2).
Discretizes the transverse cross-section (y, z) into a 2D elevation grid to track:
- Longitudinal frontier surface x(y, z)
- FloorFrontier, RowFrontier, LayerFrontier, WallFrontier
- Valley detection (valleys, steps, incomplete rows/layers)
- Continuous floor frontier recovery (rebuild_floor_frontier)
"""
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any, Set
import math

from backend.solver_v2.domain.models import ContainerSpec, Placement, Point3D
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.spaces.types import AnchorCategory, ClassifiedAnchor


@dataclass(frozen=True)
class ValleyRegion:
    """Represents a detected recessed valley / depression on the cargo wall front."""
    min_y: float
    max_y: float
    min_z: float
    max_z: float
    floor_x: float          # Bottom/recessed X of this valley
    target_max_x: float     # Surrounding wall peak X to fill up to
    depth_m: float          # target_max_x - floor_x

    @property
    def anchor(self) -> Point3D:
        """Preferred fill anchor point (bottom-left of valley)."""
        return Point3D(self.floor_x, self.min_y, self.min_z)


@dataclass
class ActivePackingFrontier:
    """
    Authoritative state of the active packing frontier reconstructed from WorldState.
    """
    max_x: float = 0.0
    min_x: float = 0.0
    mean_x: float = 0.0
    flatness_score: float = 1.0
    occupancy_ratio: float = 0.0
    floor_frontier_anchors: List[ClassifiedAnchor] = field(default_factory=list)
    row_frontier_anchors: List[ClassifiedAnchor] = field(default_factory=list)
    layer_frontier_anchors: List[ClassifiedAnchor] = field(default_factory=list)
    wall_frontier_anchors: List[ClassifiedAnchor] = field(default_factory=list)
    valleys: List[ValleyRegion] = field(default_factory=list)
    incomplete_rows: List[float] = field(default_factory=list)
    incomplete_layers: List[float] = field(default_factory=list)


@dataclass(frozen=True)
class WallSurfaceMetrics:
    """Quantitative metrics describing the front frontier surface of the cargo wall."""
    min_x: float
    max_x: float
    mean_x: float
    variance_x: float
    std_dev_x: float
    flatness_score: float         # 0.0 (highly jagged/irregular) to 1.0 (perfectly flat vertical face)
    occupancy_ratio: float        # Fraction of transverse cross-section covered by cargo (0.0 to 1.0)
    max_step_discontinuity: float # Max Delta x between neighboring occupied cells in y or z
    avg_step_discontinuity: float # Average Delta x across adjacent occupied surface cells
    hollow_cell_count: int        # Number of recessed cells creating pockets/indentations


class WallSurfaceMap:
    """
    2D elevation grid across transverse cross-section (y, z) representing the front frontier x(y, z).
    """

    def __init__(
        self,
        container: ContainerSpec,
        grid_resolution_m: float = 0.1,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
    ):
        self.container = container
        self.res = grid_resolution_m
        self.geom_epsilon = geom_epsilon

        self.num_y = max(1, int(math.ceil(container.Ly / self.res)))
        self.num_z = max(1, int(math.ceil(container.Lz / self.res)))

        # 2D Grid: grid[iy][iz] = frontier max_x for this cell (0.0 if empty)
        self.grid: List[List[float]] = [[0.0 for _ in range(self.num_z)] for _ in range(self.num_y)]
        self._placements: List[Placement] = []

    def clear(self) -> None:
        """Resets the surface map to empty container."""
        for iy in range(self.num_y):
            for iz in range(self.num_z):
                self.grid[iy][iz] = 0.0
        self._placements.clear()

    def build_from_placements(self, placements: List[Placement]) -> WallSurfaceMetrics:
        """
        Reconstructs the 2D wall surface map from the given list of placements and returns metrics.
        """
        self.clear()
        self._placements = list(placements)

        for p in placements:
            self._rasterize_placement(p)

        return self.compute_metrics()

    def add_placement(self, placement: Placement) -> None:
        """Incrementally rasterizes a newly added placement onto the wall surface map."""
        self._placements.append(placement)
        self._rasterize_placement(placement)

    def _rasterize_placement(self, placement: Placement) -> None:
        cand_aabb = AABB.from_placement(placement)
        iy_start = max(0, int(cand_aabb.min_y // self.res))
        iy_end = min(self.num_y, int(math.ceil(cand_aabb.max_y / self.res)))
        iz_start = max(0, int(cand_aabb.min_z // self.res))
        iz_end = min(self.num_z, int(math.ceil(cand_aabb.max_z / self.res)))

        for iy in range(iy_start, iy_end):
            for iz in range(iz_start, iz_end):
                self.grid[iy][iz] = max(self.grid[iy][iz], cand_aabb.max_x)

    def get_frontier_x(self, y: float, z: float) -> float:
        """Returns the current frontier x coordinate at given (y, z)."""
        iy = max(0, min(self.num_y - 1, int(y // self.res)))
        iz = max(0, min(self.num_z - 1, int(z // self.res)))
        return self.grid[iy][iz]

    def find_valleys(self, recess_threshold: float = 0.15) -> List[ValleyRegion]:
        """
        Scans the 2D surface grid to detect recessed valleys / depressions where x(y,z) < max_x - threshold.
        """
        metrics = self.compute_metrics()
        peak_x = metrics.max_x
        if peak_x <= self.geom_epsilon:
            return []

        valleys: List[ValleyRegion] = []
        visited = [[False for _ in range(self.num_z)] for _ in range(self.num_y)]

        for iy in range(self.num_y):
            for iz in range(self.num_z):
                if visited[iy][iz]:
                    continue

                curr_x = self.grid[iy][iz]
                depth = peak_x - curr_x
                if depth >= recess_threshold:
                    # Flood-fill region of similar depth
                    region_iy = [iy]
                    region_iz = [iz]
                    visited[iy][iz] = True

                    min_y = iy * self.res
                    max_y = (iy + 1) * self.res
                    min_z = iz * self.res
                    max_z = (iz + 1) * self.res

                    valleys.append(ValleyRegion(
                        min_y=min_y,
                        max_y=max_y,
                        min_z=min_z,
                        max_z=max_z,
                        floor_x=curr_x,
                        target_max_x=peak_x,
                        depth_m=depth,
                    ))

        return valleys

    def rebuild_floor_frontier(self, max_allowed_x: Optional[float] = None) -> List[ClassifiedAnchor]:
        """
        Reconstructs available floor frontier anchors (z ≈ 0) across all lateral spans y ∈ [0, Ly].
        Ensures that floor space is always discoverable as long as x < max_allowed_x.
        """
        eps = self.geom_epsilon
        limit_x = max_allowed_x or self.container.Lx
        floor_anchors: List[ClassifiedAnchor] = []
        seen = set()

        for iy in range(self.num_y):
            y_pos = iy * self.res
            # Find frontier X along bottom layer (iz = 0)
            front_x = self.grid[iy][0]

            if front_x < limit_x - eps:
                pt = Point3D(front_x, y_pos, 0.0)
                key = (round(pt.x, 3), round(pt.y, 3), 0.0)
                if key not in seen:
                    seen.add(key)
                    floor_anchors.append(ClassifiedAnchor(
                        point=pt,
                        category=AnchorCategory.FLOOR_FRONTIER,
                        support_z=0.0,
                        priority_score=pt.x * 10.0 + pt.y,
                    ))

        # Also add discrete y positions along committed item boundaries
        for p in self._placements:
            if p.position.z <= eps:
                # Advancing X from this box
                bx = p.position.x + p.orientation.dx
                by = p.position.y
                if bx < limit_x - eps:
                    pt = Point3D(bx, by, 0.0)
                    key = (round(pt.x, 3), round(pt.y, 3), 0.0)
                    if key not in seen:
                        seen.add(key)
                        floor_anchors.append(ClassifiedAnchor(
                            point=pt,
                            category=AnchorCategory.FLOOR_FRONTIER,
                            support_z=0.0,
                            priority_score=pt.x * 10.0 + pt.y,
                        ))

        floor_anchors.sort(key=lambda a: (round(a.x, 4), round(a.y, 4)))
        return floor_anchors

    def extract_active_packing_frontier(
        self,
        placements: List[Placement],
        max_allowed_x: Optional[float] = None,
    ) -> ActivePackingFrontier:
        """
        Full extraction of ActivePackingFrontier directly from placements.
        """
        metrics = self.build_from_placements(placements)
        floor_anchors = self.rebuild_floor_frontier(max_allowed_x)
        valleys = self.find_valleys()

        # Wall and layer frontier anchors
        wall_anchors: List[ClassifiedAnchor] = []
        layer_anchors: List[ClassifiedAnchor] = []
        seen = set()

        for p in placements:
            top_z = p.position.z + p.orientation.dz
            max_x = p.position.x + p.orientation.dx
            # Layer continuation anchor (on top of box)
            if top_z < self.container.Lz - self.geom_epsilon:
                pt_layer = Point3D(p.position.x, p.position.y, top_z)
                key_l = (round(pt_layer.x, 3), round(pt_layer.y, 3), round(pt_layer.z, 3))
                if key_l not in seen:
                    seen.add(key_l)
                    layer_anchors.append(ClassifiedAnchor(
                        point=pt_layer,
                        category=AnchorCategory.SUPPORTED_FRONTIER,
                        support_z=top_z,
                        priority_score=pt_layer.x * 10.0 + pt_layer.z,
                    ))

            # Wall continuation anchor (in front of box)
            if max_x < (max_allowed_x or self.container.Lx) - self.geom_epsilon:
                pt_wall = Point3D(max_x, p.position.y, p.position.z)
                key_w = (round(pt_wall.x, 3), round(pt_wall.y, 3), round(pt_wall.z, 3))
                if key_w not in seen:
                    seen.add(key_w)
                    wall_anchors.append(ClassifiedAnchor(
                        point=pt_wall,
                        category=AnchorCategory.WALL_FRONTIER,
                        support_z=p.position.z,
                        priority_score=pt_wall.y * 10.0 + pt_wall.z,
                    ))

        return ActivePackingFrontier(
            max_x=metrics.max_x,
            min_x=metrics.min_x,
            mean_x=metrics.mean_x,
            flatness_score=metrics.flatness_score,
            occupancy_ratio=metrics.occupancy_ratio,
            floor_frontier_anchors=floor_anchors,
            layer_frontier_anchors=layer_anchors,
            wall_frontier_anchors=wall_anchors,
            valleys=valleys,
        )

    def compute_metrics(self) -> WallSurfaceMetrics:
        """
        Computes comprehensive flatness, occupancy, variance, and discontinuity metrics.
        """
        total_cells = self.num_y * self.num_z
        if not self._placements or total_cells == 0:
            return WallSurfaceMetrics(
                min_x=0.0,
                max_x=0.0,
                mean_x=0.0,
                variance_x=0.0,
                std_dev_x=0.0,
                flatness_score=1.0,
                occupancy_ratio=0.0,
                max_step_discontinuity=0.0,
                avg_step_discontinuity=0.0,
                hollow_cell_count=0,
            )

        active_x_values: List[float] = []
        occupied_cells = 0

        for iy in range(self.num_y):
            for iz in range(self.num_z):
                x_val = self.grid[iy][iz]
                if x_val > self.geom_epsilon:
                    active_x_values.append(x_val)
                    occupied_cells += 1

        occupancy_ratio = occupied_cells / float(total_cells)

        if not active_x_values:
            return WallSurfaceMetrics(
                min_x=0.0,
                max_x=0.0,
                mean_x=0.0,
                variance_x=0.0,
                std_dev_x=0.0,
                flatness_score=1.0,
                occupancy_ratio=0.0,
                max_step_discontinuity=0.0,
                avg_step_discontinuity=0.0,
                hollow_cell_count=0,
            )

        min_x = min(active_x_values)
        max_x = max(active_x_values)
        mean_x = sum(active_x_values) / len(active_x_values)

        variance_x = sum((x - mean_x) ** 2 for x in active_x_values) / len(active_x_values)
        std_dev_x = math.sqrt(variance_x)

        raw_flatness = 1.0 / (1.0 + 2.0 * std_dev_x)

        # Discontinuity calculations between adjacent occupied cells
        step_diffs: List[float] = []
        hollow_count = 0

        for iy in range(self.num_y):
            for iz in range(self.num_z):
                curr = self.grid[iy][iz]
                if curr <= self.geom_epsilon:
                    continue

                # Check neighbor along Y (if neighbor is also occupied)
                if iy + 1 < self.num_y:
                    neighbor_y = self.grid[iy + 1][iz]
                    if neighbor_y > self.geom_epsilon:
                        step_diffs.append(abs(curr - neighbor_y))

                # Check neighbor along Z (if neighbor is also occupied)
                if iz + 1 < self.num_z:
                    neighbor_z = self.grid[iy][iz + 1]
                    if neighbor_z > self.geom_epsilon:
                        step_diffs.append(abs(curr - neighbor_z))

                # Hollow detection: if occupied cell is significantly recessed behind max_x
                if max_x - curr > 0.30:  # > 30cm recess
                    hollow_count += 1

        max_step = max(step_diffs) if step_diffs else 0.0
        avg_step = (sum(step_diffs) / len(step_diffs)) if step_diffs else 0.0

        return WallSurfaceMetrics(
            min_x=min_x,
            max_x=max_x,
            mean_x=mean_x,
            variance_x=variance_x,
            std_dev_x=std_dev_x,
            flatness_score=round(raw_flatness, 4),
            occupancy_ratio=round(occupancy_ratio, 4),
            max_step_discontinuity=round(max_step, 4),
            avg_step_discontinuity=round(avg_step, 4),
            hollow_cell_count=hollow_count,
        )
