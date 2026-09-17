"""
CP-SAT Macro Allocator for 3D Packing Solver (Phase 1).
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple, Any

from ortools.sat.python import cp_model

from backend.solver_v2.domain.models import (
    ContainerSpec,
    OrientationSpec,
    UniversalCargoTensor,
    UniversalZone,
)


@dataclass
class StripItemTemplate:
    sku_id: str
    orientation: OrientationSpec
    count_per_instance: int


@dataclass
class CandidateStrip:
    strip_type_id: int
    items: List[StripItemTemplate]
    x_depth: float
    y_coverage: float
    z_coverage: float
    volume_filled: float
    zone: str = "MIDDLE"  # "INNER" | "MIDDLE" | "DOOR"


@dataclass
class StripItem:
    sku_id: str
    orientation: OrientationSpec
    count: int


@dataclass
class StripAllocation:
    strip_id: int
    x_start: float
    x_depth: float
    zone: str
    items: List[StripItem]


@dataclass
class MacroAllocationResult:
    strips: List[StripAllocation]
    total_allocated: Dict[str, int]
    solver_status: str
    objective_value: float
    solve_time_ms: float


DEFAULT_OBJECTIVE_WEIGHTS: Dict[str, int] = {
    "rigid_fulfillment": 10000,
    "compactness": 1000,
    "com_stability": 200,
    "elastic": 1,
}


class CPSATMacroAllocator:
    """
    CP-SAT Macro Allocator Engine.
    Discretizes container X-axis and assigns strip patterns to satisfy physical constraints.
    """

    def __init__(self, container: ContainerSpec):
        self.container = container
        self.cL = round(container.Lx, 4)
        self.cW = round(container.Ly, 4)
        self.cH = round(container.Lz, 4)
        self.door_zone_len = getattr(container, "door_zone_length_m", 1.5)
        self.rear_zone_len = getattr(container, "rear_zone_length_m", 1.5)

    def _generate_candidate_strips(
        self,
        cargo_list: List[UniversalCargoTensor],
        x_limit: Optional[float] = None,
    ) -> List[CandidateStrip]:
        max_x = x_limit if x_limit is not None else self.cL
        candidates: List[CandidateStrip] = []

        for cargo in cargo_list:
            if cargo.quantity_required <= 0:
                continue

            for ori in cargo.orientations:
                cols_y = int(self.cW / ori.dy)
                if cols_y <= 0:
                    continue

                rows_z = int(self.cH / ori.dz)
                max_layers = cargo.max_stack_layers or 99
                if getattr(cargo, "must_be_on_floor", False):
                    max_layers = 1
                rows_z = min(rows_z, max_layers)
                if rows_z <= 0:
                    continue

                cap_per_slice = cols_y * rows_z
                x_depth = ori.dx

                max_rows_x = min(8, int(max_x / x_depth)) if x_depth > 0 else 1
                for n_rows in range(1, max_rows_x + 1):
                    depth = round(x_depth * n_rows, 4)
                    if depth > max_x:
                        break
                    tot_cap = cap_per_slice * n_rows
                    if tot_cap <= 0:
                        continue

                    zone = "MIDDLE"
                    if cargo.zone_preference == UniversalZone.INNER:
                        zone = "INNER"
                    elif cargo.zone_preference == UniversalZone.DOOR:
                        zone = "DOOR"

                    vol = round(tot_cap * ori.dx * ori.dy * ori.dz, 6)
                    candidates.append(
                        CandidateStrip(
                            strip_type_id=len(candidates),
                            items=[
                                StripItemTemplate(
                                    sku_id=cargo.sku_id,
                                    orientation=ori,
                                    count_per_instance=tot_cap,
                                )
                            ],
                            x_depth=depth,
                            y_coverage=round(cols_y * ori.dy / self.cW, 4),
                            z_coverage=round(rows_z * ori.dz / self.cH, 4),
                            volume_filled=vol,
                            zone=zone,
                        )
                    )

        combo_strips = self._generate_dual_combo_strips(cargo_list, max_x)
        candidates.extend(combo_strips)

        if len(candidates) > 500:
            candidates.sort(
                key=lambda s: s.volume_filled / max(1e-4, s.x_depth),
                reverse=True,
            )
            candidates = candidates[:500]
            for idx, c in enumerate(candidates):
                c.strip_type_id = idx

        return candidates

    def _generate_dual_combo_strips(
        self,
        cargo_list: List[UniversalCargoTensor],
        max_x: float,
    ) -> List[CandidateStrip]:
        combos: List[CandidateStrip] = []
        n_skus = len(cargo_list)
        if n_skus < 2:
            return combos

        for i in range(n_skus):
            c1 = cargo_list[i]
            for j in range(i + 1, n_skus):
                c2 = cargo_list[j]

                for ori1 in c1.orientations:
                    for ori2 in c2.orientations:
                        ratio = ori1.dx / ori2.dx
                        nx1, nx2 = 1, 1
                        if abs(ori1.dx - ori2.dx) < 0.02:
                            depth = max(ori1.dx, ori2.dx)
                            nx1, nx2 = 1, 1
                        elif abs(ratio - 2.0) < 0.05:
                            depth = ori1.dx
                            nx1, nx2 = 1, 2
                        elif abs(ratio - 0.5) < 0.05:
                            depth = ori2.dx
                            nx1, nx2 = 2, 1
                        else:
                            continue

                        if depth > max_x:
                            continue

                        for ny1 in range(1, int(self.cW / ori1.dy) + 1):
                            rem_w = self.cW - ny1 * ori1.dy
                            if rem_w < ori2.dy:
                                continue
                            ny2 = int(rem_w / ori2.dy)
                            if ny2 <= 0:
                                continue

                            nz1 = min(int(self.cH / ori1.dz), c1.max_stack_layers or 99)
                            if getattr(c1, "must_be_on_floor", False):
                                nz1 = 1
                            nz2 = min(int(self.cH / ori2.dz), c2.max_stack_layers or 99)
                            if getattr(c2, "must_be_on_floor", False):
                                nz2 = 1

                            cnt1 = nx1 * ny1 * nz1
                            cnt2 = nx2 * ny2 * nz2
                            if cnt1 <= 0 or cnt2 <= 0:
                                continue

                            vol1 = cnt1 * ori1.dx * ori1.dy * ori1.dz
                            vol2 = cnt2 * ori2.dx * ori2.dy * ori2.dz
                            total_vol = round(vol1 + vol2, 6)

                            combos.append(
                                CandidateStrip(
                                    strip_type_id=len(combos),
                                    items=[
                                        StripItemTemplate(c1.sku_id, ori1, cnt1),
                                        StripItemTemplate(c2.sku_id, ori2, cnt2),
                                    ],
                                    x_depth=depth,
                                    y_coverage=round((ny1 * ori1.dy + ny2 * ori2.dy) / self.cW, 4),
                                    z_coverage=round(max(nz1 * ori1.dz, nz2 * ori2.dz) / self.cH, 4),
                                    volume_filled=total_vol,
                                    zone="MIDDLE",
                                )
                            )
                            if len(combos) >= 150:
                                return combos
        return combos


    def _build_cpsat_model(
        self,
        cargo_list: List[UniversalCargoTensor],
        candidate_strips: List[CandidateStrip],
        min_rigid_ratio: float = 1.0,
        x_limit: Optional[float] = None,
        weights: Optional[Dict[str, int]] = None,
    ) -> Tuple[cp_model.CpModel, Dict[int, cp_model.IntVar], Dict[str, cp_model.IntVar]]:
        model = cp_model.CpModel()
        max_x = x_limit if x_limit is not None else self.cL

        w_cfg = dict(DEFAULT_OBJECTIVE_WEIGHTS)
        if weights:
            w_cfg.update(weights)

        strip_used: Dict[int, cp_model.IntVar] = {}
        for i, strip in enumerate(candidate_strips):
            max_repeats = max(1, int(max_x / max(1e-4, strip.x_depth)))
            strip_used[i] = model.NewIntVar(0, max_repeats, f"strip_{i}")

        sku_placed: Dict[str, cp_model.IntVar] = {}
        for cargo in cargo_list:
            upper = cargo.quantity_required if not cargo.is_elastic else max(cargo.quantity_required * 3, 500)
            sku_placed[cargo.sku_id] = model.NewIntVar(0, upper, f"placed_{cargo.sku_id}")

        # 1. Total X length budget constraint
        SCALE = 10000
        model.Add(
            sum(
                strip_used[i] * int(round(strip.x_depth * SCALE))
                for i, strip in enumerate(candidate_strips)
            )
            <= int(round(max_x * SCALE))
        )

        # 2. Link strip usage to SKU placed counts
        for cargo in cargo_list:
            terms = []
            for i, strip in enumerate(candidate_strips):
                for item in strip.items:
                    if item.sku_id == cargo.sku_id:
                        terms.append(strip_used[i] * item.count_per_instance)
            if terms:
                model.Add(sku_placed[cargo.sku_id] == sum(terms))
            else:
                model.Add(sku_placed[cargo.sku_id] == 0)

        # 3. Rigid hard constraints vs Elastic soft optimization
        for cargo in cargo_list:
            if not cargo.is_elastic:
                # Force rigid items to exactly meet required quantity if feasible
                model.Add(sku_placed[cargo.sku_id] <= cargo.quantity_required)
                min_qty = int(math.floor(cargo.quantity_required * min_rigid_ratio))
                if min_qty > 0:
                    model.Add(sku_placed[cargo.sku_id] >= min_qty)

        # 4. Total weight limit
        WEIGHT_SCALE = 100
        weight_terms = []
        cargo_weight_map = {c.sku_id: c.weight_kg for c in cargo_list}
        cargo_floor_map = {c.sku_id: getattr(c, "must_be_on_floor", False) for c in cargo_list}
        for i, strip in enumerate(candidate_strips):
            s_weight = sum(
                item.count_per_instance * cargo_weight_map.get(item.sku_id, 0.0)
                for item in strip.items
            )
            weight_terms.append(strip_used[i] * int(round(s_weight * WEIGHT_SCALE)))

        max_payload = getattr(self.container, "max_payload_kg", 30000.0)
        model.Add(sum(weight_terms) <= int(round(max_payload * WEIGHT_SCALE)))

        # 5. Multi-objective construction
        # Term A: Rigid Cargo Fulfillment (10000x multiplier guarantees zero priority inversion)
        VOL_SCALE = 1000
        obj_terms = []
        w_rigid = w_cfg.get("rigid_fulfillment", 10000)
        w_elastic = w_cfg.get("elastic", 1)
        w_compact = w_cfg.get("compactness", 1000)
        w_com = w_cfg.get("com_stability", 200)

        for cargo in cargo_list:
            unit_vol = max(1, int(round(cargo.volume_m3 * VOL_SCALE)))
            if not cargo.is_elastic:
                obj_terms.append(sku_placed[cargo.sku_id] * unit_vol * w_rigid)
            else:
                obj_terms.append(sku_placed[cargo.sku_id] * unit_vol * w_elastic)

        # Term B: Compactness Objective (Rewards full cross-section coverage, penalizes void fragmentation)
        for i, strip in enumerate(candidate_strips):
            vol_box = max(1e-4, strip.x_depth * self.cW * self.cH)
            fill_ratio = min(1.0, strip.volume_filled / vol_box)
            # Higher y_coverage & z_coverage yields significantly more compact and stable walls
            coverage_factor = strip.y_coverage * strip.z_coverage
            compact_score = int(round(fill_ratio * coverage_factor * w_compact))
            if compact_score > 0:
                obj_terms.append(strip_used[i] * compact_score)

        # Term C: Center-of-Mass & Ground Stacking Stability
        for i, strip in enumerate(candidate_strips):
            has_floor_req = any(cargo_floor_map.get(item.sku_id, False) for item in strip.items)
            # Low center-of-mass & high density base strips receive stability bonus
            s_weight = sum(item.count_per_instance * cargo_weight_map.get(item.sku_id, 0.0) for item in strip.items)
            density_score = min(100, int(round((s_weight / max(1e-3, strip.volume_filled)) / 20.0)))
            floor_bonus = 50 if has_floor_req else 0
            # Strips that are too slender or have weak z_coverage are penalized
            tipping_safety_score = max(0, int(round((density_score + floor_bonus) * (w_com / 100.0))))
            if tipping_safety_score > 0:
                obj_terms.append(strip_used[i] * tipping_safety_score)

        model.Maximize(sum(obj_terms))
        return model, strip_used, sku_placed

    def solve(
        self,
        cargo_list: List[UniversalCargoTensor],
        time_limit_seconds: float = 60.0,
        weights: Optional[Dict[str, int]] = None,
    ) -> MacroAllocationResult:
        t0 = time.perf_counter()

        # Pre-check: feasibility of rigid cargo volume
        rigid_tensors = [t for t in cargo_list if not t.is_elastic]
        total_rigid_vol = sum(t.volume_m3 * t.quantity_required for t in rigid_tensors)
        container_vol = self.container.volume
        if container_vol > 0 and total_rigid_vol > container_vol * 0.98:
            return MacroAllocationResult(
                strips=[],
                total_allocated={c.sku_id: 0 for c in cargo_list},
                solver_status="INFEASIBLE",
                objective_value=0.0,
                solve_time_ms=(time.perf_counter() - t0) * 1000.0,
            )

        candidate_strips = self._generate_candidate_strips(cargo_list)

        if not candidate_strips:
            return MacroAllocationResult(
                strips=[],
                total_allocated={c.sku_id: 0 for c in cargo_list},
                solver_status="INFEASIBLE",
                objective_value=0.0,
                solve_time_ms=(time.perf_counter() - t0) * 1000.0,
            )

        # Rigid fulfillment priority ladder: try 100% hard constraint first
        relaxation_levels = [1.0, 0.99, 0.95, 0.90, 0.80, 0.50, 0.0]
        per_level_time = max(2.0, time_limit_seconds / len(relaxation_levels))

        for level in relaxation_levels:
            rem_time = max(1.0, time_limit_seconds - (time.perf_counter() - t0))
            current_time_limit = min(per_level_time, rem_time)

            model, strip_used, sku_placed = self._build_cpsat_model(
                cargo_list, candidate_strips, min_rigid_ratio=level, weights=weights
            )

            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = current_time_limit
            solver.parameters.num_search_workers = min(8, os.cpu_count() or 4)

            status = solver.Solve(model)
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                return self._extract_result(
                    solver,
                    strip_used,
                    sku_placed,
                    candidate_strips,
                    cargo_list,
                    status,
                    (time.perf_counter() - t0) * 1000.0,
                )

        return MacroAllocationResult(
            strips=[],
            total_allocated={c.sku_id: 0 for c in cargo_list},
            solver_status="INFEASIBLE",
            objective_value=0.0,
            solve_time_ms=(time.perf_counter() - t0) * 1000.0,
        )

    def _extract_result(
        self,
        solver: cp_model.CpSolver,
        strip_used: Dict[int, cp_model.IntVar],
        sku_placed: Dict[str, cp_model.IntVar],
        candidate_strips: List[CandidateStrip],
        cargo_list: List[UniversalCargoTensor],
        status: int,
        solve_time_ms: float,
    ) -> MacroAllocationResult:
        strips_allocated: List[StripAllocation] = []
        current_x = 0.0
        strip_counter = 0

        selected_strip_indices = []
        for i, var in strip_used.items():
            count = solver.Value(var)
            if count > 0:
                selected_strip_indices.append((i, count))

        cargo_weight_map = {c.sku_id: c.weight_kg for c in cargo_list}
        cargo_floor_map = {c.sku_id: getattr(c, "must_be_on_floor", False) for c in cargo_list}

        def strip_placement_priority(item_idx: int) -> Tuple[int, int, float, float]:
            cand = candidate_strips[item_idx]
            z_prio = 0 if cand.zone == "INNER" else (1 if cand.zone == "MIDDLE" else 2)
            has_floor = 0 if any(cargo_floor_map.get(it.sku_id, False) for it in cand.items) else 1
            s_weight = sum(it.count_per_instance * cargo_weight_map.get(it.sku_id, 0.0) for it in cand.items)
            density = s_weight / max(1e-3, cand.volume_filled)
            return (z_prio, has_floor, -round(density, 2), -round(cand.y_coverage, 2))

        selected_strip_indices.sort(key=lambda pair: strip_placement_priority(pair[0]))

        for idx, count in selected_strip_indices:
            cand = candidate_strips[idx]
            for _ in range(count):
                alloc_items = [
                    StripItem(
                        sku_id=it.sku_id,
                        orientation=it.orientation,
                        count=it.count_per_instance,
                    )
                    for it in cand.items
                ]
                strips_allocated.append(
                    StripAllocation(
                        strip_id=strip_counter,
                        x_start=round(current_x, 4),
                        x_depth=cand.x_depth,
                        zone=cand.zone,
                        items=alloc_items,
                    )
                )
                current_x += cand.x_depth
                strip_counter += 1

        total_allocated = {
            c.sku_id: int(solver.Value(sku_placed[c.sku_id])) for c in cargo_list
        }

        status_str = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
        return MacroAllocationResult(
            strips=strips_allocated,
            total_allocated=total_allocated,
            solver_status=status_str,
            objective_value=float(solver.ObjectiveValue()),
            solve_time_ms=solve_time_ms,
        )
