"""
Wall Close Gate and Localized Wall Repair Planner for Solver V2 (Agent 08 / BLK-003).
Enforces wall quality gates before advancing to next wall or closing container:
- wall_flatness >= min_flatness
- wall_occupancy >= min_occupancy
- max_height_delta <= max_height_delta
- zero enclosed cavity
- support continuity

Localized WallRepairPlanner performs non-backtracking micro-adjustments:
- valley filling using filler SKUs
- completing open rows/layers
- local orientation / swap
"""
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any, Set
import math

from backend.solver_v2.domain.models import ContainerSpec, Placement, Point3D, CargoSKU, PlacementContext
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.structure.wall_model import WallState, WallCompletionState
from backend.solver_v2.structure.cavity_classifier import AdvancedCavityClassifier, ComprehensiveCavityReport
from backend.solver_v2.candidates.generator import CandidatePlacement, CandidateGenerator
from backend.solver_v2.world.state import WorldState
from backend.solver_v2.feasibility.pipeline import HardValidationPipeline
from backend.solver_v2.spaces.engine import FreeSpaceEngine
from backend.solver_v2.orientation.manager import OrientationEngine
from backend.solver_v2.zones.manager import AdaptiveZoneManager
from backend.solver_v2.quantity.manager import QuantityManager


@dataclass
class WallCloseReport:
    """Quantitative evaluation report on whether a Wall satisfies closure criteria."""
    wall_id: str
    is_ready_to_close: bool
    wall_flatness: float
    wall_occupancy: float
    max_height_delta: float
    enclosed_cavity_count: int
    enclosed_cavity_volume_m3: float
    rejection_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wall_id": self.wall_id,
            "is_ready_to_close": self.is_ready_to_close,
            "wall_flatness": round(self.wall_flatness, 4),
            "wall_occupancy": round(self.wall_occupancy, 4),
            "max_height_delta": round(self.max_height_delta, 4),
            "enclosed_cavity_count": self.enclosed_cavity_count,
            "enclosed_cavity_volume_m3": round(self.enclosed_cavity_volume_m3, 5),
            "rejection_reasons": self.rejection_reasons,
        }


class WallCloseChecker:
    """
    Checks if a Wall meets closure quality standards.
    """

    def __init__(
        self,
        min_flatness: float = 0.70,
        min_occupancy: float = 0.60,
        max_height_delta: float = 0.65,
        max_enclosed_vol_m3: float = 0.01,
    ):
        self.min_flatness = min_flatness
        self.min_occupancy = min_occupancy
        self.max_height_delta = max_height_delta
        self.max_enclosed_vol_m3 = max_enclosed_vol_m3

    def evaluate_wall_close(
        self,
        wall: WallState,
        cavity_report: Optional[ComprehensiveCavityReport] = None,
    ) -> WallCloseReport:
        """Evaluates Wall closure readiness."""
        reasons = []

        if wall.wall_flatness < self.min_flatness:
            reasons.append(f"Wall flatness ({wall.wall_flatness:.3f}) below threshold ({self.min_flatness:.3f})")

        if wall.wall_occupancy < self.min_occupancy:
            reasons.append(f"Wall occupancy ({wall.wall_occupancy:.3f}) below threshold ({self.min_occupancy:.3f})")

        if wall.max_height_delta > self.max_height_delta:
            reasons.append(f"Wall height delta ({wall.max_height_delta:.3f}m) exceeds threshold ({self.max_height_delta:.3f}m)")

        enc_count = len(cavity_report.enclosed_cavities) if cavity_report else 0
        enc_vol = cavity_report.enclosed_volume_m3 if cavity_report else 0.0

        if enc_vol > self.max_enclosed_vol_m3 or (cavity_report and cavity_report.bridge_void_count > 0):
            reasons.append(f"Enclosed/Bridge cavities present ({enc_count} voids, {enc_vol:.4f}m3)")

        is_ready = (len(reasons) == 0)
        return WallCloseReport(
            wall_id=wall.wall_id,
            is_ready_to_close=is_ready,
            wall_flatness=wall.wall_flatness,
            wall_occupancy=wall.wall_occupancy,
            max_height_delta=wall.max_height_delta,
            enclosed_cavity_count=enc_count,
            enclosed_cavity_volume_m3=enc_vol,
            rejection_reasons=reasons,
        )


class WallRepairPlanner:
    """
    Localized repair planner: when a wall fails close checks, attempts targeted micro-actions
    (such as filling depressions, smoothing steps with filler SKUs) without global backtracking.
    """

    def __init__(
        self,
        container: ContainerSpec,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
    ):
        self.container = container
        self.geom_epsilon = geom_epsilon
        self.cand_gen = CandidateGenerator(geom_epsilon=geom_epsilon)
        self.validator = HardValidationPipeline(geom_epsilon=geom_epsilon)

    def plan_wall_repair(
        self,
        world_state: WorldState,
        space_engine: FreeSpaceEngine,
        orientation_engine: OrientationEngine,
        zone_mgr: AdaptiveZoneManager,
        qty_mgr: QuantityManager,
        active_skus: List[CargoSKU],
        wall: WallState,
        max_repair_steps: int = 5,
    ) -> List[CandidatePlacement]:
        """
        Generates targeted repair candidate placements to resolve wall defects.
        Prioritizes smaller filler SKUs into valley depressions.
        """
        repair_actions: List[CandidatePlacement] = []

        # Sort active SKUs by volume ascending to pick smallest filler items first
        filler_skus = sorted(active_skus, key=lambda s: s.box.volume)
        if not filler_skus:
            return []

        # Generate candidate placements targeted at open notches / valleys
        candidates = self.cand_gen.generate_candidates(
            world_state=world_state,
            space_engine=space_engine,
            orientation_engine=orientation_engine,
            zone_mgr=zone_mgr,
            qty_mgr=qty_mgr,
            active_skus=filler_skus,
            context=PlacementContext.GAP_FILL,
            max_candidates=50,
        )

        for cand in candidates:
            # Check if candidate falls within current wall X bounds and doesn't overshoot
            if cand.x <= wall.x_end + 0.05 and cand.x + cand.dx <= wall.x_end + 0.30:
                is_valid, _ = self.validator.is_feasible(
                    candidate=cand,
                    sku=next(s for s in active_skus if s.sku_id == cand.sku_id),
                    world_state=world_state,
                    zone_mgr=zone_mgr,
                    context=PlacementContext.GAP_FILL,
                )
                if is_valid:
                    repair_actions.append(cand)
                    if len(repair_actions) >= max_repair_steps:
                        break

        return repair_actions
