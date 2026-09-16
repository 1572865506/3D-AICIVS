"""
CP-SAT Hybrid Three-Stage 3D Packing Solver (Solver V2).

Pipeline:
  Stage 1: CP-SAT Macro Strip Allocation (cpsat_engine.py)
  Stage 2: Constructive Micro-Placer (constructive_placer.py)
  Stage 3: Large Neighborhood Search Local Optimization (lns_optimizer.py)
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from backend.solver_v2.domain.models import (
    BoxDim,
    CargoSKU,
    ContainerSpec,
    Orientation3D,
    Placement,
    PlacementContext,
    Point3D,
    UniversalCargoTensor,
    UniversalZone,
    ZoneType,
    PackingRole,
)
from backend.solver_v2.solver.baseline_solver import SolverSolution, SolverTelemetry
from backend.solver_v2.solver.constructive_placer import ConstructivePlacer
from backend.solver_v2.solver.cpsat_engine import CPSATMacroAllocator
from backend.solver_v2.solver.lns_optimizer import LNSOptimizer
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator


class CPSATHybridSolver:
    """
    CP-SAT Hybrid Three-Stage Solver.
    Fully compatible interface with UnifiedSolver.
    """

    GLOBAL_TIMEOUT_SECONDS = 300.0

    def __init__(self, container: Optional[ContainerSpec] = None):
        if container is not None:
            self.container = container
        else:
            self.container = ContainerSpec(
                code="40HQ",
                inner_dim=BoxDim(12.024, 2.350, 2.690),
                max_payload_kg=26000.0,
            )
        self.cL = round(self.container.Lx, 4)
        self.cW = round(self.container.Ly, 4)
        self.cH = round(self.container.Lz, 4)

    def solve(
        self,
        cargo_list: List[CargoSKU],
        options: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> SolverSolution:
        t0 = time.perf_counter()
        options = dict(options or {})
        options.update(kwargs)
        timeout = float(options.get("timeout", options.get("time_budget", self.GLOBAL_TIMEOUT_SECONDS)))

        if not cargo_list:
            val_result = IndependentGlobalValidator.validate(self.container, [], cargo_list)
            return SolverSolution(
                status="SUCCESS",
                container=self.container,
                placements=[],
                placed_count=0,
                unplaced_count=0,
                volume_utilization_pct=0.0,
                total_weight_kg=0.0,
                validation_result=val_result,
                telemetry=SolverTelemetry(runtime_ms=0.0),
            )

        # 1. Convert CargoSKU -> UniversalCargoTensor
        tensors = self._convert_to_tensors(cargo_list)

        # 2. Phase 1: CP-SAT Macro Strip Allocation
        phase1_time = min(60.0, timeout * 0.4)
        allocator = CPSATMacroAllocator(self.container)
        allocation = allocator.solve(tensors, time_limit_seconds=phase1_time)

        # 3. Phase 2: Constructive Micro-Placer
        placer = ConstructivePlacer(self.container)
        placements = placer.place(allocation, tensors)

        # 4. Phase 3: LNS Optimization
        elapsed = time.perf_counter() - t0
        remaining_time = timeout - elapsed
        if remaining_time > 15.0 and placements:
            optimizer = LNSOptimizer(self.container)
            placements = optimizer.optimize(
                placements,
                tensors,
                remaining_time_seconds=remaining_time - 5.0,
                max_iterations=15,
            )

        # 5. Independent validation
        validation_result = IndependentGlobalValidator.validate(
            self.container,
            placements,
            cargo_list,
        )

        total_time_ms = (time.perf_counter() - t0) * 1000.0
        total_vol = sum(p.volume for p in placements)
        total_weight = sum(p.weight_kg for p in placements)
        total_req = sum(c.quantity.required for c in cargo_list)

        status_str = "SUCCESS" if (validation_result.is_valid and len(placements) == total_req) else (
            "VALID_PARTIAL" if validation_result.is_valid else "INVALID"
        )

        return SolverSolution(
            status=status_str,
            container=self.container,
            placements=placements,
            placed_count=len(placements),
            unplaced_count=max(0, total_req - len(placements)),
            volume_utilization_pct=round(total_vol / max(1e-6, self.container.volume) * 100.0, 4),
            total_weight_kg=round(total_weight, 2),
            validation_result=validation_result,
            telemetry=SolverTelemetry(
                runtime_ms=round(total_time_ms, 2),
                steps_committed=len(placements),
                phases_completed=["CPSAT_MACRO", "CONSTRUCTIVE", "LNS"],
            ),
        )

    def _convert_to_tensors(self, cargo_list: List[CargoSKU]) -> List[UniversalCargoTensor]:
        tensors: List[UniversalCargoTensor] = []
        for s in cargo_list:
            req = s.source_requirement_text or ""
            zp = UniversalZone.MIDDLE
            if s.target_zone == ZoneType.REAR or "最里面" in req or "里面" in req or "内" in req:
                zp = UniversalZone.INNER
            elif (
                s.target_zone == ZoneType.DOOR
                or PackingRole.DOOR_SEAL in s.packing_roles
                or "封柜门" in req
                or "封门" in req
                or "门" in req
            ):
                zp = UniversalZone.DOOR

            allow_flat = s.orientation_policy.allow_flat
            allow_side = s.orientation_policy.allow_side
            max_stack = s.stacking_policy.max_stack_layers
            must_be_on_floor = getattr(s.stacking_policy, "must_be_on_floor", False)
            is_elastic = getattr(s.quantity, "is_elastic", False) or "可以减少" in req or "可减少" in req or "少放" in req

            t = UniversalCargoTensor(
                sku_id=s.sku_id,
                name=s.name,
                length=s.box.x,
                width=s.box.y,
                height=s.box.z,
                weight_kg=s.weight_kg,
                quantity_required=s.quantity.required,
                zone_preference=zp,
                allow_flat=allow_flat,
                allow_side=allow_side,
                max_stack_layers=max_stack,
                must_be_on_floor=must_be_on_floor,
                raw_requirement=req,
                is_elastic=is_elastic,
            )
            setattr(t, "allow_stacking_on_top", getattr(s.stacking_policy, "allow_stacking_on_top", True))
            setattr(t, "max_bearing_kg", getattr(s.stacking_policy, "max_bearing_kg", None))
            setattr(t, "sku_obj", s)
            tensors.append(t)
        return tensors
