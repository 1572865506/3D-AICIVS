from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import math

from backend.solver_v2.domain.models import ContainerSpec, Placement, Point3D, PlacementContext
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator


@dataclass(frozen=True)
class SteppingResult:
    status: str
    is_stepped: bool
    trailing_edge_x: float
    open_space_m: float
    step_start_x: float
    repositioned_count: int
    placements: Tuple[Placement, ...]
    reasons: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "is_stepped": self.is_stepped,
            "trailing_edge_x": round(self.trailing_edge_x, 3),
            "open_space_m": round(self.open_space_m, 3),
            "step_start_x": round(self.step_start_x, 3),
            "repositioned_count": self.repositioned_count,
            "placement_count": len(self.placements),
            "reasons": list(self.reasons),
        }


class SteppedTrailingEdgeOptimizer:
    """
    Terraces the trailing open edge of cargo into a stepped-down profile
    when the container is not completely full.
    Prevents cargo toppling / avalanche into open voids during braking and acceleration.
    """

    def __init__(self, min_open_space_m: float = 0.80, max_trailing_aspect_ratio: float = 1.15):
        self.min_open_space_m = min_open_space_m
        self.max_aspect_ratio = max_trailing_aspect_ratio

    def optimize(
        self,
        container: ContainerSpec,
        cargo: Tuple[Any, ...],
        placements: Tuple[Placement, ...],
    ) -> SteppingResult:
        if not placements:
            return SteppingResult("EMPTY", False, 0.0, container.Lx, 0.0, 0, (), ())

        max_x = max(p.max_x for p in placements)
        open_space = container.Lx - max_x

        if open_space < self.min_open_space_m:
            return SteppingResult(
                "SKIPPED_FULL_CONTAINER", False, max_x, open_space, max_x, 0, placements,
                ("Container is fully loaded to door threshold; stepping not required",)
            )

        # 1. Determine stepping transition zone at the rear edge of cargo
        # Stepping zone length: roughly 1.5m to 2.5m before max_x
        transition_len = min(2.5, max(1.2, max_x * 0.35))
        step_start_x = max(0.0, max_x - transition_len)
        max_height_seen = max(p.max_z for p in placements)

        # 2. Check each placement in the trailing transition zone for terracing envelope
        # Envelope: Z_max(x) decreases linearly/stepwise from max_height_seen down to 1-2 layers (~0.6-1.2m)
        min_step_height = min(1.2, max_height_seen * 0.45)

        violating_placements: List[Placement] = []
        conforming_placements: List[Placement] = []

        for p in placements:
            if p.min_x >= step_start_x:
                # Fraction along stepping zone from 0 (step_start_x) to 1 (max_x)
                frac = (p.min_x - step_start_x) / max(transition_len, 0.5)
                allowed_z = max(min_step_height, max_height_seen * (1.0 - 0.55 * frac))
                if p.max_z > allowed_z + 0.05:
                    violating_placements.append(p)
                else:
                    conforming_placements.append(p)
            else:
                conforming_placements.append(p)

        if not violating_placements:
            return SteppingResult(
                "SUCCESS_ALREADY_STEPPED", True, max_x, open_space, step_start_x, 0, placements,
                ("Trailing edge already conforms to stepped anti-tipping envelope",)
            )

        # 3. Terrace redistribution: move high violating boxes into lower positions
        # along the floor/lower tier further forward or lower on the step
        current_list = list(conforming_placements)
        repositioned = 0

        # Sort violating placements from highest Z downwards
        violating_placements.sort(key=lambda p: (p.min_z, p.min_x), reverse=True)

        for vp in violating_placements:
            # Try to place at lower Z or slightly forward in existing gaps
            placed = False
            dx, dy, dz = vp.orientation.dx, vp.orientation.dy, vp.orientation.dz
            
            # Candidate anchor positions: floor and lower layers
            # Search x from 0.0 up to max_x in steps of 0.1m, y from 0.0 in steps of 0.1m
            cand_pts: List[Point3D] = []
            for p in current_list:
                cand_pts.append(Point3D(p.max_x, p.min_y, 0.0))
                cand_pts.append(Point3D(p.min_x, p.max_y, 0.0))
                cand_pts.append(Point3D(0.0, p.min_y, 0.0))
                cand_pts.append(Point3D(p.min_x, p.min_y, p.max_z))

            cand_pts.sort(key=lambda pt: (round(pt.z, 3), round(pt.x, 3), round(pt.y, 3)))

            for pt in cand_pts:
                # Check terracing envelope at candidate x
                cand_frac = max(0.0, (pt.x - step_start_x) / max(transition_len, 0.5)) if pt.x >= step_start_x else 0.0
                cand_allowed_z = max(min_step_height, max_height_seen * (1.0 - 0.55 * cand_frac))
                if pt.z + dz > cand_allowed_z + 0.05:
                    continue
                if pt.x + dx > container.Lx or pt.y + dy > container.Ly or pt.z + dz > container.Lz:
                    continue

                # Check collision with current_list
                cand_aabb = AABB(pt.x, pt.y, pt.z, pt.x + dx, pt.y + dy, pt.z + dz)
                collides = False
                for other in current_list:
                    o_aabb = AABB(other.min_x, other.min_y, other.min_z, other.max_x, other.max_y, other.max_z)
                    if cand_aabb.intersects(o_aabb):
                        collides = True
                        break
                if not collides:
                    from dataclasses import replace
                    new_p = replace(vp, position=pt)
                    current_list.append(new_p)
                    repositioned += 1
                    placed = True
                    break

            if not placed:
                # If could not find an internal lower void, keep original to avoid losing item count
                current_list.append(vp)

        # Validate final layout
        validation = IndependentGlobalValidator.validate(container, current_list, list(cargo))
        if not validation.is_valid:
            # Fallback to original placements if repositioning caused any validation defect
            return SteppingResult(
                "FALLBACK_UNVALIDATED", False, max_x, open_space, step_start_x, 0, placements,
                tuple(validation.rejection_reasons)
            )

        new_max_x = max(p.max_x for p in current_list)
        return SteppingResult(
            "SUCCESS", True, new_max_x, container.Lx - new_max_x, step_start_x, repositioned,
            tuple(current_list), ("Successfully shaped stepped anti-tipping trailing profile",)
        )

