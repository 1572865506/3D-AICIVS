"""
Wall Model, Row/Layer Coherence, and Lifecycle State Machine for Solver V2 (Agent 08 / BLK-003).
Maintains structured Wall representations within Solver State:
- WallState: lifecycle (OPEN, FILLING, CLOSING, CLOSED, REPAIR), spatial bounding, occupancy, flatness.
- RowStructure: horizontal transverse contiguous cargo segments.
- LayerStructure: vertical tier cargo segments.
- DimensionCompatibility: evaluation of dimensional alignment between adjacent boxes.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Tuple, Optional, Dict, Any, Set
import math

from backend.solver_v2.domain.models import ContainerSpec, Placement, Point3D, CargoSKU, BoxDim
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.structure.wall_surface import WallSurfaceMap, WallSurfaceMetrics
from backend.solver_v2.structure.wall_manager import WallSlice


class WallCompletionState(Enum):
    """Lifecycle state of an individual cargo wall."""
    WALL_OPEN = "WALL_OPEN"          # Newly created, initial base rows forming
    WALL_FILLING = "WALL_FILLING"    # Actively accumulating rows & layers
    WALL_CLOSING = "WALL_CLOSING"    # Reaching target depth, smoothing frontier
    WALL_CLOSED = "WALL_CLOSED"      # Formally verified and sealed
    WALL_REPAIR = "WALL_REPAIR"      # Requires localized gap/valley repair before sealing


class CandidateActionType(Enum):
    """Categorized structural intention of candidate placement."""
    START_NEW_WALL = "START_NEW_WALL"
    CONTINUE_ROW = "CONTINUE_ROW"
    COMPLETE_ROW = "COMPLETE_ROW"
    CONTINUE_LAYER = "CONTINUE_LAYER"
    COMPLETE_LAYER = "COMPLETE_LAYER"
    LEVEL_WALL = "LEVEL_WALL"
    FILL_VALLEY = "FILL_VALLEY"
    GAP_FILL = "GAP_FILL"
    TOP_FILL = "TOP_FILL"
    DOOR_SEAL = "DOOR_SEAL"
    ISOLATED = "ISOLATED"


@dataclass
class RowStructure:
    """Represents a continuous horizontal transverse row of cargo along axis Y."""
    row_id: str
    z_level: float
    height: float
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    placements: List[Placement] = field(default_factory=list)
    is_complete: bool = False
    coverage_ratio: float = 0.0

    @property
    def item_count(self) -> int:
        return len(self.placements)


@dataclass
class LayerStructure:
    """Represents a continuous vertical tier / layer of cargo along axis Z."""
    layer_id: str
    z_min: float
    z_max: float
    height: float
    placements: List[Placement] = field(default_factory=list)
    rows: List[RowStructure] = field(default_factory=list)
    is_complete: bool = False
    occupancy_ratio: float = 0.0

    @property
    def item_count(self) -> int:
        return len(self.placements)


@dataclass
class DimensionCompatibility:
    """Evaluates dimensional similarity and alignment compatibility between SKUs/boxes."""
    width_compat: float   # 0.0 to 1.0 (similarity along Y)
    height_compat: float  # 0.0 to 1.0 (similarity along Z)
    depth_compat: float   # 0.0 to 1.0 (similarity along X)
    composite_score: float

    @classmethod
    def evaluate(cls, d1: BoxDim, d2: BoxDim) -> "DimensionCompatibility":
        """Calculates dimensional alignment ratio between two box dimensions."""
        def dim_sim(a: float, b: float) -> float:
            if max(a, b) <= 1e-6:
                return 1.0
            return min(a, b) / max(a, b)

        w_c = dim_sim(d1.y, d2.y)
        h_c = dim_sim(d1.z, d2.z)
        d_c = dim_sim(d1.x, d2.x)

        # Height compatibility is most critical for layer formation, width for row formation
        comp = 0.40 * h_c + 0.35 * w_c + 0.25 * d_c
        return cls(width_compat=round(w_c, 3), height_compat=round(h_c, 3), depth_compat=round(d_c, 3), composite_score=round(comp, 3))


@dataclass
class WallState:
    """
    Authoritative representation of a single physical Cargo Wall within SolverState.
    """
    wall_id: str
    x_start: float
    x_end: float
    width: float
    height: float
    depth: float
    placements: List[Placement] = field(default_factory=list)
    rows: List[RowStructure] = field(default_factory=list)
    layers: List[LayerStructure] = field(default_factory=list)
    surface_map: Optional[WallSurfaceMap] = None
    occupancy_map: Dict[str, float] = field(default_factory=dict)
    frontier_profile: Dict[str, Any] = field(default_factory=dict)
    open_cavities: List[Any] = field(default_factory=list)
    enclosed_cavities: List[Any] = field(default_factory=list)
    support_state: Dict[str, Any] = field(default_factory=dict)
    wall_flatness: float = 1.0
    wall_occupancy: float = 0.0
    max_height_delta: float = 0.0
    completion_state: WallCompletionState = WallCompletionState.WALL_OPEN

    @property
    def item_count(self) -> int:
        return len(self.placements)

    @property
    def volume(self) -> float:
        return sum(p.orientation.volume for p in self.placements)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wall_id": self.wall_id,
            "x_start": round(self.x_start, 4),
            "x_end": round(self.x_end, 4),
            "depth": round(self.depth, 4),
            "width": round(self.width, 4),
            "height": round(self.height, 4),
            "item_count": self.item_count,
            "wall_flatness": round(self.wall_flatness, 4),
            "wall_occupancy": round(self.wall_occupancy, 4),
            "max_height_delta": round(self.max_height_delta, 4),
            "completion_state": self.completion_state.value,
            "row_count": len(self.rows),
            "layer_count": len(self.layers),
            "enclosed_cavities_count": len(self.enclosed_cavities),
            "open_cavities_count": len(self.open_cavities),
        }


@dataclass(frozen=True)
class TopSurfaceCell:
    """Area-bearing cell on a logical wall's upward support surface."""
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    z: float
    area_m2: float
    placement_id: str


@dataclass(frozen=True)
class TopSurface:
    """Credible X-Y support surface reconstructed from carton top faces."""
    resolution_m: float
    cells: Tuple[TopSurfaceCell, ...]
    covered_area_m2: float
    usable_area_m2: float
    mean_z: float
    variance_z: float
    flatness_score: float
    available: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resolution_m": self.resolution_m,
            "cell_count": len(self.cells),
            "covered_area_m2": round(self.covered_area_m2, 5),
            "usable_area_m2": round(self.usable_area_m2, 5),
            "mean_z": round(self.mean_z, 5),
            "variance_z": round(self.variance_z, 6),
            "flatness_score": round(self.flatness_score, 4),
            "available": self.available,
        }


@dataclass
class LogicalWall(WallState):
    """A structural wall assembled from one or more compatible ``WallSlice``s."""
    slices: List[WallSlice] = field(default_factory=list)
    top_surface: Optional[TopSurface] = None
    frontier_surface_area_m2: float = 0.0

    @property
    def frontier_surface(self) -> Optional[WallSurfaceMap]:
        """Compatibility-safe name for the existing authoritative Y-Z surface."""
        return self.surface_map

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data.update({
            "slice_count": len(self.slices),
            "slice_ids": [s.slice_index for s in self.slices],
            "frontier_surface_area_m2": round(self.frontier_surface_area_m2, 5),
            "top_surface": self.top_surface.to_dict() if self.top_surface else None,
        })
        return data


class WallStructureAnalyzer:
    """
    Analyzes, segments, and clusters placements into structured Walls, Rows, and Layers.
    """

    def __init__(self, container: ContainerSpec, geom_epsilon: float = DEFAULT_GEOM_EPSILON):
        self.container = container
        self.geom_epsilon = geom_epsilon

    def extract_walls(
        self,
        placements: List[Placement],
        wall_depth_threshold: float = 0.60,
    ) -> List[LogicalWall]:
        """Return compatibility-preserving logical walls for existing callers."""
        slices = self.extract_wall_slices(placements)
        return self.extract_logical_walls(slices)

    def extract_wall_slices(self, placements: List[Placement]) -> List[WallSlice]:
        """Build atomic slices from cartons sharing the same longitudinal band."""
        if not placements:
            return []
        bands: List[List[Placement]] = []
        band_bounds: List[Tuple[float, float]] = []
        for p in sorted(placements, key=lambda item: (item.min_x, item.max_x, item.min_z, item.min_y)):
            matched = None
            for idx, (x0, x1) in enumerate(band_bounds):
                overlap = min(x1, p.max_x) - max(x0, p.min_x)
                min_depth = min(x1 - x0, p.max_x - p.min_x)
                if abs(p.min_x - x0) <= 0.03 and overlap >= 0.80 * max(min_depth, self.geom_epsilon):
                    matched = idx
                    break
            if matched is None:
                bands.append([p])
                band_bounds.append((p.min_x, p.max_x))
            else:
                bands[matched].append(p)
                x0, x1 = band_bounds[matched]
                band_bounds[matched] = (min(x0, p.min_x), max(x1, p.max_x))

        slices: List[WallSlice] = []
        section_area = self.container.Ly * self.container.Lz
        for idx, group in enumerate(bands):
            x0, x1 = band_bounds[idx]
            surface = WallSurfaceMap(self.container, geom_epsilon=self.geom_epsilon)
            metrics = surface.build_from_placements(group)
            frontier_area = metrics.occupancy_ratio * section_area
            cargo_volume = sum(p.orientation.volume for p in group)
            occupancy = min(1.0, cargo_volume / max((x1 - x0) * section_area, 0.01))
            slices.append(WallSlice(
                slice_index=idx,
                min_x=x0,
                max_x=x1,
                thickness=x1 - x0,
                placements=tuple(group),
                occupancy_ratio=round(occupancy, 4),
                is_complete=occupancy >= 0.75,
                cross_section_area_m2=round(section_area, 5),
                frontier_area_m2=round(frontier_area, 5),
                is_micro_slice=(len(group) <= 3 or frontier_area < 0.12 * section_area),
            ))
        return slices

    def extract_logical_walls(self, slices: List[WallSlice]) -> List[LogicalWall]:
        """Merge only adjacent micro bands with demonstrable Y-Z continuity."""
        if not slices:
            return []
        groups: List[List[WallSlice]] = []
        for wall_slice in sorted(slices, key=lambda s: (s.min_x, s.max_x)):
            if groups and self._should_merge_slices(groups[-1][-1], wall_slice):
                groups[-1].append(wall_slice)
            else:
                groups.append([wall_slice])
        return [
            self._build_wall_state(f"LOGICAL_WALL_{idx:03d}", group)
            for idx, group in enumerate(groups, start=1)
        ]

    def weighted_wall_flatness(self, walls: List[LogicalWall]) -> float:
        """Area-weighted frontier flatness; micro walls cannot dominate the mean."""
        total_area = sum(w.frontier_surface_area_m2 for w in walls)
        if total_area <= self.geom_epsilon:
            return 1.0
        return sum(w.wall_flatness * w.frontier_surface_area_m2 for w in walls) / total_area

    def _should_merge_slices(self, left: WallSlice, right: WallSlice) -> bool:
        gap = right.min_x - left.max_x
        if gap > 0.03 or gap < -0.03:
            return False
        if not (left.is_micro_slice or right.is_micro_slice):
            return False
        left_cells = self._projected_cells(left.placements)
        right_cells = self._projected_cells(right.placements)
        if not left_cells or not right_cells:
            return False
        overlap = len(left_cells & right_cells) / float(min(len(left_cells), len(right_cells)))
        return overlap >= 0.60

    def _projected_cells(self, placements: Tuple[Placement, ...], res: float = 0.1) -> Set[Tuple[int, int]]:
        cells: Set[Tuple[int, int]] = set()
        for p in placements:
            for iy in range(max(0, int(p.min_y // res)), min(int(math.ceil(self.container.Ly / res)), int(math.ceil(p.max_y / res)))):
                for iz in range(max(0, int(p.min_z // res)), min(int(math.ceil(self.container.Lz / res)), int(math.ceil(p.max_z / res)))):
                    cells.add((iy, iz))
        return cells

    def _build_wall_state(self, wall_id: str, slices: List[WallSlice]) -> LogicalWall:
        """Constructs detailed WallState including Row and Layer decomposition."""
        placements = list({p.placement_id: p for s in slices for p in s.placements}.values())
        if not placements:
            return LogicalWall(
                wall_id=wall_id,
                x_start=0.0,
                x_end=0.0,
                width=self.container.Ly,
                height=self.container.Lz,
                depth=0.0,
            )

        x_min = min(p.min_x for p in placements)
        x_max = max(p.max_x for p in placements)
        depth = x_max - x_min
        
        # 1. Identify Layers (clustered by bottom z)
        layers = self._extract_layers(wall_id, placements)

        # 2. Identify Rows (clustered by (z_level, y_position))
        rows = self._extract_rows(wall_id, placements)

        # 3. Wall Flatness & Occupancy
        surface_map = WallSurfaceMap(self.container, geom_epsilon=self.geom_epsilon)
        surface_metrics = surface_map.build_from_placements(placements)

        # Bounding volume
        wall_vol = sum(p.orientation.volume for p in placements)
        bounding_vol = max(0.01, depth * self.container.Ly * self.container.Lz)
        wall_occ = min(1.0, wall_vol / (depth * self.container.Ly * max(p.max_z for p in placements)))

        # Max height delta across transverse cross section
        heights_by_y = [0.0] * surface_map.num_y
        for p in placements:
            iy_start = max(0, int(p.min_y // surface_map.res))
            iy_end = min(surface_map.num_y, int(math.ceil(p.max_y / surface_map.res)))
            for iy in range(iy_start, iy_end):
                heights_by_y[iy] = max(heights_by_y[iy], p.max_z)

        occ_heights = [h for h in heights_by_y if h > 0.0]
        max_h_delta = (max(occ_heights) - min(occ_heights)) if occ_heights else 0.0

        # Completion state evaluation
        comp_state = WallCompletionState.WALL_FILLING
        if surface_metrics.flatness_score >= 0.85 and wall_occ >= 0.70:
            comp_state = WallCompletionState.WALL_CLOSED
        elif surface_metrics.flatness_score < 0.60 or max_h_delta > 0.60:
            comp_state = WallCompletionState.WALL_REPAIR

        frontier_area = surface_metrics.occupancy_ratio * self.container.Ly * self.container.Lz
        top_surface = self._build_top_surface(placements, x_min, x_max)

        return LogicalWall(
            wall_id=wall_id,
            x_start=x_min,
            x_end=x_max,
            width=self.container.Ly,
            height=max(p.max_z for p in placements),
            depth=depth,
            placements=placements,
            rows=rows,
            layers=layers,
            surface_map=surface_map,
            wall_flatness=surface_metrics.flatness_score,
            wall_occupancy=wall_occ,
            max_height_delta=max_h_delta,
            completion_state=comp_state,
            slices=list(slices),
            top_surface=top_surface,
            frontier_surface_area_m2=frontier_area,
        )

    def _build_top_surface(self, placements: List[Placement], x_min: float, x_max: float, res: float = 0.1) -> TopSurface:
        nx = max(1, int(math.ceil((x_max - x_min) / res)))
        ny = max(1, int(math.ceil(self.container.Ly / res)))
        tops: Dict[Tuple[int, int], Tuple[float, Placement]] = {}
        for p in placements:
            ix0 = max(0, int((p.min_x - x_min) // res))
            ix1 = min(nx, int(math.ceil((p.max_x - x_min) / res)))
            iy0 = max(0, int(p.min_y // res))
            iy1 = min(ny, int(math.ceil(p.max_y / res)))
            for ix in range(ix0, ix1):
                for iy in range(iy0, iy1):
                    previous = tops.get((ix, iy))
                    if previous is None or p.max_z > previous[0]:
                        tops[(ix, iy)] = (p.max_z, p)

        cells: List[TopSurfaceCell] = []
        for (ix, iy), (z, p) in tops.items():
            cell_x0 = x_min + ix * res
            cell_x1 = min(x_max, cell_x0 + res)
            cell_y0 = iy * res
            cell_y1 = min(self.container.Ly, cell_y0 + res)
            area = max(0.0, cell_x1 - cell_x0) * max(0.0, cell_y1 - cell_y0)
            cells.append(TopSurfaceCell(cell_x0, cell_x1, cell_y0, cell_y1, z, area, p.placement_id))

        covered = sum(c.area_m2 for c in cells)
        usable_cells = [c for c in cells if c.z < self.container.Lz - self.geom_epsilon]
        usable = sum(c.area_m2 for c in usable_cells)
        if covered > self.geom_epsilon:
            mean_z = sum(c.z * c.area_m2 for c in cells) / covered
            variance = sum(((c.z - mean_z) ** 2) * c.area_m2 for c in cells) / covered
        else:
            mean_z = variance = 0.0
        flatness = 1.0 / (1.0 + 2.0 * math.sqrt(variance))
        return TopSurface(
            resolution_m=res,
            cells=tuple(cells),
            covered_area_m2=covered,
            usable_area_m2=usable,
            mean_z=mean_z,
            variance_z=variance,
            flatness_score=round(flatness, 4),
            available=usable > self.geom_epsilon,
        )

    def _extract_layers(self, wall_id: str, placements: List[Placement]) -> List[LayerStructure]:
        """Groups placements by vertical elevation Z into distinct horizontal layers."""
        z_groups: Dict[int, List[Placement]] = {}
        eps = 0.05

        for p in placements:
            # Discretize z level
            z_key = int(round(p.min_z / eps))
            z_groups.setdefault(z_key, []).append(p)

        layers: List[LayerStructure] = []
        for idx, (z_key, p_list) in enumerate(sorted(z_groups.items())):
            z_min = min(p.min_z for p in p_list)
            z_max = max(p.max_z for p in p_list)
            h = z_max - z_min
            
            # Layer occupancy
            total_area = sum(p.orientation.dx * p.orientation.dy for p in p_list)
            bound_x = max(p.max_x for p in p_list) - min(p.min_x for p in p_list)
            denom = max(0.01, bound_x * self.container.Ly)
            occ = min(1.0, total_area / denom)

            layers.append(
                LayerStructure(
                    layer_id=f"{wall_id}_L{idx+1:02d}",
                    z_min=z_min,
                    z_max=z_max,
                    height=h,
                    placements=p_list,
                    is_complete=occ >= 0.80,
                    occupancy_ratio=round(occ, 3),
                )
            )
        return layers

    def _extract_rows(self, wall_id: str, placements: List[Placement]) -> List[RowStructure]:
        """Groups placements along transverse axis Y at similar height levels into rows."""
        rows: List[RowStructure] = []
        # Group by z_level
        eps_z = 0.05
        z_groups: Dict[int, List[Placement]] = {}
        for p in placements:
            z_key = int(round(p.min_z / eps_z))
            z_groups.setdefault(z_key, []).append(p)

        row_counter = 1
        for z_key, p_list in sorted(z_groups.items()):
            # Sort by min_y
            sorted_by_y = sorted(p_list, key=lambda p: p.min_y)
            z_level = sorted_by_y[0].min_z
            h = max(p.orientation.dz for p in sorted_by_y)

            # Compute transverse coverage
            y_min = sorted_by_y[0].min_y
            y_max = sorted_by_y[-1].max_y
            x_min = min(p.min_x for p in sorted_by_y)
            x_max = max(p.max_x for p in sorted_by_y)

            total_w = sum(p.orientation.dy for p in sorted_by_y)
            cov = min(1.0, total_w / self.container.Ly)

            rows.append(
                RowStructure(
                    row_id=f"{wall_id}_R{row_counter:02d}",
                    z_level=z_level,
                    height=h,
                    x_min=x_min,
                    x_max=x_max,
                    y_min=y_min,
                    y_max=y_max,
                    placements=sorted_by_y,
                    is_complete=(cov >= 0.85 or (y_min <= 0.05 and y_max >= self.container.Ly - 0.05)),
                    coverage_ratio=round(cov, 3),
                )
            )
            row_counter += 1

        return rows
