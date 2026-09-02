"""
Legacy Re-export module for backward compatibility.
All core definitions have migrated to backend.solver_v2.domain.models.
"""
from backend.solver_v2.domain.models import (
    UniversalCargoTensor,
    UniversalZone,
    ContainerDimensions,
    OrientationSpec,
)

__all__ = [
    "UniversalCargoTensor",
    "UniversalZone",
    "ContainerDimensions",
    "OrientationSpec",
]
