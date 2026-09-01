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
from backend.solver_v2.structure.cavity_classifier import (
    AdvancedCavityClassifier,
    DEFAULT_VOXEL_RES_M,
    DEFAULT_MAX_ENCLOSED_VOID_VOL_M3
)


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
    thickness: float = 0.0
    placements: Tuple[Placement, ...] = ()
    occupancy_ratio: float = 0.0
    is_complete: bool = False
    cross_section_area_m2: float = 0.0
    frontier_area_m2: float = 0.0
    is_micro_slice: bool = False
    thickness_m: float = 0.0
    occupied_volume_m3: float = 0.0
    void_volume_m3: float = 0.0
    density: float = 0.0


class CavityVoidDetector:
    """
    Bad Case 001 regression avoidance detector.
    Detects internal enclosed hollow cavities surrounded by cargo walls/container boundaries.
    Standardized on AdvancedCavityClassifier multi-tier voxel engine.
    """

    def __init__(
        self,
        container: ContainerSpec,
        voxel_res_m: float = DEFAULT_VOXEL_RES_M,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
    ):
        self.container = container
        self.res = voxel_res_m
        self.geom_epsilon = geom_epsilon
        self.classifier = AdvancedCavityClassifier(
            container=container,
            voxel_res_m=voxel_res_m,
            geom_epsilon=geom_epsilon,
        )

    def detect_enclosed_voids(
        self,
        placements: List[Placement],
        max_allowed_void_vol_m3: float = DEFAULT_MAX_ENCLOSED_VOID_VOL_M3,
    ) -> EnclosedVoidReport:
        """
        Runs 3D flood-fill reachability analysis to identify any enclosed, unreachable hollow voids
        behind the loading frontier.
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

        report = self.classifier.classify_cavities(
            placements=placements,
            max_allowed_enclosed_vol=max_allowed_void_vol_m3,
        )

        enclosed = report.enclosed_cavities
        total_vol = report.enclosed_volume_m3
        max_single_vol = max((c.volume_m3 for c in enclosed), default=0.0)
        has_voids = (total_vol > max_allowed_void_vol_m3) or bool(enclosed)

        penalty = 0.0
        rejection_reason = None
        if has_voids:
            penalty = 100.0 + total_vol * 500.0
            rejection_reason = (
                f"Bad Case 001 Violation: Enclosed hollow voids detected ({len(enclosed)} regions, "
                f"total volume {total_vol:.4f} m³ > max allowed {max_allowed_void_vol_m3:.4f} m³)"
            )

        return EnclosedVoidReport(
            has_enclosed_voids=has_voids,
            void_count=len(enclosed),
            total_void_volume_m3=round(total_vol, 5),
            max_single_void_volume_m3=round(max_single_vol, 5),
            enclosed_void_penalty=round(penalty, 2),
            rejection_reason=rejection_reason,
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
