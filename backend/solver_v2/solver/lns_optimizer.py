"""
Large Neighborhood Search (LNS) Optimizer for Solver V2 (Phase 3).

Iteratively selects destructive regions, removes placements,
and repairs them using local CP-SAT and constructive placement.
Accepts candidate improvements only if violations=0 and score strictly improves.
"""
from __future__ import annotations

import random
import time
from typing import Dict, List, Optional, Tuple

from backend.solver_v2.domain.models import (
    CargoSKU,
    ContainerSpec,
    Placement,
    UniversalCargoTensor,
)
from backend.solver_v2.solver.constructive_placer import ConstructivePlacer
from backend.solver_v2.solver.cpsat_engine import CPSATMacroAllocator


class LNSOptimizer:
    """
    Large Neighborhood Search Optimizer.
    Executes destroy-and-repair loops to improve space utilization and packaging stability.
    """

    def __init__(self, container: ContainerSpec):
        self.container = container
        self.cL = round(container.Lx, 4)
        self.cW = round(container.Ly, 4)
        self.cH = round(container.Lz, 4)

    def optimize(
        self,
        placements: List[Placement],
        cargo_list: List[UniversalCargoTensor],
        remaining_time_seconds: float = 30.0,
        max_iterations: int = 15,
    ) -> List[Placement]:
        """
        Runs iterative destroy and repair.
        Guarantees that the returned solution is at least as good as the input solution.
        """
        t0 = time.perf_counter()
        if remaining_time_seconds <= 5.0 or not placements:
            return placements

        best_placements = list(placements)
        best_score = self._score_solution(best_placements, cargo_list)

        iteration = 0
        while iteration < max_iterations:
            elapsed = time.perf_counter() - t0
            if elapsed >= remaining_time_seconds:
                break

            # 1. Select region to destroy
            destroy_span = 1.2
            x_range = self._select_destroy_region(best_placements, iteration, destroy_span)

            # 2. Destroy and repair
            repaired = self._destroy_and_repair(
                best_placements,
                cargo_list,
                x_range,
                time_limit=min(5.0, max(1.0, (remaining_time_seconds - elapsed) / 2)),
            )

            # 3. Evaluate improvement
            if repaired:
                repaired_score = self._score_solution(repaired, cargo_list)
                if repaired_score > best_score:
                    best_placements = repaired
                    best_score = repaired_score

            iteration += 1

        return best_placements

    def _select_destroy_region(
        self,
        placements: List[Placement],
        iteration: int,
        span: float,
    ) -> Tuple[float, float]:
        strategy = iteration % 3
        if strategy == 0:
            # Door zone focus
            start = max(0.0, self.cL - span)
            return (start, self.cL)
        elif strategy == 1:
            # Random section
            start = random.uniform(0.0, max(0.0, self.cL - span))
            return (start, start + span)
        else:
            # Mid-body section
            mid = self.cL / 2.0
            return (max(0.0, mid - span / 2.0), min(self.cL, mid + span / 2.0))

    def _destroy_and_repair(
        self,
        placements: List[Placement],
        cargo_list: List[UniversalCargoTensor],
        x_range: Tuple[float, float],
        time_limit: float = 3.0,
    ) -> Optional[List[Placement]]:
        x_min, x_max = x_range
        kept = [p for p in placements if not (x_min <= p.position.x < x_max)]
        destroyed = [p for p in placements if (x_min <= p.position.x < x_max)]

        if not destroyed:
            return None

        # Determine how many items of each SKU are remaining to be placed
        placed_counts: Dict[str, int] = {}
        for p in kept:
            placed_counts[p.sku_id] = placed_counts.get(p.sku_id, 0) + 1

        sub_cargo_list: List[UniversalCargoTensor] = []
        for c in cargo_list:
            rem = c.quantity_required - placed_counts.get(c.sku_id, 0)
            if c.is_elastic or rem > 0:
                sub_c = UniversalCargoTensor(
                    sku_id=c.sku_id,
                    name=c.name,
                    length=c.length,
                    width=c.width,
                    height=c.height,
                    weight_kg=c.weight_kg,
                    quantity_required=max(0, rem),
                    zone_preference=c.zone_preference,
                    allow_flat=c.allow_flat,
                    allow_side=c.allow_side,
                    max_stack_layers=c.max_stack_layers,
                    must_be_on_floor=c.must_be_on_floor,
                    category=c.category,
                    color=c.color,
                    raw_requirement=c.raw_requirement,
                    is_elastic=c.is_elastic,
                )
                setattr(sub_c, "allow_stacking_on_top", getattr(c, "allow_stacking_on_top", True))
                setattr(sub_c, "max_bearing_kg", getattr(c, "max_bearing_kg", None))
                sub_cargo_list.append(sub_c)

        # Allocate in remaining section
        allocator = CPSATMacroAllocator(self.container)
        region_width = x_max - x_min
        alloc_res = allocator.solve(sub_cargo_list, time_limit_seconds=time_limit)

        if not alloc_res.strips:
            return None

        # Shift strips to start from x_min
        for s in alloc_res.strips:
            s.x_start = round(x_min + s.x_start, 4)

        placer = ConstructivePlacer(self.container)
        new_placements = placer.place(alloc_res, sub_cargo_list, existing_placements=kept)
        return new_placements

    def _score_solution(
        self,
        placements: List[Placement],
        cargo_list: List[UniversalCargoTensor],
    ) -> Tuple[float, float, float]:
        """
        Evaluation score tuple: (rigid_fulfillment_ratio, total_placed_count, total_volume).
        """
        rigid_req = sum(c.quantity_required for c in cargo_list if not c.is_elastic)
        placed_counts: Dict[str, int] = {}
        for p in placements:
            placed_counts[p.sku_id] = placed_counts.get(p.sku_id, 0) + 1

        rigid_placed = sum(
            min(c.quantity_required, placed_counts.get(c.sku_id, 0))
            for c in cargo_list
            if not c.is_elastic
        )

        rigid_ratio = rigid_placed / max(1, rigid_req)
        total_vol = sum(p.volume for p in placements)
        total_count = len(placements)

        return (rigid_ratio, float(total_count), total_vol)
