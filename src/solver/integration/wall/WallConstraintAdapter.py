from dataclasses import dataclass, replace
from typing import Tuple

from backend.solver_v2.domain.models import BoxDim, CargoSKU, ContainerSpec, Placement, Point3D, QuantityPlan, ZoneType
from src.constraints.wall import CargoWallEngine, CargoWallPlan


@dataclass(frozen=True)
class PreparedWallInput:
    original_container: ContainerSpec
    solver_container: ContainerSpec
    original_cargo: Tuple[CargoSKU,...]
    solver_cargo: Tuple[CargoSKU,...]
    plan: CargoWallPlan
    x_offset: float


class WallConstraintAdapter:
    def __init__(self,engine=None):self.engine=engine or CargoWallEngine()

    @staticmethod
    def _reserve(cargo,reservations):
        result=[]
        for sku in cargo:
            left=max(0,sku.quantity.required-int(reservations.get(sku.sku_id,0)))
            # A residual-local x=0 becomes an absolute mid-container coordinate
            # after translation. Rear-required inventory therefore cannot be
            # delegated to that solver space without violating its hard zone.
            if sku.target_zone == ZoneType.REAR:
                left=0
            q=QuantityPlan(left,min(sku.quantity.min_quantity,left),left,sku.quantity.is_elastic)
            result.append(replace(sku,quantity=q))
        return tuple(result)

    def prepare(self,container,cargo,allow_fallback=True)->PreparedWallInput:
        cargo=tuple(cargo);plan=self.engine.plan(container,cargo)
        if plan.status!="READY":
            if not allow_fallback:
                raise ValueError("CARGO_WALL_PLAN_INVALID")
            return None
        residual=max(0.001,container.Lx-plan.build.wall_end_x)
        solver_container=replace(container,code=f"{container.code}-RESIDUAL",inner_dim=BoxDim(residual,container.Ly,container.Lz))
        return PreparedWallInput(container,solver_container,cargo,self._reserve(cargo,plan.build.consumed_inventory),plan,plan.build.wall_end_x)

    @staticmethod
    def shift_residual(placements,x_offset):
        return tuple(replace(p,position=Point3D(round(p.position.x+x_offset,6),p.position.y,p.position.z),
                             step_index=p.step_index) for p in placements)
