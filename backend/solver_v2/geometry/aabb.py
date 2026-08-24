"""
3D Axis-Aligned Bounding Box (AABB) and Geometry Kernel for Solver V2.
Canonical coordinate frame:
  x: longitudinal / inner wall -> doors [0, Lx]
  y: lateral / width [0, Ly]
  z: vertical / floor -> roof [0, Lz]
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple
import math

from backend.solver_v2.domain.models import Point3D, BoxDim, Orientation3D, Placement


DEFAULT_GEOM_EPSILON = 1e-6


class ContactType(str, Enum):
    NONE = "NONE"
    PENETRATION = "PENETRATION"
    FACE = "FACE"
    EDGE = "EDGE"
    POINT = "POINT"


@dataclass(frozen=True)
class AABB:
    """
    Axis-Aligned Bounding Box defined by min_pt (min_x, min_y, min_z)
    and max_pt (max_x, max_y, max_z) in meters.
    """
    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float

    def __post_init__(self):
        if self.max_x < self.min_x or self.max_y < self.min_y or self.max_z < self.min_z:
            raise ValueError(
                f"Invalid AABB coordinates: min=({self.min_x}, {self.min_y}, {self.min_z}) > "
                f"max=({self.max_x}, {self.max_y}, {self.max_z})"
            )

    @classmethod
    def from_placement(cls, placement: Placement) -> "AABB":
        return cls(
            min_x=placement.min_x,
            min_y=placement.min_y,
            min_z=placement.min_z,
            max_x=placement.max_x,
            max_y=placement.max_y,
            max_z=placement.max_z,
        )

    @classmethod
    def from_origin_and_dim(cls, origin: Point3D, dim: Orientation3D) -> "AABB":
        return cls(
            min_x=origin.x,
            min_y=origin.y,
            min_z=origin.z,
            max_x=origin.x + dim.dx,
            max_y=origin.y + dim.dy,
            max_z=origin.z + dim.dz,
        )

    @classmethod
    def from_box_dim(cls, origin: Point3D, dim: BoxDim) -> "AABB":
        return cls(
            min_x=origin.x,
            min_y=origin.y,
            min_z=origin.z,
            max_x=origin.x + dim.x,
            max_y=origin.y + dim.y,
            max_z=origin.z + dim.z,
        )

    @property
    def dx(self) -> float:
        return self.max_x - self.min_x

    @property
    def dy(self) -> float:
        return self.max_y - self.min_y

    @property
    def dz(self) -> float:
        return self.max_z - self.min_z

    @property
    def volume(self) -> float:
        return max(0.0, self.dx) * max(0.0, self.dy) * max(0.0, self.dz)

    @property
    def center(self) -> Point3D:
        return Point3D(
            x=0.5 * (self.min_x + self.max_x),
            y=0.5 * (self.min_y + self.max_y),
            z=0.5 * (self.min_z + self.max_z),
        )

    def contains_point(self, pt: Point3D, eps: float = DEFAULT_GEOM_EPSILON) -> bool:
        """Checks if a point is inside or on boundary of AABB."""
        return (
            (self.min_x - eps) <= pt.x <= (self.max_x + eps)
            and (self.min_y - eps) <= pt.y <= (self.max_y + eps)
            and (self.min_z - eps) <= pt.z <= (self.max_z + eps)
        )

    def contains_aabb(self, other: "AABB", eps: float = DEFAULT_GEOM_EPSILON) -> bool:
        """Checks if other AABB is completely inside this AABB."""
        return (
            (other.min_x >= self.min_x - eps)
            and (other.max_x <= self.max_x + eps)
            and (other.min_y >= self.min_y - eps)
            and (other.max_y <= self.max_y + eps)
            and (other.min_z >= self.min_z - eps)
            and (other.max_z <= self.max_z + eps)
        )

    def is_within_bounds(
        self,
        Lx: float,
        Ly: float,
        Lz: float,
        eps: float = DEFAULT_GEOM_EPSILON
    ) -> bool:
        """Checks if this AABB is completely within container boundaries [0, Lx] x [0, Ly] x [0, Lz]."""
        return (
            self.min_x >= -eps
            and self.min_y >= -eps
            and self.min_z >= -eps
            and self.max_x <= Lx + eps
            and self.max_y <= Ly + eps
            and self.max_z <= Lz + eps
        )

    def intersects(self, other: "AABB", eps: float = DEFAULT_GEOM_EPSILON) -> bool:
        """
        True ONLY if there is a strict volumetric penetration (> eps) in all 3 dimensions.
        Face-touching, edge-touching, or point-touching return False (contact, not penetration).
        """
        overlap_x = min(self.max_x, other.max_x) - max(self.min_x, other.min_x)
        overlap_y = min(self.max_y, other.max_y) - max(self.min_y, other.min_y)
        overlap_z = min(self.max_z, other.max_z) - max(self.min_z, other.min_z)

        return (overlap_x > eps) and (overlap_y > eps) and (overlap_z > eps)

    def compute_intersection(self, other: "AABB", eps: float = DEFAULT_GEOM_EPSILON) -> Optional["AABB"]:
        """
        Returns the intersection AABB if there is a volumetric penetration (> eps).
        Otherwise returns None.
        """
        min_x = max(self.min_x, other.min_x)
        max_x = min(self.max_x, other.max_x)
        min_y = max(self.min_y, other.min_y)
        max_y = min(self.max_y, other.max_y)
        min_z = max(self.min_z, other.min_z)
        max_z = min(self.max_z, other.max_z)

        if (max_x - min_x > eps) and (max_y - min_y > eps) and (max_z - min_z > eps):
            return AABB(
                min_x=min_x,
                min_y=min_y,
                min_z=min_z,
                max_x=max_x,
                max_y=max_y,
                max_z=max_z,
            )
        return None

    def penetration_volume(self, other: "AABB", eps: float = DEFAULT_GEOM_EPSILON) -> float:
        """Returns the volumetric penetration in m^3. If no penetration (> eps), returns 0.0."""
        inter = self.compute_intersection(other, eps=eps)
        return inter.volume if inter is not None else 0.0

    def classify_contact(self, other: "AABB", eps: float = DEFAULT_GEOM_EPSILON) -> Tuple[ContactType, float]:
        """
        Classifies geometric contact between self and other:
        - PENETRATION: 3D volume overlap > eps
        - FACE: 2 dimensions have overlap > eps, 1 dimension is touching (within eps)
        - EDGE: 1 dimension has overlap > eps, 2 dimensions are touching (within eps)
        - POINT: all 3 dimensions are touching (within eps)
        - NONE: separated (at least one dimension has gap > eps)

        Returns (ContactType, contact_area_or_volume)
        """
        ox = min(self.max_x, other.max_x) - max(self.min_x, other.min_x)
        oy = min(self.max_y, other.max_y) - max(self.min_y, other.min_y)
        oz = min(self.max_z, other.max_z) - max(self.min_z, other.min_z)

        if ox < -eps or oy < -eps or oz < -eps:
            return ContactType.NONE, 0.0

        if ox > eps and oy > eps and oz > eps:
            return ContactType.PENETRATION, ox * oy * oz

        touching_x = abs(ox) <= eps
        touching_y = abs(oy) <= eps
        touching_z = abs(oz) <= eps

        pos_x = ox > eps
        pos_y = oy > eps
        pos_z = oz > eps

        if touching_x and pos_y and pos_z:
            return ContactType.FACE, oy * oz
        if touching_y and pos_x and pos_z:
            return ContactType.FACE, ox * oz
        if touching_z and pos_x and pos_y:
            return ContactType.FACE, ox * oy

        if pos_x and touching_y and touching_z:
            return ContactType.EDGE, ox
        if pos_y and touching_x and touching_z:
            return ContactType.EDGE, oy
        if pos_z and touching_x and touching_y:
            return ContactType.EDGE, oz

        if touching_x and touching_y and touching_z:
            return ContactType.POINT, 0.0

        return ContactType.NONE, 0.0
