"""
Constructive Micro-Placer for Solver V2 (Phase 2).

Converts MacroAllocationResult from CP-SAT into exact 3D coordinates (List[Placement]).
Executes Bottom-Left-Back placement with strict spatial indexing, overlap avoidance,
support ratio check (>= 70%), and weight bearing checks.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Set, Tuple, Any

from backend.solver_v2.domain.models import (
    BoxDim,
    ContainerSpec,
    Orientation3D,
    OrientationSpec,
    Placement,
    PlacementContext,
    Point3D,
    UniversalCargoTensor,
)
from backend.solver_v2.geometry.aabb import AABB
from backend.solver_v2.geometry.spatial_index import SpatialIndex
from backend.solver_v2.solver.cpsat_engine import MacroAllocationResult, StripAllocation


class ConstructivePlacer:
    """
    Constructive Micro-Placer.
    Takes StripAllocations and converts them to precise 3D box placements.
    """

    def __init__(self, container: ContainerSpec):
        self.container = container
        self.cL = round(container.Lx, 4)
        self.cW = round(container.Ly, 4)
        self.cH = round(container.Lz, 4)
        self.door_zone_len = getattr(container, "door_zone_length_m", 1.5)
        self.spatial_index = SpatialIndex(cell_size=0.5)

    def place(
        self,
        allocation: MacroAllocationResult,
        cargo_list: List[UniversalCargoTensor],
        existing_placements: Optional[List[Placement]] = None,
    ) -> List[Placement]:
        """Places items strip by strip, enforcing all physical gates."""
        self.spatial_index.clear()
        self.box_props: Dict[str, Dict[str, Any]] = {}
        placements: List[Placement] = []
        step_idx = 0

        # Register any already existing placements
        if existing_placements:
            for p in existing_placements:
                placements.append(p)
                self.spatial_index.insert(p.placement_id, AABB.from_placement(p), data=p)
                step_idx = max(step_idx, p.step_index + 1)

        cargo_map = {c.sku_id: c for c in cargo_list}
        placed_counts: Dict[str, int] = {c.sku_id: 0 for c in cargo_list}
        for p in placements:
            placed_counts[p.sku_id] = placed_counts.get(p.sku_id, 0) + 1

        sorted_strips = sorted(allocation.strips, key=lambda s: s.x_start)

        for strip in sorted_strips:
            x_cursor = strip.x_start

            # Calculate total width required for items if composite
            items_to_place = []
            for it in strip.items:
                cargo = cargo_map.get(it.sku_id)
                if not cargo:
                    continue
                # Respect required quantities if rigid
                max_allowed = cargo.quantity_required if not cargo.is_elastic else 99999
                rem_needed = max_allowed - placed_counts.get(it.sku_id, 0)
                actual_count = min(it.count, rem_needed)
                if actual_count > 0:
                    items_to_place.append((cargo, it.orientation, actual_count))

            if not items_to_place:
                continue

            # Prioritize rigid items first within composite strip
            items_to_place.sort(key=lambda t: (0 if not t[0].is_elastic else 1, -t[0].weight_kg, -t[0].volume_m3))

            # If homogeneous strip (1 SKU)
            if len(items_to_place) == 1:
                cargo, orig_ori, count = items_to_place[0]
                best_strip_placements: List[Placement] = []
                best_step = step_idx

                # Backtrack & try alternative orientations if primary fails to place required count
                candidate_oris = [orig_ori] + [o for o in cargo.orientations if o.name != orig_ori.name]

                for ori in candidate_oris:
                    trial_placements: List[Placement] = []
                    trial_step = step_idx
                    placed_in_strip = 0

                    row_x = x_cursor
                    max_strip_x = strip.x_start + strip.x_depth
                    while row_x + ori.dx <= min(self.cL, max_strip_x) + 1e-4 and placed_in_strip < count:
                        col_y = 0.0
                        while col_y + ori.dy <= self.cW + 1e-4 and placed_in_strip < count:
                            layer_z = 0.0
                            max_layers = cargo.max_stack_layers or 99
                            if getattr(cargo, "must_be_on_floor", False):
                                max_layers = 1
                            layer_count = 0

                            while (
                                layer_z + ori.dz <= self.cH + 1e-4
                                and layer_count < max_layers
                                and placed_in_strip < count
                            ):
                                cand = {
                                    "x": round(row_x, 4),
                                    "y": round(col_y, 4),
                                    "z": round(layer_z, 4),
                                    "dx": ori.dx,
                                    "dy": ori.dy,
                                    "dz": ori.dz,
                                }
                                if self._pre_check(cand, cargo, placements + trial_placements):
                                    p = self._commit_placement(cand, cargo, ori, trial_step, strip)
                                    trial_placements.append(p)
                                    trial_step += 1
                                    placed_in_strip += 1

                                layer_z = round(layer_z + ori.dz, 4)
                                layer_count += 1

                            col_y = round(col_y + ori.dy, 4)
                        row_x = round(row_x + ori.dx, 4)

                    if len(trial_placements) > len(best_strip_placements):
                        best_strip_placements = trial_placements
                        best_step = trial_step
                        if len(best_strip_placements) >= count:
                            break

                for p in best_strip_placements:
                    placements.append(p)
                    self.spatial_index.insert(p.placement_id, AABB.from_placement(p), data=p)
                    placed_counts[p.sku_id] = placed_counts.get(p.sku_id, 0) + 1
                step_idx = best_step

            else:
                # Composite strip (multiple SKUs side by side along Y)
                curr_y = 0.0
                for cargo, ori, count in items_to_place:
                    placed_for_sku = 0
                    row_x = x_cursor
                    max_strip_x = strip.x_start + strip.x_depth

                    # Width slice for this SKU with floor-only awareness
                    max_stack = 1 if getattr(cargo, "must_be_on_floor", False) else (cargo.max_stack_layers or max(1, int(self.cH / ori.dz)))
                    eff_layers = min(max_stack, max(1, int(self.cH / ori.dz)))
                    eff_rows = max(1, int(round(strip.x_depth / max(1e-4, ori.dx))))
                    cols_y = max(1, math.ceil(count / (eff_layers * eff_rows)))
                    sub_y_limit = min(self.cW, curr_y + cols_y * ori.dy)

                    while row_x + ori.dx <= min(self.cL, max_strip_x) + 1e-4 and placed_for_sku < count:
                        col_y = curr_y
                        while col_y + ori.dy <= sub_y_limit + 1e-4 and placed_for_sku < count:
                            layer_z = 0.0
                            max_layers = 1 if getattr(cargo, "must_be_on_floor", False) else (cargo.max_stack_layers or 99)
                            layer_count = 0

                            while (
                                layer_z + ori.dz <= self.cH + 1e-4
                                and layer_count < max_layers
                                and placed_for_sku < count
                            ):
                                cand = {
                                    "x": round(row_x, 4),
                                    "y": round(col_y, 4),
                                    "z": round(layer_z, 4),
                                    "dx": ori.dx,
                                    "dy": ori.dy,
                                    "dz": ori.dz,
                                }
                                if self._pre_check(cand, cargo, placements):
                                    p = self._commit_placement(cand, cargo, ori, step_idx, strip)
                                    placements.append(p)
                                    self.spatial_index.insert(p.placement_id, AABB.from_placement(p), data=p)
                                    step_idx += 1
                                    placed_for_sku += 1
                                    placed_counts[cargo.sku_id] = placed_counts.get(cargo.sku_id, 0) + 1

                                layer_z = round(layer_z + ori.dz, 4)
                                layer_count += 1

                            col_y = round(col_y + ori.dy, 4)
                        row_x = round(row_x + ori.dx, 4)

                    curr_y = round(curr_y + cols_y * ori.dy, 4)

        return placements

    def _pre_check(self, cand: Dict[str, float], cargo: UniversalCargoTensor, placements: List[Placement]) -> bool:
        """Physical safety pre-check before committing placement."""
        cand_aabb = AABB(
            min_x=cand["x"],
            min_y=cand["y"],
            min_z=cand["z"],
            max_x=cand["x"] + cand["dx"],
            max_y=cand["y"] + cand["dy"],
            max_z=cand["z"] + cand["dz"],
        )

        # 1. Container boundaries
        if (
            cand_aabb.min_x < -1e-4
            or cand_aabb.min_y < -1e-4
            or cand_aabb.min_z < -1e-4
            or cand_aabb.max_x > self.cL + 1e-4
            or cand_aabb.max_y > self.cW + 1e-4
            or cand_aabb.max_z > self.cH + 1e-4
        ):
            return False

        # 2. Collision with existing placements
        if self.spatial_index.query_intersect(cand_aabb, eps=1e-4):
            return False

        # 3. Floor-only rule
        if getattr(cargo, "must_be_on_floor", False) and cand["z"] > 1e-3:
            return False

        # 4. Bottom support ratio (floor layer z < 1e-3 always True)
        if cand["z"] > 1e-3:
            support_ratio = self._calc_support_ratio(cand_aabb)
            if support_ratio < 0.70:
                return False

        # 5. Top-stacking forbidden on supporting boxes
        if cand["z"] > 1e-3:
            if not self._check_top_stacking_allowed(cand_aabb):
                return False

        # 6. Bearing weight check on boxes beneath
        if cand["z"] > 1e-3:
            if not self._check_bearing(cand_aabb, cargo.weight_kg):
                return False

        # 7. Tipping stability check (TIP-03)
        if not self._is_tipping_safe(cand, placements):
            return False

        return True

    def _is_tipping_safe(self, cand: Dict[str, float], placements: List[Placement]) -> bool:
        """Checks longitudinal tipping safety for slender/tall cartons."""
        dx, dz = cand["dx"], cand["dz"]
        if dz <= 1e-6:
            return True

        # Intrinsic safety factor under 0.5g deceleration: SF = 2.0 * dx / dz
        intrinsic_sf = (2.0 * dx) / dz
        if intrinsic_sf >= 1.5 - 1e-4:
            return True

        # Door flush provides rigid forward support
        if cand["x"] + cand["dx"] >= self.cL - 0.04 - 1e-4:
            return True

        # Check forward support from adjacent cartons in +X direction
        target_x = cand["x"] + cand["dx"]
        min_y_ov = 0.20 * cand["dy"]
        min_z_ov = 0.20 * cand["dz"]
        eps = 1e-4

        for other in placements:
            if abs(other.position.x - target_x) <= 0.03:
                y_ov = min(cand["y"] + cand["dy"], other.position.y + other.orientation.dy) - max(cand["y"], other.position.y)
                z_ov = min(cand["z"] + cand["dz"], other.position.z + other.orientation.dz) - max(cand["z"], other.position.z)
                if y_ov >= min_y_ov - eps and z_ov >= min_z_ov - eps:
                    return True

        return False

    def _calc_support_ratio(self, cand_aabb: AABB) -> float:
        """Computes contact area ratio between cand bottom face and lower boxes."""
        bottom_z = cand_aabb.min_z
        cand_area = (cand_aabb.max_x - cand_aabb.min_x) * (cand_aabb.max_y - cand_aabb.min_y)
        if cand_area < 1e-6:
            return 1.0

        query_box = AABB(
            min_x=cand_aabb.min_x,
            min_y=cand_aabb.min_y,
            min_z=bottom_z - 0.05,
            max_x=cand_aabb.max_x,
            max_y=cand_aabb.max_y,
            max_z=bottom_z + 0.005,
        )
        candidate_ids = self.spatial_index.query_candidate_ids(query_box)

        supported_area = 0.0
        for item_id in candidate_ids:
            item = self.spatial_index.get_item(item_id)
            if item and abs(item.aabb.max_z - bottom_z) < 0.005:
                ox = max(0.0, min(cand_aabb.max_x, item.aabb.max_x) - max(cand_aabb.min_x, item.aabb.min_x))
                oy = max(0.0, min(cand_aabb.max_y, item.aabb.max_y) - max(cand_aabb.min_y, item.aabb.min_y))
                supported_area += ox * oy

        return supported_area / cand_area

    def _check_top_stacking_allowed(self, cand_aabb: AABB) -> bool:
        """Verifies that none of the directly supporting boxes forbid top stacking."""
        bottom_z = cand_aabb.min_z
        query_box = AABB(
            min_x=cand_aabb.min_x,
            min_y=cand_aabb.min_y,
            min_z=bottom_z - 0.05,
            max_x=cand_aabb.max_x,
            max_y=cand_aabb.max_y,
            max_z=bottom_z + 0.005,
        )
        candidate_ids = self.spatial_index.query_candidate_ids(query_box)
        for item_id in candidate_ids:
            item = self.spatial_index.get_item(item_id)
            if item and abs(item.aabb.max_z - bottom_z) < 0.005:
                ox = min(cand_aabb.max_x, item.aabb.max_x) - max(cand_aabb.min_x, item.aabb.min_x)
                oy = min(cand_aabb.max_y, item.aabb.max_y) - max(cand_aabb.min_y, item.aabb.min_y)
                if ox > 1e-4 and oy > 1e-4:
                    p: Optional[Placement] = item.data
                    if p:
                        props = self.box_props.get(p.placement_id, {})
                        if props.get("allow_stacking_on_top", True) is False:
                            return False
        return True

    def _check_bearing(self, cand_aabb: AABB, added_weight_kg: float) -> bool:
        """Verifies underlying boxes do not exceed their max bearing weight."""
        bottom_z = cand_aabb.min_z
        query_box = AABB(
            min_x=cand_aabb.min_x,
            min_y=cand_aabb.min_y,
            min_z=bottom_z - 0.05,
            max_x=cand_aabb.max_x,
            max_y=cand_aabb.max_y,
            max_z=bottom_z + 0.005,
        )
        candidate_ids = self.spatial_index.query_candidate_ids(query_box)
        for item_id in candidate_ids:
            item = self.spatial_index.get_item(item_id)
            if item and abs(item.aabb.max_z - bottom_z) < 0.005:
                p: Optional[Placement] = item.data
                if p:
                    props = self.box_props.get(p.placement_id, {})
                    max_bearing = props.get("max_bearing_kg", None)
                    current_bearing = props.get("current_bearing_kg", 0.0)
                    if max_bearing is not None and current_bearing + added_weight_kg > max_bearing:
                        return False
        return True

    def _infer_context(self, cand: Dict[str, float], strip: StripAllocation) -> PlacementContext:
        if cand["x"] >= self.cL - self.door_zone_len:
            return PlacementContext.DOOR_SEAL
        if strip.zone == "INNER" or cand["x"] <= getattr(self.container, "rear_zone_length_m", 1.5):
            return PlacementContext.FOUNDATION
        return PlacementContext.MAIN_WALL

    def _commit_placement(
        self,
        cand: Dict[str, float],
        cargo: UniversalCargoTensor,
        ori: OrientationSpec,
        step_idx: int,
        strip: StripAllocation,
    ) -> Placement:
        context = self._infer_context(cand, strip)
        pid = f"cpsat-{step_idx:04d}"
        p = Placement(
            placement_id=pid,
            instance_id=f"{cargo.sku_id}-{step_idx:04d}",
            sku_id=cargo.sku_id,
            position=Point3D(x=cand["x"], y=cand["y"], z=cand["z"]),
            orientation=Orientation3D(
                dx=ori.dx,
                dy=ori.dy,
                dz=ori.dz,
                name=ori.name,
                is_upright=ori.is_upright,
                is_flat=ori.is_flat,
                is_side=ori.is_side,
            ),
            weight_kg=cargo.weight_kg,
            context=context,
            step_index=step_idx,
        )
        self.box_props[pid] = {
            "allow_stacking_on_top": getattr(cargo, "allow_stacking_on_top", True),
            "max_bearing_kg": getattr(cargo, "max_bearing_kg", None),
            "current_bearing_kg": 0.0,
        }
        return p
