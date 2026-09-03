"""
Composite Strip Builder for Solver V2 (OPT-01).

Core concept:
Enables multiple heterogeneous SKUs to stitch together along the container width (Y-axis)
within a given wall slice thickness (delta_x), maximizing lateral coverage from ~80% to ~92%+.
Computes stepped top surface profiles and headroom relay zones for vertical adaptation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from backend.solver_v2.domain.models import (
    BoxDim,
    CargoSKU,
    Orientation3D,
    OrientationSpec,
    Placement,
    PlacementContext,
    Point3D,
    UniversalCargoTensor,
)
from backend.solver_v2.geometry.aabb import DEFAULT_GEOM_EPSILON


@dataclass(frozen=True)
class SubColumnConfig:
    """Configuration for a single sub-column within a composite strip."""
    sku_id: str
    sku_name: str
    orientation_name: str
    dx: float
    dy: float
    dz: float
    nx: int
    ny: int
    nz: int
    total_cartons: int
    y_offset: float
    column_width: float
    column_depth: float
    column_height: float
    headroom: float
    weight_kg: float
    total_weight_kg: float
    tag: str = "MAIN_WALL"
    context: PlacementContext = PlacementContext.MAIN_WALL

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sku_id": self.sku_id,
            "sku_name": self.sku_name,
            "orientation_name": self.orientation_name,
            "dx": round(self.dx, 4),
            "dy": round(self.dy, 4),
            "dz": round(self.dz, 4),
            "nx": self.nx,
            "ny": self.ny,
            "nz": self.nz,
            "total_cartons": self.total_cartons,
            "y_offset": round(self.y_offset, 4),
            "column_width": round(self.column_width, 4),
            "column_depth": round(self.column_depth, 4),
            "column_height": round(self.column_height, 4),
            "headroom": round(self.headroom, 4),
            "weight_kg": round(self.weight_kg, 2),
            "total_weight_kg": round(self.total_weight_kg, 2),
            "tag": self.tag,
            "context": self.context.value if isinstance(self.context, PlacementContext) else str(self.context),
        }


@dataclass
class CompositeStripResult:
    """The constructed multi-SKU composite strip configuration."""
    columns: List[SubColumnConfig] = field(default_factory=list)
    total_width: float = 0.0
    target_width: float = 0.0
    y_coverage_ratio: float = 0.0
    delta_x: float = 0.0
    available_height: float = 0.0
    total_cartons: int = 0
    total_volume: float = 0.0
    total_weight_kg: float = 0.0
    stepped_heights: List[Tuple[float, float, float]] = field(default_factory=list)  # (y_start, y_end, height)
    headroom_profiles: List[Tuple[float, float, float]] = field(default_factory=list)  # (y_start, y_end, headroom)
    sku_counts: Dict[str, int] = field(default_factory=dict)
    is_valid: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_width": round(self.total_width, 4),
            "target_width": round(self.target_width, 4),
            "y_coverage_ratio": round(self.y_coverage_ratio, 4),
            "delta_x": round(self.delta_x, 4),
            "available_height": round(self.available_height, 4),
            "total_cartons": self.total_cartons,
            "total_volume": round(self.total_volume, 4),
            "total_weight_kg": round(self.total_weight_kg, 2),
            "stepped_heights": [
                [round(y0, 4), round(y1, 4), round(h, 4)]
                for y0, y1, h in self.stepped_heights
            ],
            "headroom_profiles": [
                [round(y0, 4), round(y1, 4), round(hr, 4)]
                for y0, y1, hr in self.headroom_profiles
            ],
            "sku_counts": dict(self.sku_counts),
            "columns": [c.to_dict() for c in self.columns],
            "is_valid": self.is_valid,
        }

    def instantiate_placements(
        self,
        start_x: float,
        start_y: float = 0.0,
        start_z: float = 0.0,
        step_offset: int = 0,
        placement_id_prefix: str = "plc",
    ) -> List[Placement]:
        """Instantiate concrete domain Placement objects for all items in the strip."""
        placements: List[Placement] = []
        step = step_offset
        for col in self.columns:
            for lz in range(col.nz):
                for rx in range(col.nx):
                    for cy in range(col.ny):
                        pos = Point3D(
                            x=round(start_x + rx * col.dx, 4),
                            y=round(start_y + col.y_offset + cy * col.dy, 4),
                            z=round(start_z + lz * col.dz, 4),
                        )
                        ori = Orientation3D(
                            dx=round(col.dx, 4),
                            dy=round(col.dy, 4),
                            dz=round(col.dz, 4),
                            name=col.orientation_name,
                            is_upright="UPRIGHT" in col.orientation_name,
                            is_flat="FLAT" in col.orientation_name,
                            is_side="SIDE" in col.orientation_name,
                        )
                        pid = f"{placement_id_prefix}_{step}_{col.sku_id}"
                        inst_id = f"inst_{col.sku_id}_{step}"
                        placements.append(
                            Placement(
                                placement_id=pid,
                                instance_id=inst_id,
                                sku_id=col.sku_id,
                                position=pos,
                                orientation=ori,
                                weight_kg=col.weight_kg,
                                context=col.context,
                                step_index=step,
                            )
                        )
                        step += 1
        return placements

    def instantiate_raw_dict(
        self,
        start_x: float,
        start_y: float = 0.0,
        start_z: float = 0.0,
        step_offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Instantiate dictionary format placements compatible with UnifiedSolver."""
        raw_list: List[Dict[str, Any]] = []
        step = step_offset
        for col in self.columns:
            for lz in range(col.nz):
                for rx in range(col.nx):
                    for cy in range(col.ny):
                        raw_list.append({
                            "sku_id": col.sku_id,
                            "x": round(start_x + rx * col.dx, 4),
                            "y": round(start_y + col.y_offset + cy * col.dy, 4),
                            "z": round(start_z + lz * col.dz, 4),
                            "dx": round(col.dx, 4),
                            "dy": round(col.dy, 4),
                            "dz": round(col.dz, 4),
                            "weight_kg": col.weight_kg,
                            "orientation": col.orientation_name,
                            "step": step,
                            "tag": col.tag,
                            "context": col.context.value if isinstance(col.context, PlacementContext) else str(col.context),
                        })
                        step += 1
        return raw_list


@dataclass(frozen=True)
class _CandidateOrientationOption:
    sku_id: str
    sku_name: str
    weight_kg: float
    dx: float
    dy: float
    dz: float
    orientation_name: str
    nx: int
    max_nz: int
    is_upright: bool
    is_flat: bool
    is_side: bool
    raw_sku: Any


class CompositeStripBuilder:
    """
    Builder engine for constructing high-coverage composite multi-SKU wall strips.
    """

    def __init__(
        self,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
        default_margin_y: float = 0.01,
        default_margin_z: float = 0.04,
    ):
        self.geom_epsilon = geom_epsilon
        self.default_margin_y = default_margin_y
        self.default_margin_z = default_margin_z

    def build_strip(
        self,
        delta_x: float,
        target_width: float,
        available_height: float,
        cargo_pool: Sequence[Union[CargoSKU, UniversalCargoTensor]],
        remaining_qty: Optional[Dict[str, int]] = None,
        preferred_primary_sku: Optional[str] = None,
        context: PlacementContext = PlacementContext.MAIN_WALL,
        max_subcolumns: int = 8,
        allow_mixed_skus: bool = True,
    ) -> CompositeStripResult:
        """
        Builds a composite strip maximizing Y-axis coverage using Best-Fit-Decreasing
        and bounded combinatorial search.
        """
        if delta_x <= self.geom_epsilon or target_width <= self.geom_epsilon or available_height <= self.geom_epsilon:
            return CompositeStripResult(
                target_width=target_width,
                delta_x=delta_x,
                available_height=available_height,
                is_valid=False,
            )

        # 1. Normalize inventory and candidate options
        curr_rem_qty: Dict[str, int] = {}
        for c in cargo_pool:
            sku_id = getattr(c, "sku_id", "")
            if not sku_id:
                continue
            if remaining_qty is not None and sku_id in remaining_qty:
                curr_rem_qty[sku_id] = remaining_qty[sku_id]
            elif hasattr(c, "quantity") and hasattr(c.quantity, "required"):
                curr_rem_qty[sku_id] = c.quantity.required
            elif hasattr(c, "quantity_required"):
                curr_rem_qty[sku_id] = c.quantity_required
            else:
                curr_rem_qty[sku_id] = 1

        active_options = self._extract_eligible_orientations(
            cargo_pool=cargo_pool,
            delta_x=delta_x,
            target_width=target_width,
            available_height=available_height,
            remaining_qty=curr_rem_qty,
        )

        if not active_options:
            return CompositeStripResult(
                target_width=target_width,
                delta_x=delta_x,
                available_height=available_height,
                is_valid=False,
            )

        # 2. Generate candidate strip combinations
        # We try multiple strategies:
        # A. BFD Greedy with dy descending
        # B. Combinatorial beam search / subset search to find exact Y fit (>= 92% coverage)
        # C. Primary-SKU anchored BFD if preferred_primary_sku is specified
        candidates: List[CompositeStripResult] = []

        # Strategy A: BFD with standard dy-descending ordering
        cand_bfd = self._build_greedy_bfd_strip(
            options=active_options,
            target_width=target_width,
            delta_x=delta_x,
            available_height=available_height,
            inventory=curr_rem_qty,
            context=context,
            max_subcolumns=max_subcolumns,
            allow_mixed_skus=allow_mixed_skus,
        )
        if cand_bfd and cand_bfd.columns:
            candidates.append(cand_bfd)

        # Strategy B: Knapsack/Combinatorial optimization for near-perfect width packing
        cand_knapsack = self._build_combinatorial_strip(
            options=active_options,
            target_width=target_width,
            delta_x=delta_x,
            available_height=available_height,
            inventory=curr_rem_qty,
            context=context,
            max_subcolumns=max_subcolumns,
            allow_mixed_skus=allow_mixed_skus,
        )
        if cand_knapsack and cand_knapsack.columns:
            candidates.append(cand_knapsack)

        # Strategy C: Preferred primary SKU prioritized
        if preferred_primary_sku and allow_mixed_skus:
            cand_pref = self._build_primary_biased_strip(
                primary_sku_id=preferred_primary_sku,
                options=active_options,
                target_width=target_width,
                delta_x=delta_x,
                available_height=available_height,
                inventory=curr_rem_qty,
                context=context,
                max_subcolumns=max_subcolumns,
            )
            if cand_pref and cand_pref.columns:
                candidates.append(cand_pref)

        if not candidates:
            return CompositeStripResult(
                target_width=target_width,
                delta_x=delta_x,
                available_height=available_height,
                is_valid=False,
            )

        # Rank candidates by:
        # 1. Y-coverage ratio (highest)
        # 2. Total volume packed
        # 3. Simplicity (fewer distinct SKU fractures)
        def score_candidate(res: CompositeStripResult) -> float:
            cov = res.y_coverage_ratio
            vol = res.total_volume
            num_cols = len(res.columns)
            distinct_skus = len(res.sku_counts)
            return cov * 1000.0 + vol * 50.0 - num_cols * 0.5 - distinct_skus * 1.0

        best_result = max(candidates, key=score_candidate)
        return best_result

    def _extract_eligible_orientations(
        self,
        cargo_pool: Sequence[Union[CargoSKU, UniversalCargoTensor]],
        delta_x: float,
        target_width: float,
        available_height: float,
        remaining_qty: Dict[str, int],
    ) -> List[_CandidateOrientationOption]:
        """Extract all legal orientation options satisfying bounding limits."""
        options: List[_CandidateOrientationOption] = []

        for c in cargo_pool:
            sku_id = getattr(c, "sku_id", "")
            if not sku_id or remaining_qty.get(sku_id, 0) <= 0:
                continue

            sku_name = getattr(c, "name", sku_id)
            weight_kg = getattr(c, "weight_kg", 0.0)

            # Determine max stacking layers
            max_stack = None
            if hasattr(c, "stacking_policy") and c.stacking_policy:
                max_stack = c.stacking_policy.max_stack_layers
            elif hasattr(c, "max_stack_layers"):
                max_stack = c.max_stack_layers

            # Determine orientations
            oris: List[Tuple[str, float, float, float, bool, bool, bool]] = []
            if isinstance(c, UniversalCargoTensor):
                for o in c.orientations:
                    oris.append((o.name, o.dx, o.dy, o.dz, o.is_upright, o.is_flat, o.is_side))
            elif isinstance(c, CargoSKU):
                bx, by, bz = c.box.x, c.box.y, c.box.z
                policy = c.orientation_policy
                # Upright
                oris.append(("UPRIGHT_NORMAL", bx, by, bz, True, False, False))
                if abs(bx - by) > self.geom_epsilon:
                    oris.append(("UPRIGHT_ROTATED", by, bx, bz, True, False, False))
                if policy.allow_flat:
                    oris.append(("FLAT_NORMAL", bx, bz, by, False, True, False))
                    if abs(bx - bz) > self.geom_epsilon:
                        oris.append(("FLAT_ROTATED", bz, bx, by, False, True, False))
                if policy.allow_side:
                    oris.append(("SIDE_NORMAL", bz, by, bx, False, False, True))
                    if abs(bz - by) > self.geom_epsilon:
                        oris.append(("SIDE_ROTATED", by, bz, bx, False, False, True))
            else:
                # Generic object
                lx = getattr(c, "length", getattr(c, "x", 0.4))
                wy = getattr(c, "width", getattr(c, "y", 0.4))
                hz = getattr(c, "height", getattr(c, "z", 0.4))
                oris.append(("UPRIGHT_NORMAL", lx, wy, hz, True, False, False))

            for ori_name, dx, dy, dz, is_up, is_fl, is_sd in oris:
                if dx <= delta_x + self.geom_epsilon and dy <= target_width + self.geom_epsilon and dz <= available_height + self.geom_epsilon:
                    nx = max(1, int((delta_x + self.geom_epsilon) // dx))
                    max_nz = int((available_height + self.geom_epsilon) // dz)
                    if max_stack is not None and max_stack > 0:
                        max_nz = min(max_nz, max_stack)
                    max_nz = max(1, max_nz)

                    options.append(
                        _CandidateOrientationOption(
                            sku_id=sku_id,
                            sku_name=sku_name,
                            weight_kg=weight_kg,
                            dx=round(dx, 4),
                            dy=round(dy, 4),
                            dz=round(dz, 4),
                            orientation_name=ori_name,
                            nx=nx,
                            max_nz=max_nz,
                            is_upright=is_up,
                            is_flat=is_fl,
                            is_side=is_sd,
                            raw_sku=c,
                        )
                    )

        return options

    def _build_greedy_bfd_strip(
        self,
        options: List[_CandidateOrientationOption],
        target_width: float,
        delta_x: float,
        available_height: float,
        inventory: Dict[str, int],
        context: PlacementContext,
        max_subcolumns: int,
        allow_mixed_skus: bool,
    ) -> Optional[CompositeStripResult]:
        """Greedy Best Fit Decreasing by dy descending."""
        # Sort options: prioritize larger dy, then depth alignment with delta_x, then volume
        sorted_opts = sorted(
            options,
            key=lambda o: (o.dy, (o.nx * o.dx) / delta_x, o.dx * o.dy * o.dz),
            reverse=True,
        )

        rem_inv = dict(inventory)
        columns: List[SubColumnConfig] = []
        cur_y = 0.0
        primary_sku_id = sorted_opts[0].sku_id if sorted_opts else None

        for _ in range(max_subcolumns):
            rem_w = round(target_width - cur_y, 4)
            if rem_w <= self.geom_epsilon:
                break

            best_opt: Optional[_CandidateOrientationOption] = None
            best_ny: int = 0
            best_nz: int = 0

            for opt in sorted_opts:
                if not allow_mixed_skus and primary_sku_id and opt.sku_id != primary_sku_id:
                    continue
                avail_qty = rem_inv.get(opt.sku_id, 0)
                if avail_qty <= 0:
                    continue

                if opt.dy <= rem_w + self.geom_epsilon:
                    max_ny = int((rem_w + self.geom_epsilon) // opt.dy)
                    if max_ny < 1:
                        continue

                    # Try to fill full height or available qty
                    for ny in range(max_ny, 0, -1):
                        needed_per_layer = opt.nx * ny
                        if needed_per_layer <= 0:
                            continue
                        possible_nz = min(opt.max_nz, avail_qty // needed_per_layer)
                        if possible_nz >= 1:
                            best_opt = opt
                            best_ny = ny
                            best_nz = possible_nz
                            break
                    if best_opt:
                        break

            if not best_opt or best_ny == 0 or best_nz == 0:
                break

            total_items = best_opt.nx * best_ny * best_nz
            col_w = round(best_ny * best_opt.dy, 4)
            col_d = round(best_opt.nx * best_opt.dx, 4)
            col_h = round(best_nz * best_opt.dz, 4)
            headroom = round(max(0.0, available_height - col_h), 4)

            col = SubColumnConfig(
                sku_id=best_opt.sku_id,
                sku_name=best_opt.sku_name,
                orientation_name=best_opt.orientation_name,
                dx=best_opt.dx,
                dy=best_opt.dy,
                dz=best_opt.dz,
                nx=best_opt.nx,
                ny=best_ny,
                nz=best_nz,
                total_cartons=total_items,
                y_offset=round(cur_y, 4),
                column_width=col_w,
                column_depth=col_d,
                column_height=col_h,
                headroom=headroom,
                weight_kg=best_opt.weight_kg,
                total_weight_kg=round(total_items * best_opt.weight_kg, 2),
                tag="GAP_FILL" if best_opt.is_flat else "MAIN_WALL",
                context=context,
            )
            columns.append(col)
            rem_inv[best_opt.sku_id] -= total_items
            cur_y = round(cur_y + col_w, 4)

        return self._finalize_strip_result(columns, target_width, delta_x, available_height)

    def _build_combinatorial_strip(
        self,
        options: List[_CandidateOrientationOption],
        target_width: float,
        delta_x: float,
        available_height: float,
        inventory: Dict[str, int],
        context: PlacementContext,
        max_subcolumns: int,
        allow_mixed_skus: bool,
    ) -> Optional[CompositeStripResult]:
        """
        Combinatorial subset generation to achieve >92% (often 98-100%) Y coverage
        by finding optimal combinations of widths dy_1*ny_1 + dy_2*ny_2 + ... <= target_width.
        """
        # Deduplicate option geometries per SKU
        dedup_opts: List[_CandidateOrientationOption] = []
        seen_keys: Set[Tuple[str, float, float, float]] = set()
        for o in options:
            key = (o.sku_id, o.dx, o.dy, o.dz)
            if key not in seen_keys:
                seen_keys.add(key)
                dedup_opts.append(o)

        best_combo: List[Tuple[_CandidateOrientationOption, int, int]] = []
        best_width = 0.0
        best_volume = 0.0

        # Recursive bounded search / beam search over combinations
        # State: (current_y, combo_list, remaining_inv_dict)
        def search(
            idx: int,
            current_y: float,
            current_combo: List[Tuple[_CandidateOrientationOption, int, int]],
            rem_inv: Dict[str, int],
        ):
            nonlocal best_combo, best_width, best_volume

            rem_w = round(target_width - current_y, 4)
            if rem_w < self.geom_epsilon or len(current_combo) >= max_subcolumns or idx >= len(dedup_opts):
                # Evaluate current configuration
                cur_w = round(sum(o.dy * ny for o, ny, _ in current_combo), 4)
                cur_vol = sum((o.dx * o.nx) * (o.dy * ny) * (o.dz * nz) for o, ny, nz in current_combo)
                if cur_w > best_width + 1e-4 or (abs(cur_w - best_width) <= 1e-4 and cur_vol > best_volume):
                    best_width = cur_w
                    best_volume = cur_vol
                    best_combo = list(current_combo)
                return

            opt = dedup_opts[idx]
            avail = rem_inv.get(opt.sku_id, 0)

            # Option 1: Try skipping this option
            search(idx + 1, current_y, current_combo, rem_inv)

            # Option 2: Try using ny = 1..max_ny of this option
            if avail > 0 and opt.dy <= rem_w + self.geom_epsilon:
                max_ny = min(int((rem_w + self.geom_epsilon) // opt.dy), 10)
                for ny in range(max_ny, 0, -1):
                    needed_per_layer = opt.nx * ny
                    if needed_per_layer <= 0:
                        continue
                    nz = min(opt.max_nz, avail // needed_per_layer)
                    if nz >= 1:
                        total_needed = needed_per_layer * nz
                        new_inv = dict(rem_inv)
                        new_inv[opt.sku_id] -= total_needed
                        new_y = round(current_y + ny * opt.dy, 4)
                        
                        current_combo.append((opt, ny, nz))
                        if not allow_mixed_skus:
                            # If single SKU only, evaluate immediately
                            cur_w = round(sum(o.dy * c_ny for o, c_ny, _ in current_combo), 4)
                            cur_vol = sum((o.dx * o.nx) * (o.dy * c_ny) * (o.dz * c_nz) for o, c_ny, c_nz in current_combo)
                            if cur_w > best_width:
                                best_width = cur_w
                                best_volume = cur_vol
                                best_combo = list(current_combo)
                        else:
                            search(idx + 1, new_y, current_combo, new_inv)
                        current_combo.pop()

        search(0, 0.0, [], dict(inventory))

        if not best_combo:
            return None

        # Build columns from best combination
        columns: List[SubColumnConfig] = []
        cur_y = 0.0
        for opt, ny, nz in best_combo:
            total_items = opt.nx * ny * nz
            col_w = round(ny * opt.dy, 4)
            col_d = round(opt.nx * opt.dx, 4)
            col_h = round(nz * opt.dz, 4)
            headroom = round(max(0.0, available_height - col_h), 4)

            columns.append(
                SubColumnConfig(
                    sku_id=opt.sku_id,
                    sku_name=opt.sku_name,
                    orientation_name=opt.orientation_name,
                    dx=opt.dx,
                    dy=opt.dy,
                    dz=opt.dz,
                    nx=opt.nx,
                    ny=ny,
                    nz=nz,
                    total_cartons=total_items,
                    y_offset=round(cur_y, 4),
                    column_width=col_w,
                    column_depth=col_d,
                    column_height=col_h,
                    headroom=headroom,
                    weight_kg=opt.weight_kg,
                    total_weight_kg=round(total_items * opt.weight_kg, 2),
                    tag="GAP_FILL" if opt.is_flat else "MAIN_WALL",
                    context=context,
                )
            )
            cur_y = round(cur_y + col_w, 4)

        return self._finalize_strip_result(columns, target_width, delta_x, available_height)

    def _build_primary_biased_strip(
        self,
        primary_sku_id: str,
        options: List[_CandidateOrientationOption],
        target_width: float,
        delta_x: float,
        available_height: float,
        inventory: Dict[str, int],
        context: PlacementContext,
        max_subcolumns: int,
    ) -> Optional[CompositeStripResult]:
        """Places primary SKU first across Y, then fills remaining width with companion SKUs."""
        primary_opts = [o for o in options if o.sku_id == primary_sku_id]
        companion_opts = [o for o in options if o.sku_id != primary_sku_id]

        if not primary_opts:
            return None

        primary_opts.sort(key=lambda o: (o.dy, o.dx * o.dy * o.dz), reverse=True)
        companion_opts.sort(key=lambda o: (o.dy, o.dx * o.dy * o.dz), reverse=True)

        rem_inv = dict(inventory)
        columns: List[SubColumnConfig] = []
        cur_y = 0.0

        # Step 1: Place primary SKU
        p_opt = primary_opts[0]
        p_avail = rem_inv.get(primary_sku_id, 0)
        if p_avail > 0 and p_opt.dy <= target_width + self.geom_epsilon:
            max_ny = int((target_width + self.geom_epsilon) // p_opt.dy)
            chosen_ny = 0
            chosen_nz = 0
            for ny in range(max_ny, 0, -1):
                needed_layer = p_opt.nx * ny
                if needed_layer <= 0:
                    continue
                nz = min(p_opt.max_nz, p_avail // needed_layer)
                if nz >= 1:
                    chosen_ny = ny
                    chosen_nz = nz
                    break

            if chosen_ny > 0 and chosen_nz > 0:
                p_items = p_opt.nx * chosen_ny * chosen_nz
                p_w = round(chosen_ny * p_opt.dy, 4)
                p_d = round(p_opt.nx * p_opt.dx, 4)
                p_h = round(chosen_nz * p_opt.dz, 4)
                columns.append(
                    SubColumnConfig(
                        sku_id=p_opt.sku_id,
                        sku_name=p_opt.sku_name,
                        orientation_name=p_opt.orientation_name,
                        dx=p_opt.dx,
                        dy=p_opt.dy,
                        dz=p_opt.dz,
                        nx=p_opt.nx,
                        ny=chosen_ny,
                        nz=chosen_nz,
                        total_cartons=p_items,
                        y_offset=0.0,
                        column_width=p_w,
                        column_depth=p_d,
                        column_height=p_h,
                        headroom=round(max(0.0, available_height - p_h), 4),
                        weight_kg=p_opt.weight_kg,
                        total_weight_kg=round(p_items * p_opt.weight_kg, 2),
                        tag="MAIN_WALL",
                        context=context,
                    )
                )
                rem_inv[primary_sku_id] -= p_items
                cur_y = p_w

        # Step 2: Fill remainder width with companion SKUs
        for _ in range(max_subcolumns - 1):
            rem_w = round(target_width - cur_y, 4)
            if rem_w <= self.geom_epsilon:
                break

            best_c_opt = None
            best_c_ny = 0
            best_c_nz = 0

            for c_opt in companion_opts:
                c_avail = rem_inv.get(c_opt.sku_id, 0)
                if c_avail <= 0 or c_opt.dy > rem_w + self.geom_epsilon:
                    continue
                max_ny = int((rem_w + self.geom_epsilon) // c_opt.dy)
                for ny in range(max_ny, 0, -1):
                    needed_layer = c_opt.nx * ny
                    if needed_layer <= 0:
                        continue
                    nz = min(c_opt.max_nz, c_avail // needed_layer)
                    if nz >= 1:
                        best_c_opt = c_opt
                        best_c_ny = ny
                        best_c_nz = nz
                        break
                if best_c_opt:
                    break

            if not best_c_opt or best_c_ny == 0 or best_c_nz == 0:
                break

            c_items = best_c_opt.nx * best_c_ny * best_c_nz
            c_w = round(best_c_ny * best_c_opt.dy, 4)
            c_d = round(best_c_opt.nx * best_c_opt.dx, 4)
            c_h = round(best_c_nz * best_c_opt.dz, 4)
            columns.append(
                SubColumnConfig(
                    sku_id=best_c_opt.sku_id,
                    sku_name=best_c_opt.sku_name,
                    orientation_name=best_c_opt.orientation_name,
                    dx=best_c_opt.dx,
                    dy=best_c_opt.dy,
                    dz=best_c_opt.dz,
                    nx=best_c_opt.nx,
                    ny=best_c_ny,
                    nz=best_c_nz,
                    total_cartons=c_items,
                    y_offset=round(cur_y, 4),
                    column_width=c_w,
                    column_depth=c_d,
                    column_height=c_h,
                    headroom=round(max(0.0, available_height - c_h), 4),
                    weight_kg=best_c_opt.weight_kg,
                    total_weight_kg=round(c_items * best_c_opt.weight_kg, 2),
                    tag="GAP_FILL" if best_c_opt.is_flat else "MAIN_WALL",
                    context=context,
                )
            )
            rem_inv[best_c_opt.sku_id] -= c_items
            cur_y = round(cur_y + c_w, 4)

        return self._finalize_strip_result(columns, target_width, delta_x, available_height)

    def _finalize_strip_result(
        self,
        columns: List[SubColumnConfig],
        target_width: float,
        delta_x: float,
        available_height: float,
    ) -> CompositeStripResult:
        """Calculates aggregate metrics, stepped heights, and headroom profiles."""
        if not columns:
            return CompositeStripResult(
                target_width=target_width,
                delta_x=delta_x,
                available_height=available_height,
                is_valid=False,
            )

        total_w = round(sum(c.column_width for c in columns), 4)
        cov_ratio = round(total_w / target_width, 4) if target_width > 0 else 0.0
        total_cartons = sum(c.total_cartons for c in columns)
        total_vol = sum(c.total_cartons * (c.dx * c.dy * c.dz) for c in columns)
        total_wt = sum(c.total_weight_kg for c in columns)

        stepped_heights: List[Tuple[float, float, float]] = []
        headroom_profiles: List[Tuple[float, float, float]] = []
        sku_counts: Dict[str, int] = {}

        for c in columns:
            y0 = round(c.y_offset, 4)
            y1 = round(c.y_offset + c.column_width, 4)
            stepped_heights.append((y0, y1, round(c.column_height, 4)))
            headroom_profiles.append((y0, y1, round(c.headroom, 4)))
            sku_counts[c.sku_id] = sku_counts.get(c.sku_id, 0) + c.total_cartons

        return CompositeStripResult(
            columns=columns,
            total_width=total_w,
            target_width=target_width,
            y_coverage_ratio=cov_ratio,
            delta_x=delta_x,
            available_height=available_height,
            total_cartons=total_cartons,
            total_volume=round(total_vol, 4),
            total_weight_kg=round(total_wt, 2),
            stepped_heights=stepped_heights,
            headroom_profiles=headroom_profiles,
            sku_counts=sku_counts,
            is_valid=True,
        )
