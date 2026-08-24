from dataclasses import replace
from typing import Iterable, Tuple

from backend.solver_v2.domain.models import BoxDim, CargoSKU, ContainerSpec, Orientation3D, Placement, PlacementContext, Point3D, QuantityPlan
from src.constraints.door import DoorSafetyConfig, DoorSafetyEngine
from .ReservedRegionManager import ReservedRegionManager
from .types import DoorAnchor, PreparedPackingInput, ReservedRegion, SolverDoorContext


class DoorConstraintAdapter:
    """Converts pre-packing policy output into a frozen-core solver envelope."""

    def __init__(self, engine: DoorSafetyEngine = None):
        self.engine = engine or DoorSafetyEngine(DoorSafetyConfig.formation_v2())

    @staticmethod
    def _placement(raw, concrete_orientation: str) -> Placement:
        return Placement(
            placement_id=raw.placement_id, instance_id=raw.placement_id, sku_id=raw.sku_id,
            position=Point3D(raw.x, raw.y, raw.z),
            orientation=Orientation3D(raw.dx, raw.dy, raw.dz, concrete_orientation, is_upright=True),
            weight_kg=raw.weight_kg, context=PlacementContext.DOOR_SEAL, step_index=raw.layer,
        )

    @staticmethod
    def _reserve_inventory(cargo: Tuple[CargoSKU, ...], reservations) -> Tuple[CargoSKU, ...]:
        result = []
        for sku in cargo:
            remaining = max(0, sku.quantity.required - int(reservations.get(sku.sku_id, 0)))
            quantity = QuantityPlan(
                required=remaining, min_quantity=min(sku.quantity.min_quantity, remaining),
                max_quantity=remaining, is_elastic=sku.quantity.is_elastic,
            )
            result.append(replace(sku, quantity=quantity))
        return tuple(result)

    def prepare(self, container: ContainerSpec, cargo: Iterable[CargoSKU]) -> PreparedPackingInput:
        cargo_tuple = tuple(cargo)
        plan = self.engine.plan(container, cargo_tuple)
        if plan.status != "READY" or plan.wall is None:
            raise ValueError(f"{plan.reason}: {plan.detail}")
        anchors = tuple(self._placement(p,p.concrete_orientation) for p in plan.wall.placements)
        # Only the anchored blocking wall and its small door-side restraint gap
        # are unavailable to ordinary cargo. The rest of the semantic Door Zone
        # remains packable from the inside, eliminating the former 1.2 m void.
        region = ReservedRegion("DOOR_WALL_AND_CLEARANCE_RESERVED", plan.wall.anchor_x, plan.zone.solver_end_x)
        anchor = DoorAnchor(plan.wall.wall_id, tuple(p.placement_id for p in anchors))
        context = SolverDoorContext(
            plan.zone, anchors, dict(plan.constraints.forced_orientation), region,
            anchors, tuple(plan.constraints.priority_cargo), anchor,
        )
        solver_container = replace(
            container, code=f"{container.code}-MAIN",
            inner_dim=BoxDim(plan.wall.anchor_x, container.Ly, container.Lz),
        )
        solver_cargo = self._reserve_inventory(cargo_tuple, plan.constraints.inventory_reservation)
        return PreparedPackingInput(container, solver_container, cargo_tuple, solver_cargo, context, plan.wall)
