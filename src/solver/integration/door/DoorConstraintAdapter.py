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
        
        # Adaptive check: Only anchor a fixed door wall if cargo naturally reaches the door zone.
        # Otherwise, cargo (including door-seal capable SKUs) should pack continuously inside.
        total_volume = sum(sku.box.x * sku.box.y * sku.box.z * sku.quantity.required for sku in cargo_tuple)
        container_cross_section = container.Ly * container.Lz
        estimated_load_length = total_volume / max(container_cross_section * 0.70, 1e-6)
        door_zone_threshold = plan.zone.solver_start_x * 0.75 if (plan.zone and plan.zone.solver_start_x > 0) else (container.Lx * 0.75)
        reaches_door_zone = estimated_load_length >= door_zone_threshold

        if plan.status != "READY" or plan.wall is None or not reaches_door_zone:
            region = ReservedRegion("NO_DOOR_RESERVED", container.Lx, container.Lx)
            anchor = DoorAnchor("", ())
            context = SolverDoorContext(
                plan.zone, (), dict(plan.constraints.forced_orientation) if plan.constraints else {},
                region, (), (), anchor,
            )
            return PreparedPackingInput(container, container, cargo_tuple, cargo_tuple, context, None)
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
