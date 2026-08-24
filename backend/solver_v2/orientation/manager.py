"""
Context-Aware Conditional Orientation Engine for Solver V2 (Agent 04).
Implements context-dependent orientation selection:
- MAIN_BODY / FOUNDATION / MAIN_WALL: strictly / preferentially upright (dz = box.z).
- TOP_FILL / GAP_FILL: conditionally flat (dz = box.y or box.x) when configured and upright cannot fit or in top layer.
- Never use a global static best orientation across all contexts.
"""
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any

from backend.solver_v2.domain.models import (
    BoxDim,
    Orientation3D,
    OrientationPolicy,
    OrientationMode,
    CargoSKU,
    PlacementContext,
)
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON


@dataclass(frozen=True)
class OrientationCandidate:
    """A scored, context-aware concrete orientation for candidate generation."""
    orientation: Orientation3D
    context: PlacementContext
    penalty_score: float
    is_preferred: bool
    description: str

    @property
    def dx(self) -> float:
        return self.orientation.dx

    @property
    def dy(self) -> float:
        return self.orientation.dy

    @property
    def dz(self) -> float:
        return self.orientation.dz


class OrientationEngine:
    """
    Evaluates and generates legal concrete orientations strictly bound to PlacementContext.
    """

    def __init__(self, geom_epsilon: float = DEFAULT_GEOM_EPSILON):
        self.geom_epsilon = geom_epsilon

    def get_candidate_orientations(
        self,
        sku: CargoSKU,
        context: PlacementContext = PlacementContext.GENERAL,
        target_space: Optional[AABB] = None,
        min_support_ratio: Optional[float] = None,
        base_height: Optional[float] = None,
    ) -> List[OrientationCandidate]:
        """
        Generates legal orientation candidates for the given SKU and PlacementContext.
        Filters by target_space bounding box if provided.
        """
        policy = sku.orientation_policy
        base_box = sku.box
        x, y, z = base_box.x, base_box.y, base_box.z
        candidates: List[OrientationCandidate] = []
        eps = self.geom_epsilon

        # 1. Upright Orientations (dz = z)
        upright_rule = policy.rule_for(OrientationMode.UPRIGHT, context)
        if upright_rule and upright_rule.allows(policy.context_region(context), base_height, min_support_ratio):
            # Ori 1: Normal upright (dx=x, dy=y, dz=z)
            ori1 = Orientation3D(dx=x, dy=y, dz=z, name="UPRIGHT_NORMAL", is_upright=True)
            if self._fits_in_space(ori1, target_space):
                candidates.append(
                    OrientationCandidate(
                        orientation=ori1,
                        context=context,
                        penalty_score=0.0,
                        is_preferred=True,
                        description="Preferred upright normal orientation",
                    )
                )

            # Ori 2: Rotated upright (dx=y, dy=x, dz=z)
            if abs(x - y) > eps:
                ori2 = Orientation3D(dx=y, dy=x, dz=z, name="UPRIGHT_ROTATED", is_upright=True)
                if self._fits_in_space(ori2, target_space):
                    candidates.append(
                        OrientationCandidate(
                            orientation=ori2,
                            context=context,
                            penalty_score=0.0,
                            is_preferred=True,
                            description="Preferred upright rotated orientation",
                        )
                    )

        # 2. Conditional Flat Orientations (dz = y or dz = x)
        # Permitted ONLY if policy.allow_flat AND context in allowed_contexts_for_flat
        flat_rule = policy.rule_for(OrientationMode.FLAT, context)
        if flat_rule and flat_rule.allows(policy.context_region(context), base_height, min_support_ratio):
            # Flat XZ: (dx=x, dy=z, dz=y)
            ori3 = Orientation3D(dx=x, dy=z, dz=y, name="FLAT_XZ", is_flat=True, is_upright=False)
            if self._fits_in_space(ori3, target_space):
                candidates.append(
                    OrientationCandidate(
                        orientation=ori3,
                        context=context,
                        penalty_score=policy.flat_orientation_penalty,
                        is_preferred=False,
                        description="Conditional flat orientation (TOP_FILL/GAP_FILL)",
                    )
                )

            # Flat ZX: (dx=z, dy=x, dz=y)
            if abs(x - z) > eps:
                ori4 = Orientation3D(dx=z, dy=x, dz=y, name="FLAT_ZX", is_flat=True, is_upright=False)
                if self._fits_in_space(ori4, target_space):
                    candidates.append(
                        OrientationCandidate(
                            orientation=ori4,
                            context=context,
                            penalty_score=policy.flat_orientation_penalty,
                            is_preferred=False,
                            description="Conditional flat rotated orientation (TOP_FILL/GAP_FILL)",
                        )
                    )

        # 3. Conditional Side Orientations (dz = x)
        side_rule = policy.rule_for(OrientationMode.SIDE, context)
        if side_rule and side_rule.allows(policy.context_region(context), base_height, min_support_ratio):
            # Side YZ: (dx=y, dy=z, dz=x)
            ori5 = Orientation3D(dx=y, dy=z, dz=x, name="SIDE_YZ", is_side=True, is_upright=False)
            if self._fits_in_space(ori5, target_space):
                candidates.append(
                    OrientationCandidate(
                        orientation=ori5,
                        context=context,
                        penalty_score=policy.side_orientation_penalty,
                        is_preferred=False,
                        description="Conditional side orientation",
                    )
                )

            # Side ZY: (dx=z, dy=y, dz=x)
            if abs(y - z) > eps:
                ori6 = Orientation3D(dx=z, dy=y, dz=x, name="SIDE_ZY", is_side=True, is_upright=False)
                if self._fits_in_space(ori6, target_space):
                    candidates.append(
                        OrientationCandidate(
                            orientation=ori6,
                            context=context,
                            penalty_score=policy.side_orientation_penalty,
                            is_preferred=False,
                            description="Conditional side rotated orientation",
                        )
                    )

        # Sort candidates: preferred first (penalty 0), then by lower penalty
        candidates.sort(key=lambda c: (0 if c.is_preferred else 1, c.penalty_score))
        return candidates

    def evaluate_orientation(
        self,
        sku: CargoSKU,
        dx: float,
        dy: float,
        dz: float,
        context: PlacementContext = PlacementContext.GENERAL,
    ) -> Tuple[bool, float, str]:
        """
        Evaluates whether a concrete dimension (dx, dy, dz) is legal in the given context,
        and returns (is_legal, penalty_score, reason).
        """
        policy = sku.orientation_policy
        base_box = sku.box
        bx, by, bz = base_box.x, base_box.y, base_box.z
        eps = self.geom_epsilon

        # Verify permutation
        if sorted([dx, dy, dz]) != sorted([bx, by, bz]) and any(
            abs(p - b) > eps for p, b in zip(sorted([dx, dy, dz]), sorted([bx, by, bz]))
        ):
            return False, 9999.0, f"Dimensions ({dx}, {dy}, {dz}) do not match SKU base box ({bx}, {by}, {bz})"

        is_upright = abs(dz - bz) <= eps
        is_flat = abs(dz - by) <= eps
        is_side = abs(dz - bx) <= eps

        if is_upright:
            if policy.rule_for(OrientationMode.UPRIGHT, context):
                return True, 0.0, "Legal upright orientation"
            return False, 9999.0, "Upright orientation not allowed by policy"

        if is_flat:
            if not policy.rule_for(OrientationMode.FLAT, context):
                return False, 9999.0, "Flat orientation forbidden for this SKU"
            return True, policy.flat_orientation_penalty, "Legal conditional flat orientation"

        if is_side:
            if not policy.rule_for(OrientationMode.SIDE, context):
                return False, 9999.0, "Side orientation forbidden for this SKU"
            return True, policy.side_orientation_penalty, "Legal conditional side orientation"

        return False, 9999.0, "Unrecognized orientation mode"

    def _fits_in_space(self, ori: Orientation3D, target_space: Optional[AABB]) -> bool:
        if target_space is None:
            return True
        eps = self.geom_epsilon
        return (
            ori.dx <= target_space.dx + eps
            and ori.dy <= target_space.dy + eps
            and ori.dz <= target_space.dz + eps
        )
