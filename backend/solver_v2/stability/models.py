"""
Stability Domain Models for Solver V2 (Agent 07).
Defines stability states, metrics, and report structures for:
- Item-level stability
- Cluster-level stability
- Wall-level stability
- Stability Debt tracking
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Tuple, Optional, Set, Any

from backend.solver_v2.domain.models import Point3D


class StabilityState(str, Enum):
    SELF_STABLE = "SELF_STABLE"                   # Fully stable independently
    SUPPORTED_STABLE = "SUPPORTED_STABLE"         # Stable via support + lateral bracing
    CONDITIONALLY_STABLE = "CONDITIONALLY_STABLE" # Committed under temporary bounded debt
    WARNING = "WARNING"                           # Marginally stable, high slenderness
    UNSTABLE = "UNSTABLE"                         # Unstable: tipping risk or unsupported


@dataclass
class ItemStabilityReport:
    """Detailed stability evaluation for an individual cargo placement."""
    placement_id: str
    sku_id: str
    stability_state: StabilityState
    support_ratio: float
    com_projection_in_base: bool
    edge_margin_m: float           # Distance from COM to nearest support polygon boundary (positive = inside)
    max_overhang_m: float          # Cantilever distance beyond supporting base
    slenderness: float             # Height / min(width, length)
    has_lateral_bracing: bool
    lateral_contact_count: int
    is_stable: bool                # True if SELF_STABLE or SUPPORTED_STABLE
    reasons: List[str] = field(default_factory=list)


@dataclass
class ClusterStabilityReport:
    """Stability evaluation for an interconnected cargo cluster."""
    cluster_id: str
    placement_ids: List[str]
    total_weight_kg: float
    combined_com: Point3D
    floor_support_area: float
    com_in_floor_base: bool
    lateral_interlock_score: float  # 0.0 to 1.0 based on seam overlap and interlocking
    stability_state: StabilityState
    is_stable: bool = True
    reasons: List[str] = field(default_factory=list)


@dataclass
class WallStabilityReport:
    """Stability evaluation for a transverse wall column/slice along the X axis."""
    wall_id: str
    x_slice_range: Tuple[float, float]
    placement_ids: List[str]
    total_weight_kg: float
    wall_com: Point3D
    height_to_thickness_ratio: float  # Wall Height / Wall Thickness along X
    tipping_moment_ratio: float       # Restoring Moment / Overturning Moment under 0.5g decel
    rear_wall_braced: bool            # True if backed by inner container wall or previous wall
    stability_state: StabilityState
    is_stable: bool = True
    reasons: List[str] = field(default_factory=list)


@dataclass
class StabilityDebtItem:
    """Record of a conditionally stable placement committed under temporary debt."""
    placement_id: str
    sku_id: str
    step_committed: int
    cause: str
    required_resolution: str
    is_resolved: bool = False
    resolved_step: Optional[int] = None
    resolved_by_placement_id: Optional[str] = None
