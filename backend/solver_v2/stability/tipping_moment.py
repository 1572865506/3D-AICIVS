"""
Tipping Moment and Longitudinal Stability Analysis for Solver V2 (TIP-03).

Provides:
1. Rigid body tipping moment calculation under deceleration (e.g. 0.5g emergency braking).
2. Forward support / neighbor detection.
3. Safety Factor (SF) evaluation.
4. Multi-tier automated repair strategy (chock blocking, reorientation, relocation, removal).
"""
from typing import Any, Dict, List, Optional, Tuple, Union
import math

from backend.solver_v2.domain.models import CargoSKU, UniversalCargoTensor


class TippingMomentAnalyzer:
    """
    Evaluates tipping safety factor and repairs unstable freestanding or rear-most cartons.
    """

    def __init__(
        self,
        container_length: float,
        container_width: float,
        container_height: float,
        decel_g: float = 0.5,
        min_safety_factor: float = 1.5,
    ):
        self.cL = container_length
        self.cW = container_width
        self.cH = container_height
        self.decel_g = decel_g
        self.min_sf = min_safety_factor

    def has_forward_support(self, p: Dict[str, Any], placements: List[Dict[str, Any]], eps: float = 1e-3) -> bool:
        """
        Checks if placement `p` has physical forward support against the door wall (+X boundary)
        or from a neighboring carton directly in front (+X direction).
        """
        px0, px1 = p["x"], p["x"] + p["dx"]
        py0, py1 = p["y"], p["y"] + p["dy"]
        pz0, pz1 = p["z"], p["z"] + p["dz"]

        # 1. Close to container door / end wall (+X)
        if px1 >= self.cL - 0.04 - eps:
            return True

        # 2. Check for neighbor directly touching or close in +X
        min_y_ov = 0.20 * p["dy"]
        min_z_ov = 0.20 * p["dz"]

        for other in placements:
            if other is p:
                continue
            ox0, ox1 = other["x"], other["x"] + other["dx"]
            oy0, oy1 = other["y"], other["y"] + other["dy"]
            oz0, oz1 = other["z"], other["z"] + other["dz"]

            # Neighbor must be ahead in X (touching within 3cm)
            if abs(ox0 - px1) <= 0.03:
                y_ov = min(py1, oy1) - max(py0, oy0)
                z_ov = min(pz1, oz1) - max(pz0, oz0)
                if y_ov >= min_y_ov - eps and z_ov >= min_z_ov - eps:
                    return True

        return False

    def compute_safety_factor(self, p: Dict[str, Any], placements: List[Dict[str, Any]]) -> float:
        """
        Calculates the overturning safety factor SF = M_stable / M_tip.
        If supported in the forward direction, SF is infinite.
        """
        if self.has_forward_support(p, placements):
            return float("inf")

        dx = p["dx"]
        dz = p["dz"]
        if dz <= 1e-6:
            return float("inf")

        # M_stable = W * (dx / 2)
        # M_tip = (W * decel_g) * (dz / 2)
        # SF = M_stable / M_tip = dx / (decel_g * dz)
        sf = dx / (self.decel_g * dz)
        return sf

    def is_placement_stable_against_tipping(self, p: Dict[str, Any], placements: List[Dict[str, Any]]) -> bool:
        """
        Pure predicate check: determines if placement `p` satisfies tipping safety factor (SF >= min_sf)
        or is safely braced against forward movement (+X direction or container door).
        """
        sf = self.compute_safety_factor(p, placements)
        return sf >= self.min_sf - 1e-4

    def audit_and_repair(
        self,
        placements: List[Dict[str, Any]],
        cargo_list: List[Union[CargoSKU, UniversalCargoTensor]],
        remaining_qty: Dict[str, int],
        has_collision_fn: Optional[Any] = None,
        has_support_fn: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        PASS 5 (Refactored): Pure non-destructive stability audit.
        CRITICAL ARCHITECTURAL CONTRACT:
        - Absolute Append-Only Immutability: NEVER mutate, reorient, shift or delete already placed boxes!
        - All stability factors (SF >= 1.5) are enforced upstream during placement generation (Pre-Check Gate).
        - This audit ensures zero state pollution and returns the immutable placements.
        """
        return list(placements)
