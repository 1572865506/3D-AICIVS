from dataclasses import dataclass,replace
from typing import Tuple
from backend.solver_v2.domain.models import BoxDim,CargoSKU,ContainerSpec,QuantityPlan
from src.constraints.wall.optimization import WallOptimizationEngine,WallOptimizationResult

@dataclass(frozen=True)
class PreparedOptimizationInput:
    solver_container:ContainerSpec
    solver_cargo:Tuple[CargoSKU,...]
    result:WallOptimizationResult
    x_offset:float

class WallOptimizationAdapter:
    def __init__(self,engine=None):self.engine=engine or WallOptimizationEngine()
    @staticmethod
    def _reserve(cargo,used):
        result=[]
        for sku in cargo:
            left=max(0,sku.quantity.required-int(used.get(sku.sku_id,0)))
            result.append(replace(sku,quantity=QuantityPlan(left,min(sku.quantity.min_quantity,left),left,sku.quantity.is_elastic)))
        return tuple(result)
    def prepare(self,wall_prepared,door_prepared):
        result=self.engine.optimize(wall_prepared.plan,wall_prepared.solver_cargo,wall_prepared.original_container,door_prepared.door_wall)
        if result.status!="READY":raise ValueError("WALL_OPTIMIZATION_FAILED")
        residual=max(.001,wall_prepared.original_container.Lx-result.optimized_wall_end_x)
        container=replace(wall_prepared.original_container,code=f"{wall_prepared.original_container.code}-OPT-RESIDUAL",inner_dim=BoxDim(residual,wall_prepared.original_container.Ly,wall_prepared.original_container.Lz))
        return PreparedOptimizationInput(container,self._reserve(wall_prepared.solver_cargo,result.consumed_inventory),result,result.optimized_wall_end_x)
