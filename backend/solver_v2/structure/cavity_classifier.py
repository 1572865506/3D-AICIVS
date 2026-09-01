"""
Cavity Classification and Anti-Bridge Void Detector for Solver V2 (Agent 08 / BLK-003).
Formalizes 5 cavity types plus normal future-free-space semantics:
1. OPEN_NOTCH: Transverse or vertical step notch open to the loading frontier.
2. REACHABLE_CAVITY: Void with open top/front access path for future packing.
3. ENCLOSED_CAVITY: Fully surrounded internal void with zero access path (CRITICAL FAULT).
4. DEAD_CAVITY: Usable residual space smaller than any remaining cargo item.
5. SLIVER: Extremely thin void (< 0.05m) between packed boxes or boundary.
6. FUTURE_FREE_SPACE: Door-reachable capacity at/ahead of the local wall frontier (not a cavity).

Also implements Anti-Bridge Rules to prevent spanning across wide internal cavities.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Tuple, Optional, Dict, Any, Set
import math

from backend.solver_v2.domain.models import ContainerSpec, Placement, Point3D, CargoSKU
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON

DEFAULT_VOXEL_RES_M: float = 0.08
DEFAULT_MAX_ENCLOSED_VOID_VOL_M3: float = 0.015


class CavityType(Enum):
    """Classification of internal and frontier voids."""
    OPEN_NOTCH = "OPEN_NOTCH"            # Open indentation on frontier (good fill target)
    REACHABLE_CAVITY = "REACHABLE_CAVITY"# Reachable recess
    ENCLOSED_CAVITY = "ENCLOSED_CAVITY"  # Completely enclosed internal void (must avoid)
    DEAD_CAVITY = "DEAD_CAVITY"          # Unfillable sub-minimum scrap space
    SLIVER = "SLIVER"                    # Thin gap between items
    FUTURE_FREE_SPACE = "FUTURE_FREE_SPACE"  # Normal door-reachable volume ahead of local frontier


@dataclass(frozen=True)
class CavityRegion:
    """Quantitative description of a 3D cavity region."""
    cavity_type: CavityType
    bounding_box: AABB
    volume_m3: float
    voxel_count: int
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    min_z: float
    max_z: float
    is_bridge_void: bool = False
    bridge_span_m: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.cavity_type.value,
            "volume_m3": round(self.volume_m3, 5),
            "bounding_box": [
                round(self.min_x, 3), round(self.min_y, 3), round(self.min_z, 3),
                round(self.max_x, 3), round(self.max_y, 3), round(self.max_z, 3)
            ],
            "is_bridge_void": self.is_bridge_void,
            "bridge_span_m": round(self.bridge_span_m, 3),
        }


@dataclass(frozen=True)
class ComprehensiveCavityReport:
    """Detailed cavity metrics for WorldState and individual candidate evaluations."""
    total_cavity_count: int
    enclosed_cavities: List[CavityRegion]
    reachable_cavities: List[CavityRegion]
    open_notches: List[CavityRegion]
    dead_cavities: List[CavityRegion]
    slivers: List[CavityRegion]
    future_free_spaces: List[CavityRegion]
    
    enclosed_volume_m3: float
    reachable_volume_m3: float
    open_notch_volume_m3: float
    dead_space_volume_m3: float
    sliver_volume_m3: float
    future_free_space_volume_m3: float

    bridge_void_count: int
    max_bridge_span_m: float
    has_critical_enclosed_void: bool
    rejection_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_cavity_count": self.total_cavity_count,
            "enclosed_count": len(self.enclosed_cavities),
            "enclosed_volume_m3": round(self.enclosed_volume_m3, 5),
            "reachable_volume_m3": round(self.reachable_volume_m3, 5),
            "open_notch_volume_m3": round(self.open_notch_volume_m3, 5),
            "dead_space_volume_m3": round(self.dead_space_volume_m3, 5),
            "sliver_volume_m3": round(self.sliver_volume_m3, 5),
            "future_free_space_volume_m3": round(self.future_free_space_volume_m3, 5),
            "bridge_void_count": self.bridge_void_count,
            "max_bridge_span_m": round(self.max_bridge_span_m, 3),
            "has_critical_enclosed_void": self.has_critical_enclosed_void,
            "rejection_reason": self.rejection_reason,
        }


class AdvancedCavityClassifier:
    """
    3D Voxel-based multi-tier cavity classifier and anti-bridge void detector.
    """

    def __init__(
        self,
        container: ContainerSpec,
        voxel_res_m: float = 0.08,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
        max_internal_bridge_span: float = 0.30,
    ):
        self.container = container
        self.res = voxel_res_m
        self.geom_epsilon = geom_epsilon
        self.max_internal_bridge_span = max_internal_bridge_span

        self.nx = max(1, int(math.ceil(container.Lx / self.res)))
        self.ny = max(1, int(math.ceil(container.Ly / self.res)))
        self.nz = max(1, int(math.ceil(container.Lz / self.res)))

    def classify_cavities(
        self,
        placements: List[Placement],
        smallest_sku_volume: float = 0.005,
        max_allowed_enclosed_vol: float = 0.015,
    ) -> ComprehensiveCavityReport:
        """
        Performs 3D flood-fill connectivity analysis to segment, classify, and quantify all cavities.
        """
        if not placements:
            return ComprehensiveCavityReport(
                total_cavity_count=0,
                enclosed_cavities=[],
                reachable_cavities=[],
                open_notches=[],
                dead_cavities=[],
                slivers=[],
                future_free_spaces=[],
                enclosed_volume_m3=0.0,
                reachable_volume_m3=0.0,
                open_notch_volume_m3=0.0,
                dead_space_volume_m3=0.0,
                sliver_volume_m3=0.0,
                future_free_space_volume_m3=round(self.container.volume, 5),
                bridge_void_count=0,
                max_bridge_span_m=0.0,
                has_critical_enclosed_void=False,
            )

        voxel_vol = self.res ** 3

        # 1. Rasterize placements onto 3D voxel grid
        # 0 = Empty, 1 = Solid Cargo, 2 = Open Air / Exterior Reachable
        grid = [[[0 for _ in range(self.nz)] for _ in range(self.ny)] for _ in range(self.nx)]

        max_cargo_x = 0.0
        # Local Y-Z frontier is the semantic boundary between a recess in an
        # existing wall and normal capacity available for future packing.
        local_frontier_x = [[0.0 for _ in range(self.nz)] for _ in range(self.ny)]
        for p in placements:
            aabb = AABB.from_placement(p)
            max_cargo_x = max(max_cargo_x, aabb.max_x)

            ix_s = max(0, int(aabb.min_x // self.res))
            ix_e = min(self.nx, int(math.ceil(aabb.max_x / self.res)))
            iy_s = max(0, int(aabb.min_y // self.res))
            iy_e = min(self.ny, int(math.ceil(aabb.max_y / self.res)))
            iz_s = max(0, int(aabb.min_z // self.res))
            iz_e = min(self.nz, int(math.ceil(aabb.max_z / self.res)))

            for ix in range(ix_s, ix_e):
                for iy in range(iy_s, iy_e):
                    for iz in range(iz_s, iz_e):
                        grid[ix][iy][iz] = 1
            for iy in range(iy_s, iy_e):
                for iz in range(iz_s, iz_e):
                    local_frontier_x[iy][iz] = max(local_frontier_x[iy][iz], aabb.max_x)

        # 1.5 Detect Bridge Voids directly under spanning placements
        bridge_regions: List[CavityRegion] = []
        for p in placements:
            if p.min_z > 0.05:
                # Query what supports this placement
                support_aabb = AABB(p.min_x, p.min_y, p.min_z - 0.05, p.max_x, p.max_y, p.min_z + 0.001)
                # Only true face-contact supports may define a bridge. Near-by
                # cartons (previously accepted within a 20mm band) do not carry
                # this placement and could manufacture a false bridge gap.
                under_items = [it for it in placements if abs(it.max_z - p.min_z) <= self.geom_epsilon and
                               it.max_x > p.min_x and it.min_x < p.max_x and it.max_y > p.min_y and it.min_y < p.max_y]
                if len(under_items) >= 2:
                    # Check gap along Y between supporting items
                    sorted_under = sorted(under_items, key=lambda x: x.min_y)
                    for i in range(len(sorted_under) - 1):
                        gap = sorted_under[i+1].min_y - sorted_under[i].max_y
                        if gap >= self.max_internal_bridge_span:
                            # Localized Bridge Void
                            b_min_y = sorted_under[i].max_y
                            b_max_y = sorted_under[i+1].min_y
                            b_min_z = min(sorted_under[i].min_z, sorted_under[i+1].min_z)
                            b_max_z = p.min_z
                            b_aabb = AABB(p.min_x, b_min_y, b_min_z, p.max_x, b_max_y, b_max_z)
                            b_vol = (p.max_x - p.min_x) * (b_max_y - b_min_y) * (b_max_z - b_min_z)
                            bridge_regions.append(
                                CavityRegion(
                                    cavity_type=CavityType.ENCLOSED_CAVITY,
                                    bounding_box=b_aabb,
                                    volume_m3=b_vol,
                                    voxel_count=max(1, int(round(b_vol / voxel_vol))),
                                    min_x=p.min_x, max_x=p.max_x,
                                    min_y=b_min_y, max_y=b_max_y,
                                    min_z=b_min_z, max_z=b_max_z,
                                    is_bridge_void=True,
                                    bridge_span_m=gap,
                                )
                            )

        # 2. 3D Flood Fill from Exterior (Open doorway at x = nx - 1 and roof at iz = nz - 1)
        queue: List[Tuple[int, int, int]] = []
        for ix in range(self.nx):
            for iy in range(self.ny):
                for iz in range(self.nz):
                    if ix == self.nx - 1 or iz == self.nz - 1:
                        if grid[ix][iy][iz] == 0:
                            grid[ix][iy][iz] = 2
                            queue.append((ix, iy, iz))

        neighbors = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
        while queue:
            cx, cy, cz = queue.pop(0)
            for dx, dy, dz in neighbors:
                nx = cx + dx
                ny = cy + dy
                nz = cz + dz
                if 0 <= nx < self.nx and 0 <= ny < self.ny and 0 <= nz < self.nz:
                    if grid[nx][ny][nz] == 0:
                        grid[nx][ny][nz] = 2
                        queue.append((nx, ny, nz))

        inferred_frontier_x = [row[:] for row in local_frontier_x]
        for iy in range(self.ny):
            for iz in range(self.nz):
                if inferred_frontier_x[iy][iz] > self.geom_epsilon:
                    continue
                bounded_frontiers: List[float] = []
                left = next((local_frontier_x[j][iz] for j in range(iy - 1, -1, -1)
                             if local_frontier_x[j][iz] > self.geom_epsilon), 0.0)
                right = next((local_frontier_x[j][iz] for j in range(iy + 1, self.ny)
                              if local_frontier_x[j][iz] > self.geom_epsilon), 0.0)
                if left > 0.0 and right > 0.0:
                    bounded_frontiers.append(min(left, right))
                below = next((local_frontier_x[iy][j] for j in range(iz - 1, -1, -1)
                              if local_frontier_x[iy][j] > self.geom_epsilon), 0.0)
                above = next((local_frontier_x[iy][j] for j in range(iz + 1, self.nz)
                              if local_frontier_x[iy][j] > self.geom_epsilon), 0.0)
                if below > 0.0 and above > 0.0:
                    bounded_frontiers.append(min(below, above))
                if bounded_frontiers:
                    inferred_frontier_x[iy][iz] = max(bounded_frontiers)

        # Split exterior-reachable air before component clustering.  A reachable
        # voxel behind the frontier at the same (y,z) is a wall notch; a voxel at
        # or ahead of that frontier is ordinary future capacity.
        for ix in range(self.nx):
            center_x = (ix + 0.5) * self.res
            for iy in range(self.ny):
                for iz in range(self.nz):
                    if grid[ix][iy][iz] == 2:
                        frontier_x = inferred_frontier_x[iy][iz]
                        grid[ix][iy][iz] = 4 if frontier_x > self.geom_epsilon and center_x < frontier_x - self.geom_epsilon else 3

        # 3. Cluster unvisited empty voxels into distinct cavity connected components
        enclosed_list: List[CavityRegion] = list(bridge_regions)
        reachable_list: List[CavityRegion] = []
        open_notch_list: List[CavityRegion] = []
        dead_list: List[CavityRegion] = []
        sliver_list: List[CavityRegion] = []
        future_free_list: List[CavityRegion] = []

        visited_voxels: Set[Tuple[int, int, int]] = set()

        for ix in range(self.nx):
            for iy in range(self.ny):
                for iz in range(self.nz):
                    val = grid[ix][iy][iz]
                    if val != 1 and (ix, iy, iz) not in visited_voxels:
                        is_reachable_comp = val in (3, 4)
                        comp_voxels = [(ix, iy, iz)]
                        visited_voxels.add((ix, iy, iz))
                        q = [(ix, iy, iz)]

                        while q:
                            vx, vy, vz = q.pop(0)
                            for dx, dy, dz in neighbors:
                                nnx, nny, nnz = vx + dx, vy + dy, vz + dz
                                if 0 <= nnx < self.nx and 0 <= nny < self.ny and 0 <= nnz < self.nz:
                                    if grid[nnx][nny][nnz] == val and (nnx, nny, nnz) not in visited_voxels:
                                        visited_voxels.add((nnx, nny, nnz))
                                        comp_voxels.append((nnx, nny, nnz))
                                        q.append((nnx, nny, nnz))

                        c_min_x = min(v[0] for v in comp_voxels) * self.res
                        c_max_x = (max(v[0] for v in comp_voxels) + 1) * self.res
                        c_min_y = min(v[1] for v in comp_voxels) * self.res
                        c_max_y = (max(v[1] for v in comp_voxels) + 1) * self.res
                        c_min_z = min(v[2] for v in comp_voxels) * self.res
                        c_max_z = (max(v[2] for v in comp_voxels) + 1) * self.res

                        comp_vol = len(comp_voxels) * voxel_vol
                        span_x = c_max_x - c_min_x
                        span_y = c_max_y - c_min_y
                        span_z = c_max_z - c_min_z

                        cav_aabb = AABB(c_min_x, c_min_y, c_min_z, c_max_x, c_max_y, c_max_z)

                        if val == 3:
                            future_free_list.append(CavityRegion(
                                cavity_type=CavityType.FUTURE_FREE_SPACE,
                                bounding_box=cav_aabb,
                                volume_m3=comp_vol,
                                voxel_count=len(comp_voxels),
                                min_x=c_min_x, max_x=c_max_x,
                                min_y=c_min_y, max_y=c_max_y,
                                min_z=c_min_z, max_z=c_max_z,
                            ))
                        # Check if component is behind or within current active cargo front
                        elif c_min_x < max_cargo_x:
                            # Check bridge condition: empty cavity bounded above by solid cargo
                            is_bridge = False
                            bridge_span = 0.0
                            if c_max_z < self.container.Lz - 0.05 and span_y >= self.max_internal_bridge_span:
                                top_iz = min(self.nz - 1, int(math.ceil(c_max_z / self.res)))
                                if any(grid[v[0]][v[1]][top_iz] == 1 for v in comp_voxels if top_iz < self.nz):
                                    is_bridge = True
                                    bridge_span = span_y

                            if val == 0 or is_bridge:
                                region = CavityRegion(
                                    cavity_type=CavityType.ENCLOSED_CAVITY,
                                    bounding_box=cav_aabb,
                                    volume_m3=comp_vol,
                                    voxel_count=len(comp_voxels),
                                    min_x=c_min_x, max_x=c_max_x,
                                    min_y=c_min_y, max_y=c_max_y,
                                    min_z=c_min_z, max_z=c_max_z,
                                    is_bridge_void=is_bridge,
                                    bridge_span_m=bridge_span,
                                )
                                enclosed_list.append(region)
                            else:
                                if min(span_x, span_y, span_z) <= 0.05:
                                    region = CavityRegion(
                                        cavity_type=CavityType.SLIVER,
                                        bounding_box=cav_aabb,
                                        volume_m3=comp_vol,
                                        voxel_count=len(comp_voxels),
                                        min_x=c_min_x, max_x=c_max_x,
                                        min_y=c_min_y, max_y=c_max_y,
                                        min_z=c_min_z, max_z=c_max_z,
                                    )
                                    sliver_list.append(region)
                                elif comp_vol < smallest_sku_volume:
                                    region = CavityRegion(
                                        cavity_type=CavityType.DEAD_CAVITY,
                                        bounding_box=cav_aabb,
                                        volume_m3=comp_vol,
                                        voxel_count=len(comp_voxels),
                                        min_x=c_min_x, max_x=c_max_x,
                                        min_y=c_min_y, max_y=c_max_y,
                                        min_z=c_min_z, max_z=c_max_z,
                                    )
                                    dead_list.append(region)
                                else:
                                    region = CavityRegion(
                                        cavity_type=CavityType.OPEN_NOTCH,
                                        bounding_box=cav_aabb,
                                        volume_m3=comp_vol,
                                        voxel_count=len(comp_voxels),
                                        min_x=c_min_x, max_x=c_max_x,
                                        min_y=c_min_y, max_y=c_max_y,
                                        min_z=c_min_z, max_z=c_max_z,
                                    )
                                    open_notch_list.append(region)

        total_enclosed_vol = sum(r.volume_m3 for r in enclosed_list)
        total_reachable_vol = sum(r.volume_m3 for r in reachable_list)
        total_open_notch_vol = sum(r.volume_m3 for r in open_notch_list)
        total_dead_vol = sum(r.volume_m3 for r in dead_list)
        total_sliver_vol = sum(r.volume_m3 for r in sliver_list)
        total_future_free_vol = sum(r.volume_m3 for r in future_free_list)

        bridge_count = sum(1 for r in enclosed_list if r.is_bridge_void)
        max_bridge = max([r.bridge_span_m for r in enclosed_list if r.is_bridge_void] or [0.0])

        has_critical = (total_enclosed_vol > max_allowed_enclosed_vol or bridge_count > 0)
        reason = None
        if has_critical:
            reason = (
                f"Cavity Fault: {len(enclosed_list)} enclosed cavities ({total_enclosed_vol:.4f}m3), "
                f"{bridge_count} bridge voids (max span {max_bridge:.3f}m)"
            )

        return ComprehensiveCavityReport(
            total_cavity_count=len(enclosed_list) + len(open_notch_list) + len(dead_list) + len(sliver_list),
            enclosed_cavities=enclosed_list,
            reachable_cavities=reachable_list,
            open_notches=open_notch_list,
            dead_cavities=dead_list,
            slivers=sliver_list,
            future_free_spaces=future_free_list,
            enclosed_volume_m3=round(total_enclosed_vol, 5),
            reachable_volume_m3=round(total_reachable_vol, 5),
            open_notch_volume_m3=round(total_open_notch_vol, 5),
            dead_space_volume_m3=round(total_dead_vol, 5),
            sliver_volume_m3=round(total_sliver_vol, 5),
            future_free_space_volume_m3=round(total_future_free_vol, 5),
            bridge_void_count=bridge_count,
            max_bridge_span_m=round(max_bridge, 3),
            has_critical_enclosed_void=has_critical,
            rejection_reason=reason,
        )
