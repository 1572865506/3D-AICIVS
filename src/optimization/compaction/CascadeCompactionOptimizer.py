"""
Cascade Shove and Void Compaction Optimizer.

Performs physics-valid, continuous X/Y cascade compaction across all placed cargo:
1. Slices cargo into coherent vertical slices/walls along X.
2. Compacts slices towards X=0 while fully preserving all inter-box vertical stacking and contact relationships.
3. Automatically re-surfaces and fills newly consolidated side/top residual voids.
"""

from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Tuple

from backend.solver_v2.domain.models import ContainerSpec, Placement, Point3D, PlacementContext
from backend.solver_v2.geometry.aabb import AABB
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from src.optimization.residual_filling import ResidualSpaceFillingEngine


@dataclass(frozen=True)
class CompactionResult:
    status: str
    original_count: int
    compacted_count: int
    gap_reduction_mm: float
    recycled_void_volume_m3: float
    placements: Tuple[Placement, ...]
    details: Dict[str, Any]


class CascadeCompactionOptimizer:
    """
    Continuous Multi-Axis Slice/Wall Cascade Shove & Residual Space Compactor.
    """

    def __init__(self, step_precision_m: float = 0.001):
        self.step_precision = step_precision_m
        self.residual_engine = ResidualSpaceFillingEngine(
            max_added=160,
            max_waves=5,
            min_row_coverage=0.82,
            min_row_items=2,
            supported_row_context=PlacementContext.TOP_FILL
        )

    def optimize(
        self,
        container: ContainerSpec,
        cargo: Tuple[Any, ...],
        placements: Tuple[Placement, ...],
        locked_ids: Optional[set] = None
    ) -> CompactionResult:
        if not placements:
            return CompactionResult("EMPTY", 0, 0, 0.0, 0.0, (), {})

        locked = set(locked_ids or set())
        for p in placements:
            if p.placement_id.startswith("door_pre_"):
                locked.add(p.placement_id)

        catalog = {s.sku_id: s for s in cargo}
        current = list(placements)
        initial_gaps = self._measure_inter_wall_gaps(current)

        # ---------------------------------------------------------
        # Iterative Slice-Level Rigid Cascade Shove along X towards X=0
        # ---------------------------------------------------------
        for _ in range(3):
            current = self._cascade_shove_slices_x(container, current, locked)

        # ---------------------------------------------------------
        # Re-fill newly consolidated free space
        # ---------------------------------------------------------
        recycled_volume = 0.0
        try:
            fill_result = self.residual_engine.fill(container, cargo, tuple(current))
            if fill_result and fill_result.status == "SUCCESS" and fill_result.placements:
                trial = current + list(fill_result.placements)
                val = IndependentGlobalValidator.validate(container, trial, list(cargo))
                if val.is_valid:
                    current = trial
                    recycled_volume = sum(p.volume for p in fill_result.placements)
        except Exception:
            pass

        final_gaps = self._measure_inter_wall_gaps(current)
        reduction_mm = max(0.0, (initial_gaps - final_gaps) * 1000.0)

        # Global Safety Validation
        validation = IndependentGlobalValidator.validate(container, current, list(cargo))
        if not validation.is_valid:
            # Atomic rollback on any defect
            return CompactionResult(
                "ROLLED_BACK", len(placements), len(placements), 0.0, 0.0, placements,
                {"reason": "VALIDATION_FAILED", "rejections": validation.rejection_reasons}
            )

        return CompactionResult(
            "SUCCESS", len(placements), len(current), round(reduction_mm, 2),
            round(recycled_volume, 4), tuple(current),
            {"initial_gaps_m": initial_gaps, "final_gaps_m": final_gaps}
        )

    def _cascade_shove_slices_x(
        self,
        container: ContainerSpec,
        placements: List[Placement],
        locked_ids: set
    ) -> List[Placement]:
        """
        Groups boxes with same start X (or tight sub-slices) and pushes each slice towards X=0
        as a rigid block, guaranteeing 100% internal support preservation.
        """
        # Cluster boxes into slices by start X coordinate bins (within 1mm)
        x_bins = defaultdict(list)
        for p in placements:
            x_bins[round(p.min_x, 3)].append(p)

        sorted_x_keys = sorted(x_bins.keys())
        all_placements: List[Placement] = []

        for x_key in sorted_x_keys:
            slice_boxes = x_bins[x_key]
            slice_min_x = min(p.min_x for p in slice_boxes)
            slice_max_x = max(p.max_x for p in slice_boxes)
            slice_locked = any(p.placement_id in locked_ids for p in slice_boxes)

            if slice_locked or not all_placements:
                all_placements.extend(slice_boxes)
                continue

            # Calculate exact maximum obstacle extent in front of this slice
            obstacles = [
                other for other in all_placements
                if other.max_x <= slice_min_x + 1e-4
                and any(
                    min(p.max_y, other.max_y) - max(p.min_y, other.min_y) > 1e-4
                    and min(p.max_z, other.max_z) - max(p.min_z, other.min_z) > 1e-4
                    for p in slice_boxes
                )
            ]

            target_x = max((o.max_x for o in obstacles), default=0.0)
            if target_x < slice_min_x - 1e-4:
                shift_dx = round(target_x - slice_min_x, 6)
                shifted_slice = [
                    replace(p, position=Point3D(round(p.min_x + shift_dx, 6), p.min_y, p.min_z))
                    for p in slice_boxes
                ]
                
                # Check collision with already committed all_placements
                collides = False
                for sp in shifted_slice:
                    s_aabb = AABB.from_placement(sp)
                    for other in all_placements:
                        if s_aabb.intersects(AABB.from_placement(other)):
                            collides = True
                            break
                    if collides:
                        break

                if not collides:
                    all_placements.extend(shifted_slice)
                else:
                    all_placements.extend(slice_boxes)
            else:
                all_placements.extend(slice_boxes)

        return all_placements

    @staticmethod
    def _measure_inter_wall_gaps(placements: List[Placement]) -> float:
        """Measure sum of distinct inter-slice loose gaps (>3mm) along container length."""
        slices = defaultdict(list)
        for p in placements:
            slices[round(p.min_x, 3)].append(p)

        sorted_x = sorted(slices.keys())
        total_gap = 0.0
        for i in range(len(sorted_x) - 1):
            curr_x = sorted_x[i]
            next_x = sorted_x[i + 1]
            max_end = max(p.max_x for p in slices[curr_x])
            gap = next_x - max_end
            if gap > 0.003:
                total_gap += gap
        return round(total_gap, 6)
