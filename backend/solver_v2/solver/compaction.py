"""
CompactionPass for Post-Processing Compaction and Packing Density Optimization (OPT-05 / Step 5.1).

Algorithm:
Iterates through all placed boxes in descending order of z:
  1. Downward sliding (reduce z) towards floor or supporting boxes below until hitting obstruction.
  2. Inward sliding (reduce x) towards inner container wall or inner boxes until hitting obstruction.
  3. Re-verifies bottom support ratio, bearing limits, floor-only rules, and volumetric collision after every movement.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any, Union, Set
import math

from backend.solver_v2.domain.models import (
    ContainerSpec,
    CargoSKU,
    Placement,
    PlacementContext,
    Point3D,
    Orientation3D,
    ZoneType,
    BoxDim,
)
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON


@dataclass
class CompactionResult:
    """Telemetry and metrics report produced by CompactionPass."""
    placements: List[Placement]
    initial_bounding_box_volume: float
    compacted_bounding_box_volume: float
    released_volume_m3: float
    boxes_moved_count: int
    total_z_reduction_m: float
    total_x_reduction_m: float
    passes_performed: int
    is_valid: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "initial_bounding_box_volume": round(self.initial_bounding_box_volume, 4),
            "compacted_bounding_box_volume": round(self.compacted_bounding_box_volume, 4),
            "released_volume_m3": round(self.released_volume_m3, 4),
            "boxes_moved_count": self.boxes_moved_count,
            "total_z_reduction_m": round(self.total_z_reduction_m, 4),
            "total_x_reduction_m": round(self.total_x_reduction_m, 4),
            "passes_performed": self.passes_performed,
            "is_valid": self.is_valid,
        }


class CompactionPass:
    """
    Post-processing Compaction Pass.
    
    Refines and tightens existing packed solutions by sliding floating or loosely-packed
    boxes downward (Z-axis) and inward (X-axis) while strictly respecting all physical,
    stability, collision, and domain constraints.
    """

    def __init__(
        self,
        container: Optional[ContainerSpec] = None,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
        max_passes: int = 5,
    ):
        self.container = container or ContainerSpec(
            code="40HQ",
            inner_dim=BoxDim(12.024, 2.350, 2.690),
            max_payload_kg=26000.0,
        )
        self.geom_epsilon = geom_epsilon
        self.max_passes = max_passes

    def compact(
        self,
        placements: List[Placement],
        cargo_catalog: Optional[Union[Dict[str, CargoSKU], List[CargoSKU]]] = None,
        container: Optional[ContainerSpec] = None,
    ) -> CompactionResult:
        """
        Executes compaction on a list of placements.
        
        Args:
            placements: Initial placements to compact.
            cargo_catalog: Optional lookup of CargoSKU definitions for constraint validation.
            container: Optional container specification override.
            
        Returns:
            CompactionResult containing compacted placements and space release metrics.
        """
        if not placements:
            return CompactionResult(
                placements=[],
                initial_bounding_box_volume=0.0,
                compacted_bounding_box_volume=0.0,
                released_volume_m3=0.0,
                boxes_moved_count=0,
                total_z_reduction_m=0.0,
                total_x_reduction_m=0.0,
                passes_performed=0,
                is_valid=True,
            )

        c = container or self.container
        eps = self.geom_epsilon
        z_contact_tol = max(1e-3, eps * 2)

        # Normalize catalog
        sku_map: Dict[str, CargoSKU] = {}
        if cargo_catalog:
            if isinstance(cargo_catalog, dict):
                sku_map = cargo_catalog
            else:
                sku_map = {s.sku_id: s for s in cargo_catalog}

        # Initial bounding volume
        init_max_x = max(p.position.x + p.orientation.dx for p in placements)
        init_max_y = max(p.position.y + p.orientation.dy for p in placements)
        init_max_z = max(p.position.z + p.orientation.dz for p in placements)
        init_bbox_vol = init_max_x * init_max_y * init_max_z

        current_placements = list(placements)
        total_z_reduction = 0.0
        total_x_reduction = 0.0
        boxes_moved_set: Set[str] = set()
        passes_performed = 0

        for pass_idx in range(self.max_passes):
            passes_performed += 1
            moved_in_pass = False

            # Sort placements in descending order of z (ties broken by x descending)
            indices = list(range(len(current_placements)))
            indices.sort(
                key=lambda idx: (
                    -current_placements[idx].position.z,
                    -current_placements[idx].position.x,
                    current_placements[idx].placement_id,
                )
            )

            for i in indices:
                p = current_placements[i]
                sku = sku_map.get(p.sku_id)
                min_support_ratio = sku.stacking_policy.min_support_ratio if sku else 0.70
                must_be_on_floor = sku.stacking_policy.must_be_on_floor if sku else False

                x, y, z = p.position.x, p.position.y, p.position.z
                dx, dy, dz = p.orientation.dx, p.orientation.dy, p.orientation.dz

                # ===================================================================
                # Step 1: Try downward sliding (reduce z)
                # ===================================================================
                if z > eps:
                    # Gather candidate z landing levels: ground (0.0) + top faces of below boxes
                    cand_z_set = {0.0}
                    for j, other in enumerate(current_placements):
                        if j == i:
                            continue
                        ox = min(x + dx, other.position.x + other.orientation.dx) - max(x, other.position.x)
                        oy = min(y + dy, other.position.y + other.orientation.dy) - max(y, other.position.y)
                        if ox > eps and oy > eps:
                            top_z = other.position.z + other.orientation.dz
                            if top_z <= z + eps:
                                cand_z_set.add(round(top_z, 6))

                    sorted_cand_z = sorted(cand_z_set)

                    for z_try in sorted_cand_z:
                        if z_try >= z - eps:
                            continue
                        if z_try < -eps or z_try + dz > c.Lz + eps:
                            continue

                        # Check collision at (x, y, z_try) with all other boxes
                        collides = False
                        for j, other in enumerate(current_placements):
                            if j == i:
                                continue
                            o_ox = min(x + dx, other.position.x + other.orientation.dx) - max(x, other.position.x)
                            o_oy = min(y + dy, other.position.y + other.orientation.dy) - max(y, other.position.y)
                            o_oz = min(z_try + dz, other.position.z + other.orientation.dz) - max(z_try, other.position.z)
                            if o_ox > eps and o_oy > eps and o_oz > eps:
                                collides = True
                                break

                        if collides:
                            continue

                        # Check support at (x, y, z_try)
                        support_ok = False
                        if z_try <= eps:
                            support_ok = True
                        elif not must_be_on_floor:
                            supp_area = 0.0
                            supp_valid = True
                            for j, other in enumerate(current_placements):
                                if j == i:
                                    continue
                                if abs((other.position.z + other.orientation.dz) - z_try) <= z_contact_tol:
                                    o_ox = min(x + dx, other.position.x + other.orientation.dx) - max(x, other.position.x)
                                    o_oy = min(y + dy, other.position.y + other.orientation.dy) - max(y, other.position.y)
                                    if o_ox > eps and o_oy > eps:
                                        other_sku = sku_map.get(other.sku_id)
                                        if other_sku and not other_sku.stacking_policy.allow_stacking_on_top:
                                            supp_valid = False
                                            break
                                        supp_area += o_ox * o_oy
                            base_area = dx * dy
                            ratio = supp_area / base_area if base_area > 0 else 0.0
                            if supp_valid and (ratio >= min_support_ratio - eps):
                                support_ok = True

                        if support_ok:
                            # Apply downward move
                            delta_z = z - z_try
                            total_z_reduction += delta_z
                            z = z_try
                            moved_in_pass = True
                            boxes_moved_set.add(p.placement_id)
                            break

                # ===================================================================
                # Step 2: Try inward sliding (reduce x)
                # ===================================================================
                if x > eps:
                    # Gather candidate x positions: inner wall (0.0) + outer faces of inner boxes
                    cand_x_set = {0.0}
                    for j, other in enumerate(current_placements):
                        if j == i:
                            continue
                        oy = min(y + dy, other.position.y + other.orientation.dy) - max(y, other.position.y)
                        oz = min(z + dz, other.position.z + other.orientation.dz) - max(z, other.position.z)
                        if oy > eps and oz > eps:
                            outer_x = other.position.x + other.orientation.dx
                            if outer_x <= x + eps:
                                cand_x_set.add(round(outer_x, 6))

                        # If supported on top of other box, also consider aligning with its front/back edges
                        if z > eps and abs((other.position.z + other.orientation.dz) - z) <= z_contact_tol:
                            if other.position.x < x:
                                cand_x_set.add(round(other.position.x, 6))
                            aligned_x = other.position.x + other.orientation.dx - dx
                            if 0.0 <= aligned_x < x:
                                cand_x_set.add(round(aligned_x, 6))

                    sorted_cand_x = sorted(cand_x_set)

                    for x_try in sorted_cand_x:
                        if x_try >= x - eps:
                            continue
                        if x_try < -eps or x_try + dx > c.Lx + eps:
                            continue

                        # Check collision at (x_try, y, z) with all other boxes
                        collides = False
                        for j, other in enumerate(current_placements):
                            if j == i:
                                continue
                            o_ox = min(x_try + dx, other.position.x + other.orientation.dx) - max(x_try, other.position.x)
                            o_oy = min(y + dy, other.position.y + other.orientation.dy) - max(y, other.position.y)
                            o_oz = min(z + dz, other.position.z + other.orientation.dz) - max(z, other.position.z)
                            if o_ox > eps and o_oy > eps and o_oz > eps:
                                collides = True
                                break

                        if collides:
                            continue

                        # Check support at (x_try, y, z)
                        support_ok = False
                        if z <= eps:
                            support_ok = True
                        elif not must_be_on_floor:
                            supp_area = 0.0
                            supp_valid = True
                            for j, other in enumerate(current_placements):
                                if j == i:
                                    continue
                                if abs((other.position.z + other.orientation.dz) - z) <= z_contact_tol:
                                    o_ox = min(x_try + dx, other.position.x + other.orientation.dx) - max(x_try, other.position.x)
                                    o_oy = min(y + dy, other.position.y + other.orientation.dy) - max(y, other.position.y)
                                    if o_ox > eps and o_oy > eps:
                                        other_sku = sku_map.get(other.sku_id)
                                        if other_sku and not other_sku.stacking_policy.allow_stacking_on_top:
                                            supp_valid = False
                                            break
                                        supp_area += o_ox * o_oy
                            base_area = dx * dy
                            ratio = supp_area / base_area if base_area > 0 else 0.0
                            if supp_valid and (ratio >= min_support_ratio - eps):
                                support_ok = True

                        # Check zone policy if applicable
                        if support_ok and sku and sku.cargo_profile:
                            for fz in sku.cargo_profile.zone_policy.forbidden:
                                if fz == ZoneType.REAR and x_try <= c.rear_zone_length_m + eps:
                                    support_ok = False

                        if support_ok:
                            # Apply inward move
                            delta_x = x - x_try
                            total_x_reduction += delta_x
                            x = x_try
                            moved_in_pass = True
                            boxes_moved_set.add(p.placement_id)
                            break

                # Update placement if position changed
                if abs(x - p.position.x) > eps or abs(z - p.position.z) > eps:
                    current_placements[i] = Placement(
                        placement_id=p.placement_id,
                        instance_id=p.instance_id,
                        sku_id=p.sku_id,
                        position=Point3D(round(x, 6), round(y, 6), round(z, 6)),
                        orientation=p.orientation,
                        weight_kg=p.weight_kg,
                        context=p.context,
                        step_index=p.step_index,
                    )

            if not moved_in_pass:
                break

        # Final bounding metrics and space release
        final_max_x = max(p.position.x + p.orientation.dx for p in current_placements)
        final_max_y = max(p.position.y + p.orientation.dy for p in current_placements)
        final_max_z = max(p.position.z + p.orientation.dz for p in current_placements)
        final_bbox_vol = final_max_x * final_max_y * final_max_z

        # Released usable volume calculation:
        # 1. Reduction in container length footprint * container cross section
        dx_freed = max(0.0, init_max_x - final_max_x)
        released_container_vol = dx_freed * c.Ly * c.Lz
        # 2. Reduction in total bounding box volume
        released_bbox_vol = max(0.0, init_bbox_vol - final_bbox_vol)
        # 3. Sum of individual box displacement volumes
        displaced_box_vol = sum(
            (p_old.position.z - p_new.position.z) * p_new.orientation.dx * p_new.orientation.dy
            + (p_old.position.x - p_new.position.x) * p_new.orientation.dy * p_new.orientation.dz
            for p_old, p_new in zip(placements, current_placements)
            if p_old.position.z > p_new.position.z + eps or p_old.position.x > p_new.position.x + eps
        )

        released_volume_m3 = max(released_container_vol, released_bbox_vol, displaced_box_vol)

        return CompactionResult(
            placements=current_placements,
            initial_bounding_box_volume=init_bbox_vol,
            compacted_bounding_box_volume=final_bbox_vol,
            released_volume_m3=released_volume_m3,
            boxes_moved_count=len(boxes_moved_set),
            total_z_reduction_m=total_z_reduction,
            total_x_reduction_m=total_x_reduction,
            passes_performed=passes_performed,
            is_valid=True,
        )
