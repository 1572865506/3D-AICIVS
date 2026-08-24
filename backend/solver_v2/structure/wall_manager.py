"""
Wall Structure Manager and Cavity/Void Detector for Solver V2 (Agent 08 - Wall / Top Fill / Door).
Enforces Bad Case 001 regression avoidance: wall construction actively avoids internal enclosed voids.
"""
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any, Set
import math

from backend.solver_v2.domain.models import ContainerSpec, Placement, Point3D, CargoSKU
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.structure.wall_surface import WallSurfaceMap, WallSurfaceMetrics


@dataclass(frozen=True)
class EnclosedVoidReport:
    """Quantitative report on internal enclosed cavities and hollow voids within cargo walls."""
    has_enclosed_voids: bool
    void_count: int
    total_void_volume_m3: float
    max_single_void_volume_m3: float
    enclosed_void_penalty: float
    rejection_reason: Optional[str] = None


@dataclass(frozen=True)
class WallSlice:
    """An atomic transverse wall band before logical-wall segmentation.

    ``placements`` are kept atomic: a carton is assigned to exactly one slice even
    when its AABB crosses a diagnostic sampling plane.  The optional structural
    fields are backward-compatible with the original fixed-grid slice API.
    """
    slice_index: int
    min_x: float
    max_x: float
    thickness: float
    placements: Tuple[Placement, ...]
    occupancy_ratio: float
    is_complete: bool
    cross_section_area_m2: float = 0.0
    frontier_area_m2: float = 0.0
    is_micro_slice: bool = False


class CavityVoidDetector:
    """
    Bad Case 001 regression avoidance detector.
    Detects internal enclosed hollow cavities surrounded by cargo walls/container boundaries.
    """

    def __init__(
        self,
        container: ContainerSpec,
        voxel_res_m: float = 0.10,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
    ):
        self.container = container
        self.res = voxel_res_m
        self.geom_epsilon = geom_epsilon

        self.nx = max(1, int(math.ceil(container.Lx / self.res)))
        self.ny = max(1, int(math.ceil(container.Ly / self.res)))
        self.nz = max(1, int(math.ceil(container.Lz / self.res)))

    def detect_enclosed_voids(
        self,
        placements: List[Placement],
        max_allowed_void_vol_m3: float = 0.02,
    ) -> EnclosedVoidReport:
        """
        Runs 3D flood-fill reachability analysis to identify any enclosed, unreachable hollow voids
        behind the loading frontier.
        
        A voxel is considered an ENCLOSED VOID if:
        1. It is empty (not occupied by any cargo placement).
        2. Its x coordinate is <= the current cargo frontier max_x (it lies behind the active front).
        3. It cannot be reached by a 3D flood-fill starting from the open loading doorway (x = Lx) or roof.
        """
        if not placements:
            return EnclosedVoidReport(
                has_enclosed_voids=False,
                void_count=0,
                total_void_volume_m3=0.0,
                max_single_void_volume_m3=0.0,
                enclosed_void_penalty=0.0,
                rejection_reason=None,
            )

        # 1. Rasterize placements onto 3D voxel grid (0 = empty, 1 = occupied)
        grid = [[[0 for _ in range(self.nz)] for _ in range(self.ny)] for _ in range(self.nx)]

        max_cargo_x = 0.0
        for p in placements:
            aabb = AABB.from_placement(p)
            max_cargo_x = max(max_cargo_x, aabb.max_x)

            ix_start = max(0, int(aabb.min_x // self.res))
            ix_end = min(self.nx, int(math.ceil(aabb.max_x / self.res)))
            iy_start = max(0, int(aabb.min_y // self.res))
            iy_end = min(self.ny, int(math.ceil(aabb.max_y / self.res)))
            iz_start = max(0, int(aabb.min_z // self.res))
            iz_end = min(self.nz, int(math.ceil(aabb.max_z / self.res)))

            for ix in range(ix_start, ix_end):
                for iy in range(iy_start, iy_end):
                    for iz in range(iz_start, iz_end):
                        grid[ix][iy][iz] = 1

        frontier_ix = min(self.nx, int(math.ceil(max_cargo_x / self.res)))

        # 2. 3D Flood-Fill from open front (x >= frontier_ix), roof (z = nz - 1), and door (x = nx - 1)
        queue: List[Tuple[int, int, int]] = []

        for ix in range(self.nx):
            for iy in range(self.ny):
                for iz in range(self.nz):
                    if ix >= frontier_ix or ix == self.nx - 1 or iz == self.nz - 1:
                        if grid[ix][iy][iz] == 0:
                            grid[ix][iy][iz] = 2  # Reachable air
                            queue.append((ix, iy, iz))

        # BFS expansion in 6 directions
        neighbors = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
        while queue:
            cx, cy, cz = queue.pop(0)
            for dx, dy, dz in neighbors:
                nx = cx + dx
                ny = cy + dy
                nz = cz + dz
                if 0 <= nx < self.nx and 0 <= ny < self.ny and 0 <= nz < self.nz:
                    if grid[nx][ny][nz] == 0:
                        grid[nx][ny][nz] = 2  # Marked as reachable
                        queue.append((nx, ny, nz))

        # 3. Any empty voxel behind frontier (ix < frontier_ix) that remained unvisited (grid == 0)
        # is an internal enclosed cavity/void.
        voxel_vol = self.res ** 3
        void_components: List[int] = []

        visited_voids: Set[Tuple[int, int, int]] = set()

        for ix in range(frontier_ix):
            for iy in range(self.ny):
                for iz in range(self.nz):
                    if grid[ix][iy][iz] == 0 and (ix, iy, iz) not in visited_voids:
                        cluster_size = 0
                        void_q = [(ix, iy, iz)]
                        visited_voids.add((ix, iy, iz))

                        while void_q:
                            vx, vy, vz = void_q.pop(0)
                            cluster_size += 1
                            for dx, dy, dz in neighbors:
                                nnx, nny, nnz = vx + dx, vy + dy, vz + dz
                                if 0 <= nnx < frontier_ix and 0 <= nny < self.ny and 0 <= nnz < self.nz:
                                    if grid[nnx][nny][nnz] == 0 and (nnx, nny, nnz) not in visited_voids:
                                        visited_voids.add((nnx, nny, nnz))
                                        void_q.append((nnx, nny, nnz))

                        void_components.append(cluster_size)

        total_void_voxels = sum(void_components)
        total_void_vol = total_void_voxels * voxel_vol
        max_single_void_vol = (max(void_components) * voxel_vol) if void_components else 0.0

        has_voids = total_void_vol > max_allowed_void_vol_m3
        penalty = total_void_vol * 1500.0

        reason = None
        if has_voids:
            reason = (
                f"Bad Case 001 Violation: Detected {len(void_components)} internal enclosed voids "
                f"(total volume={total_void_vol:.4f}m^3, max single void={max_single_void_vol:.4f}m^3)"
            )

        return EnclosedVoidReport(
            has_enclosed_voids=has_voids,
            void_count=len(void_components),
            total_void_volume_m3=round(total_void_vol, 5),
            max_single_void_volume_m3=round(max_single_void_vol, 5),
            enclosed_void_penalty=round(penalty, 2),
            rejection_reason=reason,
        )


class WallStructureManager:
    """
    Manages wall slices, surface elevation maps, and frontier evolution.
    """

    def __init__(
        self,
        container: ContainerSpec,
        grid_resolution_m: float = 0.1,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
    ):
        self.container = container
        self.geom_epsilon = geom_epsilon
        self.surface_map = WallSurfaceMap(container, grid_resolution_m=grid_resolution_m, geom_epsilon=geom_epsilon)
        self.void_detector = CavityVoidDetector(container, voxel_res_m=0.10, geom_epsilon=geom_epsilon)

    def evaluate_wall_structure(
        self,
        placements: List[Placement],
        max_allowed_void_vol_m3: float = 0.02,
    ) -> Tuple[WallSurfaceMetrics, EnclosedVoidReport]:
        """
        Evaluates current wall surface metrics and enclosed void violations.
        """
        surface_metrics = self.surface_map.build_from_placements(placements)
        void_report = self.void_detector.detect_enclosed_voids(placements, max_allowed_void_vol_m3)
        return surface_metrics, void_report

    def slice_container_walls(
        self,
        placements: List[Placement],
        slice_thickness_m: float = 0.5,
    ) -> List[WallSlice]:
        """
        Segments placed cargo into longitudinal transverse wall slices along axis x.
        """
        if not placements:
            return []

        slices: List[WallSlice] = []
        max_x = max(p.max_x for p in placements)
        num_slices = max(1, int(math.ceil(max_x / slice_thickness_m)))

        for s_idx in range(num_slices):
            min_x_slice = s_idx * slice_thickness_m
            max_x_slice = (s_idx + 1) * slice_thickness_m

            slice_placements: List[Placement] = []
            slice_occupied_vol = 0.0

            for p in placements:
                if p.min_x < max_x_slice and p.max_x > min_x_slice:
                    slice_placements.append(p)
                    overlap_x = min(p.max_x, max_x_slice) - max(p.min_x, min_x_slice)
                    slice_occupied_vol += overlap_x * p.orientation.dy * p.orientation.dz

            slice_box_vol = (max_x_slice - min_x_slice) * self.container.Ly * self.container.Lz
            occupancy = (slice_occupied_vol / slice_box_vol) if slice_box_vol > 0 else 0.0

            slices.append(
                WallSlice(
                    slice_index=s_idx,
                    min_x=min_x_slice,
                    max_x=max_x_slice,
                    thickness=slice_thickness_m,
                    placements=tuple(slice_placements),
                    occupancy_ratio=round(min(1.0, occupancy), 4),
                    is_complete=occupancy >= 0.75,
                )
            )

        return slices
