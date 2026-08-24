"""
Geometry Package for Solver V2.
"""
from backend.solver_v2.geometry.aabb import (
    AABB,
    ContactType,
    DEFAULT_GEOM_EPSILON,
)
from backend.solver_v2.geometry.spatial_index import (
    SpatialIndex,
    SpatialItem,
)
from backend.solver_v2.geometry.overlap import (
    OverlapDetector,
    OverlapReport,
)

__all__ = [
    "AABB",
    "ContactType",
    "DEFAULT_GEOM_EPSILON",
    "SpatialIndex",
    "SpatialItem",
    "OverlapDetector",
    "OverlapReport",
]
