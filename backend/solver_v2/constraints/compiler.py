"""
Solver V2 Constraint Compiler
Translates ingested/normalized business options and SKU specifications into structured constraints.
"""
from typing import List, Dict, Any, Tuple, Optional
from backend.solver_v2.domain.models import (
    CargoSKU,
    ContainerSpec,
    ZoneType,
    PackingRole,
    PlacementRuleMode,
)
from backend.solver_v2.constraints.rules import (
    ZoneConstraint,
    DoorZoneConstraint,
    StackLimitConstraint,
    BearingConstraint,
    PressureConstraint,
    SupportRatioConstraint,
)


class ConstraintCompiler:
    """
    Compiles canonical CargoSKUs and ContainerSpec into executable constraint sets.
    """

    @staticmethod
    def compile_all(container: ContainerSpec, cargo_list: List[CargoSKU]) -> Dict[str, Any]:
        """
        Compiles the entire constraint collection for a packing problem.
        """
        door_exempt_skus = set()
        zone_constraints: Dict[str, ZoneConstraint] = {}
        stack_constraints: Dict[str, StackLimitConstraint] = {}
        bearing_constraints: Dict[str, BearingConstraint] = {}
        pressure_constraints: Dict[str, PressureConstraint] = {}
        support_constraints: Dict[str, SupportRatioConstraint] = {}

        for cargo in cargo_list:
            sku = cargo.sku_id

            # Door zone exemption (SKUs with PackingRole.DOOR_SEAL or target_zone == ZoneType.DOOR)
            if (PackingRole.DOOR_SEAL in cargo.packing_roles) or (cargo.target_zone == ZoneType.DOOR):
                door_exempt_skus.add(sku)

            # Zone constraint (preferential loading guidance)
            if cargo.target_zone:
                zone_constraints[sku] = ZoneConstraint(
                    sku_id=sku,
                    allowed_zones=(cargo.target_zone,),
                    mode=PlacementRuleMode.PREFER
                )

            # Stacking limits
            if cargo.stacking_policy.max_stack_layers is not None:
                stack_constraints[sku] = StackLimitConstraint(
                    sku_id=sku,
                    max_layers=cargo.stacking_policy.max_stack_layers,
                    mode=PlacementRuleMode.REQUIRED
                )

            # Bearing weight limits
            if cargo.stacking_policy.max_bearing_kg is not None and cargo.stacking_policy.max_bearing_kg > 0:
                bearing_constraints[sku] = BearingConstraint(
                    sku_id=sku,
                    max_bearing_kg=cargo.stacking_policy.max_bearing_kg,
                    mode=PlacementRuleMode.REQUIRED
                )

            # Pressure limits
            if cargo.stacking_policy.max_pressure_kg_m2 is not None and cargo.stacking_policy.max_pressure_kg_m2 > 0:
                pressure_constraints[sku] = PressureConstraint(
                    sku_id=sku,
                    max_pressure_kg_m2=cargo.stacking_policy.max_pressure_kg_m2,
                    mode=PlacementRuleMode.REQUIRED
                )

            # Support ratio
            support_constraints[sku] = SupportRatioConstraint(
                sku_id=sku,
                min_ratio=cargo.stacking_policy.min_support_ratio,
                max_unsupported_span_m=cargo.stacking_policy.max_unsupported_span_m,
                mode=PlacementRuleMode.REQUIRED
            )

        door_constraint = DoorZoneConstraint(
            door_zone_length_m=container.door_zone_length_m,
            exempt_skus=door_exempt_skus
        )

        return {
            "door_zone": door_constraint,
            "zones": zone_constraints,
            "stack_limits": stack_constraints,
            "bearing_limits": bearing_constraints,
            "pressure_limits": pressure_constraints,
            "support_limits": support_constraints,
        }
