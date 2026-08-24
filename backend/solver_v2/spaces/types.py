"""
Types and domain models for Free Space Engine (Solver V2).
Canonical coordinates:
  x: longitudinal / inner wall -> doors [0, Lx]
  y: lateral / width [0, Ly]
  z: vertical / floor -> roof [0, Lz]
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple, List, Dict, Any

from backend.solver_v2.domain.models import Point3D, BoxDim
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON


class SpaceClass(str, Enum):
    """Classification of 3D free space."""
    OPEN_USEFUL = "OPEN_USEFUL"                # Regular, unblocked, fits remaining SKUs
    OPEN_LOW_QUALITY = "OPEN_LOW_QUALITY"      # Open but poor aspect ratio or small
    REACHABLE_CAVITY = "REACHABLE_CAVITY"      # Semi-enclosed recess, but accessible from door
    UNREACHABLE_CAVITY = "UNREACHABLE_CAVITY"  # Enclosed/blocked void, inaccessible from door
    SLIVER = "SLIVER"                          # Narrow slot/gap smaller than minimum cargo dimension
    DEAD_SPACE = "DEAD_SPACE"                  # Free space where no remaining SKU can physically fit


class AnchorCategory(str, Enum):
    """Classification of 3D anchors for balanced candidate generation."""
    FLOOR_FRONTIER = "FLOOR_FRONTIER"          # Floor anchor (z ≈ 0) advancing in X/Y
    SUPPORTED_FRONTIER = "SUPPORTED_FRONTIER"  # Anchor with verified underlying top surface
    WALL_FRONTIER = "WALL_FRONTIER"            # Anchor on active packing wall front (max X / row continuation)
    EMS_CORNER = "EMS_CORNER"                  # EMS lower-left-front corner
    EXTREME_POINT = "EXTREME_POINT"            # Extreme point from geometric projection
    TOP_SURFACE = "TOP_SURFACE"                # Top surface anchor of committed placements
    GAP_FILL = "GAP_FILL"                      # Crevice / local gap anchor
    EXPLORATION = "EXPLORATION"                # Generalized exploration anchor


@dataclass(frozen=True)
class ClassifiedAnchor:
    """
    3D Anchor point annotated with its geometric category and contextual metadata.
    """
    point: Point3D
    category: AnchorCategory
    source_id: Optional[str] = None
    created_step: int = 0
    support_z: float = 0.0
    priority_score: float = 0.0

    @property
    def x(self) -> float:
        return self.point.x

    @property
    def y(self) -> float:
        return self.point.y

    @property
    def z(self) -> float:
        return self.point.z

    def to_tuple(self) -> Tuple[float, float, float]:
        return (self.point.x, self.point.y, self.point.z)


@dataclass(frozen=True)
class ExtremePoint:
    """
    3D Extreme Point / Anchor Point for candidate placement.
    """
    point: Point3D
    source_placement_id: Optional[str] = None
    created_step: int = 0
    bound_x: Optional[float] = None
    bound_y: Optional[float] = None
    bound_z: Optional[float] = None

    @property
    def x(self) -> float:
        return self.point.x

    @property
    def y(self) -> float:
        return self.point.y

    @property
    def z(self) -> float:
        return self.point.z

    def to_tuple(self) -> Tuple[float, float, float]:
        return (self.point.x, self.point.y, self.point.z)


@dataclass(frozen=True)
class FreeSpaceBox:
    """
    Represents a recognized rectangular free space region.
    """
    space_id: str
    aabb: AABB
    space_class: SpaceClass = SpaceClass.OPEN_USEFUL
    is_reachable_from_door: bool = True
    min_opening_dim: Optional[BoxDim] = None
    fit_sku_count: int = 0
    tags: Tuple[str, ...] = ()

    @property
    def volume(self) -> float:
        return self.aabb.volume

    @property
    def dx(self) -> float:
        return self.aabb.dx

    @property
    def dy(self) -> float:
        return self.aabb.dy

    @property
    def dz(self) -> float:
        return self.aabb.dz


@dataclass(frozen=True)
class ResidualSpaceMetrics:
    """
    Authoritative metrics representing the quality of free space remaining after a placement.
    Used by candidate scorers to penalize harmful placements and reward clean space topologies.
    """
    useful_volume: float
    reachable_volume: float
    dead_volume: float
    enclosed_cavity_volume: float
    sliver_volume: float
    fragmentation_score: float
    total_free_volume: float = 0.0
    ems_count: int = 0
    extreme_points_count: int = 0

    def compute_quality_score(
        self,
        useful_weight: float = 1.0,
        reachable_weight: float = 0.5,
        cavity_penalty: float = 2.5,
        sliver_penalty: float = 2.0,
        dead_penalty: float = 1.5,
        fragmentation_penalty: float = 50.0,
    ) -> float:
        """
        Calculates a composite residual space quality score.
        Higher is better.
        """
        score = (
            useful_weight * self.useful_volume
            + reachable_weight * self.reachable_volume
            - cavity_penalty * self.enclosed_cavity_volume
            - sliver_penalty * self.sliver_volume
            - dead_penalty * self.dead_volume
            - fragmentation_penalty * self.fragmentation_score
        )
        return score
