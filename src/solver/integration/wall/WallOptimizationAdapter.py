from dataclasses import dataclass,replace
from typing import Any,Dict,Optional,Tuple
from backend.solver_v2.domain.models import BoxDim,CargoSKU,ContainerSpec,PackingRole,QuantityPlan,ZoneType
from src.constraints.door import TransportForceDirectionModel
from src.constraints.wall.optimization import WallOptimizationEngine,WallOptimizationResult

@dataclass(frozen=True)
class PreparedOptimizationInput:
    solver_container:ContainerSpec
    solver_cargo:Tuple[CargoSKU,...]
    result:WallOptimizationResult
    x_offset:float

class WallOptimizationAdapter:
    def __init__(self,engine=None):
        self.engine=engine or WallOptimizationEngine()
        self.last_result:Optional[WallOptimizationResult]=None
        self.last_diagnostic:Optional[Dict[str,Any]]=None
    @staticmethod
    def _reserve(cargo,used):
        result=[]
        for sku in cargo:
            left=max(0,sku.quantity.required-int(used.get(sku.sku_id,0)))
            result.append(replace(sku,quantity=QuantityPlan(left,min(sku.quantity.min_quantity,left),left,sku.quantity.is_elastic)))
        return tuple(result)
    def _optimize(self,wall_prepared,door_prepared):
        result=self.engine.optimize(wall_prepared.plan,wall_prepared.solver_cargo,wall_prepared.original_container,door_prepared.door_wall)
        self.last_result=result
        door_anchor_x=min((p.x for p in door_prepared.door_wall.placements),default=wall_prepared.original_container.Lx)
        transition_placements=tuple(p for wall in result.transition_walls for p in wall.placements)
        anchor_validation=(TransportForceDirectionModel().evaluate(
            door_prepared.door_wall,wall_prepared.original_container,
            transition_placements,require_actual_back_anchor=True) if transition_placements else None)
        back_axis=next((axis for axis in anchor_validation.axes if axis.vector=="-X"),None) if anchor_validation else None
        door_back_anchor_ready=bool(back_axis and back_axis.valid)
        reasons=[]
        if not result.transition_walls:reasons.append("NO_TRANSITION_WALL")
        if not result.chain.valid:reasons.append("WALL_CHAIN_INVALID")
        anchor_start=min((p.min_x for p in transition_placements),default=result.optimized_wall_end_x)
        remaining_gap=(max(0.0,anchor_start-result.original_wall_end_x) if transition_placements
                       else max(0.0,door_anchor_x-result.optimized_wall_end_x))
        if remaining_gap>.03:reasons.append("TRANSITION_GAP_EXCEEDS_LIMIT")
        admitted=result.status=="READY" or door_back_anchor_ready
        self.last_diagnostic={
            "attempted":True,
            "status":result.status,
            "admitted":admitted,
            "admission_mode":"FULL_TRANSITION_CHAIN" if result.status=="READY" else "DOOR_BACK_ANCHOR_ONLY" if door_back_anchor_ready else "CARGO_WALL_FORMATION_FALLBACK",
            "fallback":None if admitted else "CARGO_WALL_FORMATION",
            "reasons":reasons or (["ENGINE_NOT_READY"] if result.status!="READY" else []),
            "transition_wall_count":len(result.transition_walls),
            "wall_chain_valid":result.chain.valid,
            "door_back_anchor_ready":door_back_anchor_ready,
            "door_back_anchor_coverage":back_axis.restraint_coverage if back_axis else 0.0,
            "optimized_wall_end_x":result.optimized_wall_end_x,
            "door_anchor_x":door_anchor_x,
            "remaining_transition_gap_m":remaining_gap,
        }
        return result

    def _prepare_result(self,wall_prepared,result):
        residual=max(.001,wall_prepared.original_container.Lx-result.optimized_wall_end_x)
        container=replace(wall_prepared.original_container,code=f"{wall_prepared.original_container.code}-OPT-RESIDUAL",inner_dim=BoxDim(residual,wall_prepared.original_container.Ly,wall_prepared.original_container.Lz))
        return PreparedOptimizationInput(container,self._reserve(wall_prepared.solver_cargo,result.consumed_inventory),result,result.optimized_wall_end_x)

    def _prepare_anchor_result(self,wall_prepared,result):
        anchor_placements=tuple(p for wall in result.transition_walls for p in wall.placements)
        anchor_start=min(p.min_x for p in anchor_placements)
        residual=max(.001,anchor_start-result.original_wall_end_x)
        container=replace(wall_prepared.original_container,code=f"{wall_prepared.original_container.code}-ANCHOR-RESIDUAL",
            inner_dim=BoxDim(residual,wall_prepared.original_container.Ly,wall_prepared.original_container.Lz))
        reserved=self._reserve(wall_prepared.solver_cargo,result.consumed_inventory)
        # Door-only tail units cannot be delegated into the central residual
        # coordinate frame: that would either violate their required door zone
        # or collide with the frozen back-anchor wall.
        solver_cargo=[]
        for sku in reserved:
            if sku.target_zone==ZoneType.DOOR or (PackingRole.DOOR_SEAL in sku.packing_roles and PackingRole.MAIN_WALL not in sku.packing_roles):
                sku=replace(sku,quantity=QuantityPlan(0,0,0,sku.quantity.is_elastic))
            solver_cargo.append(sku)
        return PreparedOptimizationInput(container,tuple(solver_cargo),result,result.original_wall_end_x)

    def prepare(self,wall_prepared,door_prepared):
        """Strict BLK-007F2 entry point retained for its direct acceptance tests."""
        result=self._optimize(wall_prepared,door_prepared)
        if result.status!="READY":raise ValueError("WALL_OPTIMIZATION_FAILED")
        return self._prepare_result(wall_prepared,result)

    def try_prepare(self,wall_prepared,door_prepared):
        """Admit the optional optimization only when it produced a complete wall chain.

        A cargo manifest can be physically valid while lacking the inventory needed for
        a transition wall.  In that case the production orchestrator keeps the already
        validated BLK-007F1 wall plan and still runs all final hard validators.
        """
        result=self._optimize(wall_prepared,door_prepared)
        if result.status!="READY":
            if self.last_diagnostic and self.last_diagnostic["door_back_anchor_ready"]:
                return self._prepare_anchor_result(wall_prepared,result)
            return None
        return self._prepare_result(wall_prepared,result)
