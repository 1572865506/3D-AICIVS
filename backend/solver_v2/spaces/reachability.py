"""
Reachability, Cavity, Dead Space, and Fragmentation Analysis for Solver V2.
Strictly evaluates 3D container free space topology against committed cargo and door-side accessibility.
"""
from typing import List, Tuple, Optional, Set, Dict
from collections import deque
import math

from backend.solver_v2.domain.models import ContainerSpec, CargoSKU, Placement, BoxDim
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.spaces.types import SpaceClass, FreeSpaceBox, ResidualSpaceMetrics


class ReachabilityAnalyzer:
    """
    Analyzes door-side reachability, enclosed cavities, narrow slivers, and dead space.
    """

    def __init__(
        self,
        container: ContainerSpec,
        grid_resolution: float = 0.1,  # 10cm voxel grid for exact reachability flood-fill
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
    ):
        self.container = container
        self.grid_resolution = grid_resolution
        self.geom_epsilon = geom_epsilon

        # Compute grid dimensions
        self.nx = max(1, int(math.ceil(container.Lx / grid_resolution)))
        self.ny = max(1, int(math.ceil(container.Ly / grid_resolution)))
        self.nz = max(1, int(math.ceil(container.Lz / grid_resolution)))
        self.cell_vol = (container.Lx / self.nx) * (container.Ly / self.ny) * (container.Lz / self.nz)

    def analyze(
        self,
        placements: List[Placement],
        remaining_skus: Optional[List[CargoSKU]] = None,
        ems_list: Optional[List[AABB]] = None,
    ) -> Tuple[ResidualSpaceMetrics, List[FreeSpaceBox]]:
        """
        Runs comprehensive residual space analysis:
        1. Classifies 3D container voxel occupancy (0: empty, 1: occupied by cargo).
        2. Door-side flood-fill from x=Lx boundary inwards.
        3. Identifies reachable voxels, unreachable cavity voxels, and slivers.
        4. Matches against remaining SKU minimum bounding dimensions to identify dead space.
        5. Computes fragmentation score across EMS.
        """
        # Determine minimum SKU dimensions among remaining cargo
        min_sku_dim_x, min_sku_dim_y, min_sku_dim_z = self._get_min_sku_dims(remaining_skus)
        min_sku_vol = min_sku_dim_x * min_sku_dim_y * min_sku_dim_z

        # If no placements, container is 100% open useful
        total_container_vol = self.container.volume
        if not placements:
            metrics = ResidualSpaceMetrics(
                useful_volume=total_container_vol,
                reachable_volume=total_container_vol,
                dead_volume=0.0,
                enclosed_cavity_volume=0.0,
                sliver_volume=0.0,
                fragmentation_score=0.0,
                total_free_volume=total_container_vol,
                ems_count=1,
                extreme_points_count=1,
            )
            free_box = FreeSpaceBox(
                space_id="initial_container_space",
                aabb=AABB(0.0, 0.0, 0.0, self.container.Lx, self.container.Ly, self.container.Lz),
                space_class=SpaceClass.OPEN_USEFUL,
                is_reachable_from_door=True,
                fit_sku_count=len(remaining_skus) if remaining_skus else 1,
            )
            return metrics, [free_box]

        # 1. Rasterize placements onto 3D grid
        # 0 = Free, 1 = Occupied
        # Grid indexing: index = ix * (ny * nz) + iy * nz + iz
        occupied_grid = bytearray(self.nx * self.ny * self.nz)
        dx_cell = self.container.Lx / self.nx
        dy_cell = self.container.Ly / self.ny
        dz_cell = self.container.Lz / self.nz

        occupied_volume = 0.0
        for p in placements:
            occupied_volume += p.volume
            # Compute grid index bounds
            ix_min = max(0, int(p.min_x / dx_cell))
            ix_max = min(self.nx, int(math.ceil((p.max_x - self.geom_epsilon) / dx_cell)))
            iy_min = max(0, int(p.min_y / dy_cell))
            iy_max = min(self.ny, int(math.ceil((p.max_y - self.geom_epsilon) / dy_cell)))
            iz_min = max(0, int(p.min_z / dz_cell))
            iz_max = min(self.nz, int(math.ceil((p.max_z - self.geom_epsilon) / dz_cell)))

            for ix in range(ix_min, ix_max):
                for iy in range(iy_min, iy_max):
                    base_idx = ix * (self.ny * self.nz) + iy * self.nz
                    for iz in range(iz_min, iz_max):
                        occupied_grid[base_idx + iz] = 1

        # 2. Door-side Flood Fill (BFS starting from open cells at door plane ix = nx - 1)
        # 0 = Unreachable/Unvisited Free, 1 = Occupied, 2 = Reachable Free
        grid_status = bytearray(occupied_grid)
        queue = deque()

        # Seed door plane (ix = self.nx - 1)
        door_ix = self.nx - 1
        for iy in range(self.ny):
            base_idx = door_ix * (self.ny * self.nz) + iy * self.nz
            for iz in range(self.nz):
                if grid_status[base_idx + iz] == 0:
                    grid_status[base_idx + iz] = 2  # Mark reachable
                    queue.append((door_ix, iy, iz))

        # BFS expansion (6-connected neighbors)
        nx_m1 = self.nx - 1
        ny_m1 = self.ny - 1
        nz_m1 = self.nz - 1

        while queue:
            cx, cy, cz = queue.popleft()

            # Check 6 neighbors
            # -X
            if cx > 0:
                nidx = (cx - 1) * (self.ny * self.nz) + cy * self.nz + cz
                if grid_status[nidx] == 0:
                    grid_status[nidx] = 2
                    queue.append((cx - 1, cy, cz))
            # +X
            if cx < nx_m1:
                nidx = (cx + 1) * (self.ny * self.nz) + cy * self.nz + cz
                if grid_status[nidx] == 0:
                    grid_status[nidx] = 2
                    queue.append((cx + 1, cy, cz))
            # -Y
            if cy > 0:
                nidx = cx * (self.ny * self.nz) + (cy - 1) * self.nz + cz
                if grid_status[nidx] == 0:
                    grid_status[nidx] = 2
                    queue.append((cx, cy - 1, cz))
            # +Y
            if cy < ny_m1:
                nidx = cx * (self.ny * self.nz) + (cy + 1) * self.nz + cz
                if grid_status[nidx] == 0:
                    grid_status[nidx] = 2
                    queue.append((cx, cy + 1, cz))
            # -Z
            if cz > 0:
                nidx = cx * (self.ny * self.nz) + cy * self.nz + (cz - 1)
                if grid_status[nidx] == 0:
                    grid_status[nidx] = 2
                    queue.append((cx, cy, cz - 1))
            # +Z
            if cz < nz_m1:
                nidx = cx * (self.ny * self.nz) + cy * self.nz + (cz + 1)
                if grid_status[nidx] == 0:
                    grid_status[nidx] = 2
                    queue.append((cx, cy, cz + 1))

        # 3. Analyze connected components of unreachable empty cells (status == 0)
        # Any status==0 is an unreachable/enclosed cavity
        unreachable_cell_count = 0
        reachable_cell_count = 0
        for val in grid_status:
            if val == 0:
                unreachable_cell_count += 1
            elif val == 2:
                reachable_cell_count += 1

        unreachable_volume = unreachable_cell_count * self.cell_vol
        reachable_volume = reachable_cell_count * self.cell_vol
        total_free_vol = unreachable_volume + reachable_volume

        # 4. Sliver and Dead Space Analysis from EMS boxes
        # A sliver is an EMS box whose dimension is smaller than min allowable cargo dimension
        sliver_volume = 0.0
        dead_volume = unreachable_volume
        active_ems = ems_list or []

        for ems in active_ems:
            # Check if EMS is a sliver (smaller than minimum SKU dimension in any dimension)
            if (ems.dx < min_sku_dim_x - self.geom_epsilon or
                ems.dy < min_sku_dim_y - self.geom_epsilon or
                ems.dz < min_sku_dim_z - self.geom_epsilon):
                # Small sliver
                sliver_volume += ems.volume
            else:
                # Check if it can fit any remaining SKU in any orientation
                can_fit_any = False
                if remaining_skus:
                    for sku in remaining_skus:
                        if (ems.dx >= sku.box.x - self.geom_epsilon and
                            ems.dy >= sku.box.y - self.geom_epsilon and
                            ems.dz >= sku.box.z - self.geom_epsilon):
                            can_fit_any = True
                            break
                        # Check rotated
                        if (ems.dx >= sku.box.y - self.geom_epsilon and
                            ems.dy >= sku.box.x - self.geom_epsilon and
                            ems.dz >= sku.box.z - self.geom_epsilon):
                            can_fit_any = True
                            break
                else:
                    can_fit_any = True

                if not can_fit_any:
                    dead_volume += ems.volume

        # Bound sliver and dead volumes so they do not exceed total free volume
        sliver_volume = min(sliver_volume, total_free_vol)
        dead_volume = min(dead_volume, total_free_vol)
        enclosed_cavity_volume = unreachable_volume

        # Useful volume = reachable volume minus sliver and dead space components
        useful_volume = max(0.0, reachable_volume - sliver_volume)

        # 5. Compute Fragmentation Score
        fragmentation_score = self._compute_fragmentation(active_ems, useful_volume, total_container_vol)

        metrics = ResidualSpaceMetrics(
            useful_volume=round(useful_volume, 6),
            reachable_volume=round(reachable_volume, 6),
            dead_volume=round(dead_volume, 6),
            enclosed_cavity_volume=round(enclosed_cavity_volume, 6),
            sliver_volume=round(sliver_volume, 6),
            fragmentation_score=round(fragmentation_score, 6),
            total_free_volume=round(total_free_vol, 6),
            ems_count=len(active_ems),
        )

        classified_boxes = self._classify_free_boxes(
            active_ems, remaining_skus, min_sku_dim_x, min_sku_dim_y, min_sku_dim_z,
            unreachable_volume=unreachable_volume,
            frontier_x=max((p.max_x for p in placements), default=0.0)
        )
        return metrics, classified_boxes

    def _get_min_sku_dims(self, remaining_skus: Optional[List[CargoSKU]]) -> Tuple[float, float, float]:
        """Returns the minimal (x, y, z) dimensions across remaining SKUs."""
        if not remaining_skus:
            return (0.10, 0.10, 0.10)

        min_x = min(s.box.x for s in remaining_skus)
        min_y = min(s.box.y for s in remaining_skus)
        min_z = min(s.box.z for s in remaining_skus)

        # Minimum across orientations
        min_side = min(min_x, min_y, min_z)
        return (min_side, min_side, min_side)

    def _compute_fragmentation(self, ems_list: List[AABB], useful_volume: float, container_vol: float) -> float:
        """
        Computes fragmentation score:
        Higher score means free space is fragmented into many small disjoint pieces.
        Low score means free space is dominated by a few large contiguous blocks.
        """
        if not ems_list or useful_volume <= 1e-6:
            return 0.0

        n = len(ems_list)
        if n == 1:
            return 0.0

        # Normalized EMS count per unit useful volume
        count_factor = (n - 1) / 10.0

        # Entropy / size variance across EMS spaces
        vols = [max(1e-9, s.volume) for s in ems_list]
        total_v = sum(vols)
        probs = [v / total_v for v in vols]
        entropy = -sum(p * math.log(p) for p in probs)

        return (count_factor * 0.5) + (entropy * 0.5)

    def _classify_free_boxes(
        self,
        ems_list: List[AABB],
        remaining_skus: Optional[List[CargoSKU]],
        min_x: float,
        min_y: float,
        min_z: float,
        unreachable_volume: float = 0.0,
        frontier_x: float = 0.0,
    ) -> List[FreeSpaceBox]:
        """Classifies each EMS into SpaceClass category with accurate door reachability."""
        boxes: List[FreeSpaceBox] = []
        for i, aabb in enumerate(ems_list):
            is_sliver = (aabb.dx < min_x or aabb.dy < min_y or aabb.dz < min_z)
            is_reachable = (
                aabb.max_x >= frontier_x - self.geom_epsilon or
                aabb.max_x >= self.container.Lx - 0.2 or
                unreachable_volume <= self.geom_epsilon
            )
            if is_sliver:
                sclass = SpaceClass.SLIVER
            elif not is_reachable:
                sclass = SpaceClass.ENCLOSED_CAVITY
            else:
                sclass = SpaceClass.OPEN_USEFUL

            boxes.append(FreeSpaceBox(
                space_id=f"ems_{i}",
                aabb=aabb,
                space_class=sclass,
                is_reachable_from_door=is_reachable,
                fit_sku_count=len(remaining_skus) if remaining_skus else 1,
            ))
        return boxes
