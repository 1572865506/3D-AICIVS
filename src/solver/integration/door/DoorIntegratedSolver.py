import time
from dataclasses import dataclass, replace
from typing import Any, Dict, Optional

from backend.solver_v2.solver.baseline_solver import SolverSolution
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from .types import PreparedPackingInput
from .DoorConstraintAdapter import DoorConstraintAdapter
from .DoorWallCommitter import DoorWallCommitter
from src.solver.integration.wall import WallConstraintAdapter,WallOptimizationAdapter
from src.solver.integration.topfill import TopFillOptimizationAdapter
from src.solver.integration.layer import LayerOptimizationAdapter
from src.cargo.intelligence import CargoConstraintAdapter
from src.optimization.direction import DirectionConstraintAdapter, LoadingDirectionEngine
from src.optimization.global_rebuild import GlobalLayoutRebuildEngine, RebuildController
from src.optimization.wall_repacking import WallInternalRepackingEngine, WallRebuildAdapter
from src.optimization.cargo_recomposition import TrueCargoRecompositionEngine
from src.solver.integration.residual import ResidualFillingAdapter
from src.constraints.door import SHORT_EDGE_FORWARD, TransportForceDirectionModel
from src.constraints.door.types import DoorWallPlacement
from src.constraints.wall.optimization import WallInterfaceRepairEngine
from src.optimization.multisku_wall import MultiSkuWallRecompositionEngine,ThreeDLayerRecompositionEngine


@dataclass(frozen=True)
class DoorIntegrationDiagnostics:
    door_wall_committed: bool
    door_wall_count: int
    door_zone_reserved: bool
    door_orientation_valid: bool
    locked_count: int
    support_links: int
    main_solver_max_x: float
    solver_commit_sequence: tuple
    physical_sequence_policy: str
    cargo_wall_count: int = 0
    cargo_wall_placements: int = 0
    cargo_wall_end_x: float = 0.0
    transition_wall_count: int = 0
    optimized_wall_end_x: float = 0.0
    wall_chain_valid: bool = False
    top_fill_placements: int = 0
    top_fill_volume: float = 0.0
    top_fill_max_layers: int = 0
    layer_optimization_placements: int = 0
    layer_optimization_ready: bool = False
    door_seal_coverage: float = 0.0
    loading_direction_ready: bool = False
    display_direction_valid: bool = False
    global_rebuild_ready: bool = False
    rebuilt_layout_id: str = ""
    rebuilt_global_score: float = 0.0
    true_recomposition_ready: bool = False
    recomposition_changed_count: int = 0
    recomposition_changed_ratio: float = 0.0
    recomposition_score: float = 0.0
    wall_internal_repack_ready: bool = False
    wall_internal_gap_reduction_m: float = 0.0
    display_wall_continuity: float = 0.0
    cargo_intelligence_ready: bool = False
    door_plane_clearance_m: float = 0.0
    door_area_coverage: float = 0.0
    transport_stable: bool = False
    residual_fill_placements: int = 0
    residual_fill_volume: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


class DoorIntegratedSolver:
    """Pre/commit orchestration around an unchanged solver implementation."""

    def __init__(self, solver, adapter: Optional[DoorConstraintAdapter] = None, wall_adapter=None, enable_cargo_walls=False,
                 optimization_adapter=None,enable_wall_optimization=False, layer_adapter=None):
        self.solver = solver
        self.adapter = adapter or DoorConstraintAdapter()
        self.wall_adapter = wall_adapter or WallConstraintAdapter()
        self.enable_cargo_walls = enable_cargo_walls
        self.optimization_adapter=optimization_adapter or WallOptimizationAdapter()
        self.enable_wall_optimization=enable_wall_optimization
        self.topfill_adapter=TopFillOptimizationAdapter()
        self.layer_adapter=layer_adapter or LayerOptimizationAdapter()
        self.intelligence_adapter=CargoConstraintAdapter()
        self.direction_engine=LoadingDirectionEngine()
        self.direction_adapter=DirectionConstraintAdapter()
        self.enable_direction_strategy=False
        self.rebuild_engine=GlobalLayoutRebuildEngine()
        self.rebuild_controller=RebuildController("NORMAL")
        self.wall_repack_adapter=WallRebuildAdapter(WallInternalRepackingEngine())
        self.recomposition_engine=TrueCargoRecompositionEngine()
        self.enable_cargo_recomposition=False
        self.enable_dimension_corrected_rebuild=False
        self.enable_wall_internal_repack=False
        self.enable_topfill_optimization=False
        self.enable_layer_optimization=False
        self.enable_residual_filling=False
        self.residual_adapter=ResidualFillingAdapter()
        self.enable_wall_interface_repair=False
        self.wall_interface_repair_engine=WallInterfaceRepairEngine()
        self.enable_multisku_wall_recomposition=False
        self.multisku_wall_engine=MultiSkuWallRecompositionEngine()
        self.enable_3d_layer_recomposition=False
        self.layer_recomposition_engine=ThreeDLayerRecompositionEngine()
        self.last_prepared = None
        self.last_wall_prepared = None
        self.last_optimization_prepared = None
        self.last_wall_optimization_attempt = None
        self.last_topfill_prepared = None
        self.last_layer_prepared = None
        self.last_cargo_intelligence = None
        self.last_direction_plan = None
        self.last_rebuild_result = None
        self.last_recomposition_result = None
        self.last_wall_repack_result = None
        self.last_transport_validation = None
        self.last_residual_prepared = None
        self.last_wall_interface_repair = None
        self.last_multisku_wall_recomposition = None
        self.last_3d_layer_recomposition = None
        self.last_final_placements = None
        self.last_structural_lock_rejections = []

    def with_topfill_optimization(self,enabled=True):
        self.enable_topfill_optimization=enabled
        return self

    def with_layer_optimization(self, enabled=True):
        self.enable_layer_optimization = enabled
        return self

    def with_direction_strategy(self, enabled=True):
        self.enable_direction_strategy = enabled
        return self

    def with_global_rebuild(self, mode="REBUILD"):
        self.rebuild_controller=RebuildController(mode)
        return self

    def with_wall_internal_repack(self,enabled=True):
        self.enable_wall_internal_repack=enabled
        return self

    def with_cargo_recomposition(self,enabled=True):
        self.enable_cargo_recomposition=enabled
        return self

    def with_dimension_corrected_rebuild(self,enabled=True):
        """Rebuild MAIN first, then recompute Layer and Top Fill from new walls."""
        self.enable_dimension_corrected_rebuild=enabled
        return self

    def with_residual_filling(self,enabled=True):
        self.enable_residual_filling=enabled
        return self

    def with_wall_interface_repair(self,enabled=True):
        self.enable_wall_interface_repair=enabled
        return self

    def with_multisku_wall_recomposition(self,enabled=True):
        self.enable_multisku_wall_recomposition=enabled
        return self

    def with_3d_layer_recomposition(self,enabled=True):
        self.enable_3d_layer_recomposition=enabled
        return self

    @staticmethod
    def _refresh_wall_geometry(optimization_prepared,placements):
        if not optimization_prepared:return optimization_prepared
        by_id={p.placement_id:p for p in placements}
        def refresh(wall):
            current=tuple(by_id.get(p.placement_id,p) for p in wall.placements)
            if hasattr(wall,"x_range"):
                return replace(wall,placements=current,x_range=(min((p.min_x for p in current),default=0),max((p.max_x for p in current),default=0)))
            return replace(wall,placements=current)
        result=optimization_prepared.result
        refreshed=replace(result,optimized_walls=tuple(refresh(w) for w in result.optimized_walls),
            transition_walls=tuple(refresh(w) for w in result.transition_walls),
            expanded_placements=tuple(by_id.get(p.placement_id,p) for p in result.expanded_placements))
        return replace(optimization_prepared,result=refreshed)

    @staticmethod
    def _geometry_fingerprint(placement):
        return (round(placement.min_x,9),round(placement.min_y,9),round(placement.min_z,9),
                round(placement.orientation.dx,9),round(placement.orientation.dy,9),round(placement.orientation.dz,9),
                placement.orientation.name)

    def _accept_structurally_locked_stage(self,current,result,candidate,locked,stage):
        by_id={p.placement_id:p for p in candidate}
        preserved=all(pid in by_id and self._geometry_fingerprint(by_id[pid])==fingerprint
                      for pid,fingerprint in locked.items())
        if preserved:return list(candidate),result
        self.last_structural_lock_rejections.append(stage)
        try:result=replace(result,status="STRUCTURAL_LOCK_REJECTED")
        except (TypeError,ValueError):pass
        return current,result

    def solve(self, container, cargo_list, options=None) -> SolverSolution:
        started = time.perf_counter()
        intelligence=self.intelligence_adapter.prepare(cargo_list)
        self.last_cargo_intelligence=intelligence
        cargo_list=list(intelligence.cargo)
        direction_plan=None
        if self.enable_direction_strategy:
            cargo_list,direction_plan=self.direction_adapter.prepare(
                self.direction_engine,container,cargo_list,intelligence)
            cargo_list=list(cargo_list)
        prepared = self.adapter.prepare(container, cargo_list)
        self.last_prepared = prepared
        wall_prepared = self.wall_adapter.prepare(prepared.solver_container, prepared.solver_cargo) if self.enable_cargo_walls else None
        self.last_wall_prepared = wall_prepared
        optimization_prepared=None
        if wall_prepared and self.enable_wall_optimization:
            # BLK-007F2 is an optional structural enhancement.  A manifest that cannot
            # form a valid transition wall must retain the hard-valid BLK-007F1 plan,
            # rather than turning a non-applicable optimization into an HTTP 500.
            if hasattr(self.optimization_adapter,"try_prepare"):
                optimization_prepared=self.optimization_adapter.try_prepare(wall_prepared,prepared)
            else:
                optimization_prepared=self.optimization_adapter.prepare(wall_prepared,prepared)
            self.last_wall_optimization_attempt=getattr(self.optimization_adapter,"last_diagnostic",None)
        self.last_optimization_prepared=optimization_prepared
        solver_container = optimization_prepared.solver_container if optimization_prepared else wall_prepared.solver_container if wall_prepared else prepared.solver_container
        solver_cargo = optimization_prepared.solver_cargo if optimization_prepared else wall_prepared.solver_cargo if wall_prepared else prepared.solver_cargo
        main_solution = self.solver.solve(solver_container, list(solver_cargo), options=options)
        offset=optimization_prepared.x_offset if optimization_prepared else wall_prepared.x_offset if wall_prepared else 0.0
        shifted_residual = self.wall_adapter.shift_residual(main_solution.placements,offset) if offset else tuple(main_solution.placements)
        structural_main = optimization_prepared.result.expanded_placements+shifted_residual if optimization_prepared else wall_prepared.plan.build.placements+shifted_residual if wall_prepared else shifted_residual
        layer_prepared=None
        if optimization_prepared and self.enable_layer_optimization and not self.enable_dimension_corrected_rebuild:
            frozen_layout=(prepared.door_context.anchor_placements if prepared.door_context else ())+structural_main
            layer_prepared=self.layer_adapter.optimize(
                container,prepared.original_cargo,frozen_layout,optimization_prepared.result,
                prepared.door_wall,self.intelligence_adapter,intelligence)
            if layer_prepared and layer_prepared.result.status=="SUCCESS":
                structural_main=structural_main+layer_prepared.result.added_placements
        self.last_layer_prepared=layer_prepared
        topfill_prepared=None
        if optimization_prepared and self.enable_topfill_optimization and not self.enable_dimension_corrected_rebuild:
            inventory_layout=(prepared.door_context.anchor_placements if prepared.door_context else ())+structural_main
            topfill_prepared=self.topfill_adapter.optimize(container,prepared.original_cargo,inventory_layout,optimization_prepared.result.optimized_walls)
            if topfill_prepared and topfill_prepared.result.status=="SUCCESS":
                structural_main=structural_main+topfill_prepared.result.placements
        self.last_topfill_prepared=topfill_prepared
        commit = DoorWallCommitter().commit(prepared, structural_main)
        placements = list(commit.placements)

        # Comprehensive Mid-Container Void Check:
        # Ensure that from X=0.0 up to the farthest box, cargo is 100% continuous without isolated islands.
        sorted_p = sorted(placements, key=lambda p: (p.min_x, p.max_x))
        reach_x = 0.0
        has_disconnected_void = False
        for p in sorted_p:
            if p.min_x > reach_x + 0.08:
                has_disconnected_void = True
                break
            reach_x = max(reach_x, p.max_x)

        if has_disconnected_void:
            # Fallback to pure continuous packing across the entire container
            prepared = PreparedPackingInput(container, container, prepared.original_cargo, prepared.original_cargo, None, None)
            main_solution = self.solver.solve(container, list(prepared.original_cargo), options=options)
            commit = DoorWallCommitter().commit(prepared, main_solution.placements)
            placements = list(commit.placements)
        doors=tuple(p for p in placements if p.placement_id.startswith("door_pre_"))
        door_start=min((p.min_x for p in doors), default=container.Lx)
        anchor_only=bool(doors and self.last_wall_optimization_attempt and
                         self.last_wall_optimization_attempt.get("admission_mode")=="DOOR_BACK_ANCHOR_ONLY")
        anchor_ids=({p.placement_id for p in placements if not p.placement_id.startswith("door_pre_")
                     and 0.0<=door_start-p.max_x<=.010000001
                     and any(min(p.max_y,d.max_y)-max(p.min_y,d.min_y)>1e-9
                             and min(p.max_z,d.max_z)-max(p.min_z,d.min_z)>1e-9 for d in doors)}
                    if anchor_only else set())
        structural_lock_ids=set(commit.locked_ids)|anchor_ids
        structural_locks={p.placement_id:self._geometry_fingerprint(p) for p in placements
                          if p.placement_id in structural_lock_ids}
        self.last_structural_lock_rejections=[]
        rebuild_result=None
        if self.rebuild_controller.enabled:
            rebuild_result=self.rebuild_engine.rebuild(
                container,prepared.original_cargo,placements,intelligence,direction_plan,
                layer_prepared.result.door_seal["door_coverage"] if layer_prepared else 100.0,
                self.rebuild_controller.mode)
            if rebuild_result.status=="SUCCESS":
                placements,rebuild_result=self._accept_structurally_locked_stage(
                    placements,rebuild_result,rebuild_result.best_layout.placements,structural_locks,"GLOBAL_REBUILD")
        self.last_rebuild_result=rebuild_result
        recomposition_result=None
        if self.enable_cargo_recomposition:
            recomposition_result=self.recomposition_engine.recompose(
                container,prepared.original_cargo,placements,intelligence)
            if recomposition_result.status=="SUCCESS":
                placements,recomposition_result=self._accept_structurally_locked_stage(
                    placements,recomposition_result,recomposition_result.placements,structural_locks,"CARGO_RECOMPOSITION")
        self.last_recomposition_result=recomposition_result
        multisku_wall_result=None
        if self.enable_multisku_wall_recomposition:
            multisku_wall_result=self.multisku_wall_engine.recompose(
                container,prepared.original_cargo,tuple(placements),intelligence)
            if multisku_wall_result.status=="SUCCESS":
                placements,multisku_wall_result=self._accept_structurally_locked_stage(
                    placements,multisku_wall_result,multisku_wall_result.placements,structural_locks,"MULTISKU_WALL_RECOMPOSITION")
        self.last_multisku_wall_recomposition=multisku_wall_result
        layer_recomposition_result=None
        if self.enable_3d_layer_recomposition:
            layer_recomposition_result=self.layer_recomposition_engine.recompose(
                container,prepared.original_cargo,tuple(placements))
            if layer_recomposition_result.status=="SUCCESS":
                placements,layer_recomposition_result=self._accept_structurally_locked_stage(
                    placements,layer_recomposition_result,layer_recomposition_result.placements,structural_locks,"THREE_D_LAYER_RECOMPOSITION")
        self.last_3d_layer_recomposition=layer_recomposition_result
        wall_interface_repair=None
        if self.enable_wall_interface_repair:
            wall_interface_repair=self.wall_interface_repair_engine.repair(
                container,prepared.original_cargo,tuple(placements))
            if wall_interface_repair.status=="SUCCESS":
                placements,wall_interface_repair=self._accept_structurally_locked_stage(
                    placements,wall_interface_repair,wall_interface_repair.placements,structural_locks,"WALL_INTERFACE_REPAIR")
        self.last_wall_interface_repair=wall_interface_repair
        if self.enable_dimension_corrected_rebuild and optimization_prepared:
            optimization_prepared=self._refresh_wall_geometry(optimization_prepared,placements)
            self.last_optimization_prepared=optimization_prepared
            layer_prepared=None
            if self.enable_layer_optimization:
                layer_prepared=self.layer_adapter.optimize(
                    container,prepared.original_cargo,tuple(placements),optimization_prepared.result,
                    prepared.door_wall,self.intelligence_adapter,intelligence)
                if layer_prepared and layer_prepared.result.status=="SUCCESS" and layer_prepared.result.added_placements:
                    placements,layer_prepared=self._accept_structurally_locked_stage(
                        placements,layer_prepared,tuple(placements)+layer_prepared.result.added_placements,structural_locks,"LAYER_OPTIMIZATION")
            self.last_layer_prepared=layer_prepared
            topfill_prepared=None
            if self.enable_topfill_optimization:
                topfill_prepared=self.topfill_adapter.optimize(
                    container,prepared.original_cargo,tuple(placements),optimization_prepared.result.optimized_walls)
                if topfill_prepared and topfill_prepared.result.status=="SUCCESS" and topfill_prepared.result.placements:
                    placements,topfill_prepared=self._accept_structurally_locked_stage(
                        placements,topfill_prepared,tuple(placements)+topfill_prepared.result.placements,structural_locks,"TOP_FILL")
            self.last_topfill_prepared=topfill_prepared
        wall_repack_result=None
        if self.enable_wall_internal_repack:
            wall_repack_result=self.wall_repack_adapter.rebuild(
                container,prepared.original_cargo,placements,intelligence,door_start,
                rebuild_result.best_layout.score.global_score if rebuild_result else 0.0)
            if wall_repack_result.status=="SUCCESS":
                placements,wall_repack_result=self._accept_structurally_locked_stage(
                    placements,wall_repack_result,wall_repack_result.placements,structural_locks,"WALL_INTERNAL_REPACK")
        self.last_wall_repack_result=wall_repack_result
        self.last_wall_interface_repair=wall_interface_repair
        residual_prepared=None
        if self.enable_residual_filling:
            residual_prepared=self.residual_adapter.optimize(container,prepared.original_cargo,tuple(placements),intelligence)
            if residual_prepared and getattr(residual_prepared, 'result', None) and residual_prepared.result.placements:
                placements,residual_prepared=self._accept_structurally_locked_stage(
                    placements,residual_prepared,tuple(placements)+residual_prepared.result.placements,structural_locks,"RESIDUAL_FILLING")
        self.last_residual_prepared=residual_prepared
        from src.optimization.compaction import CascadeCompactionOptimizer
        compaction_result = CascadeCompactionOptimizer().optimize(
            container, prepared.original_cargo, tuple(placements), structural_lock_ids
        )
        if compaction_result.status == "SUCCESS":
            placements, compaction_result = self._accept_structurally_locked_stage(
                placements, compaction_result, compaction_result.placements, structural_locks, "CASCADE_COMPACTION"
            )
        self.last_compaction_result = compaction_result

        from src.optimization.stepping import SteppedTrailingEdgeOptimizer
        stepping_result = SteppedTrailingEdgeOptimizer().optimize(container, prepared.original_cargo, tuple(placements))
        if stepping_result.status == "SUCCESS":
            placements, stepping_result = self._accept_structurally_locked_stage(
                placements, stepping_result, stepping_result.placements, structural_locks, "STEPPED_TRAILING_EDGE"
            )
        self.last_stepping_result = stepping_result
        validation = IndependentGlobalValidator.validate(container, placements, list(prepared.original_cargo))
        transport_validation = None
        if prepared.door_wall is not None:
            actual_doors={p.placement_id:p for p in placements if p.placement_id.startswith("door_pre_")}
            planned={p.placement_id:p for p in prepared.door_wall.placements}
            if set(actual_doors)!=set(planned):
                raise ValueError("DOOR_WALL_MEMBERSHIP_CHANGED_AFTER_LOCK")
            final_door_placements=[]
            for pid,raw in planned.items():
                actual=actual_doors[pid]
                if any(abs(a-b)>1e-9 for a,b in ((actual.min_x,raw.x),(actual.min_y,raw.y),(actual.min_z,raw.z),
                        (actual.orientation.dx,raw.dx),(actual.orientation.dy,raw.dy),(actual.orientation.dz,raw.dz))):
                    raise ValueError("LOCKED_DOOR_WALL_GEOMETRY_CHANGED")
                final_door_placements.append(DoorWallPlacement(pid,actual.sku_id,actual.min_x,actual.min_y,actual.min_z,
                    actual.orientation.dx,actual.orientation.dy,actual.orientation.dz,raw.orientation,raw.layer,raw.column,actual.weight_kg,raw.concrete_orientation))
            final_door_wall=replace(prepared.door_wall,placements=tuple(final_door_placements))
            transport_validation=TransportForceDirectionModel().evaluate(
                final_door_wall,container,
                tuple(p for p in placements if not p.placement_id.startswith("door_pre_")),
                require_actual_back_anchor=self.enable_wall_optimization,
            )
            if not transport_validation.valid and compaction_result and compaction_result.status == "SUCCESS":
                placements = list(compaction_result.details.get("pre_compaction_placements", placements))
                transport_validation=TransportForceDirectionModel().evaluate(
                    final_door_wall,container,
                    tuple(p for p in placements if not p.placement_id.startswith("door_pre_")),
                    require_actual_back_anchor=self.enable_wall_optimization,
                )
            self.last_transport_validation=transport_validation
            if not transport_validation.valid:
                raise ValueError("DOOR_TRANSPORT_HARD_INVALID:"+",".join(transport_validation.rejection_reasons))
        else:
            self.last_transport_validation=None
        if direction_plan:
            actual=self.direction_engine.validate_actual(direction_plan,placements,prepared.original_cargo)
            if rebuild_result:
                actual["wall_fingerprint_unchanged"]=not rebuild_result.comparison.get("wall_order_changed",False)
                actual["direction_effective"]=rebuild_result.comparison.get("direction_effective",False)
            direction_plan=replace(direction_plan,actual_validation=actual)
        self.last_direction_plan=direction_plan
        total_volume = sum(p.volume for p in placements)
        placed_by_sku = {}
        for placement in placements:
            placed_by_sku[placement.sku_id] = placed_by_sku.get(placement.sku_id, 0) + 1
        required = sum(s.quantity.required for s in prepared.original_cargo)
        score = 0.0
        plan = self.adapter.engine.plan(container, prepared.original_cargo)
        if plan.safety_score:
            score = plan.safety_score.score
        has_door_wall = prepared.door_wall is not None
        diagnostics = DoorIntegrationDiagnostics(
            has_door_wall, len(prepared.door_context.anchor_placements) if prepared.door_context else 0, has_door_wall,
            all(value in {"SHORT_EDGE_FORWARD","LONG_EDGE_FORWARD"} for value in prepared.door_context.forced_orientation.values()) if prepared.door_context else True,
            len(commit.locked_ids), len(commit.support_links),
            max((p.max_x for p in structural_main), default=0.0),
            ("CREATE_CONTAINER", "INJECT_DOOR_WALL", "PLAN_CARGO_WALLS", "RESERVE_WALL_REGIONS", "RUN_FROZEN_SOLVER", "FULL_GLOBAL_VALIDATION"),
            "MAIN_CARGO_THEN_DOOR_WALL_BUILD (BLK007A door-access safety)",
            len(wall_prepared.plan.build.walls) if wall_prepared else 0,
            len(wall_prepared.plan.build.placements) if wall_prepared else 0,
            wall_prepared.plan.build.wall_end_x if wall_prepared else 0.0,
            len(optimization_prepared.result.transition_walls) if optimization_prepared else 0,
            optimization_prepared.result.optimized_wall_end_x if optimization_prepared else wall_prepared.plan.build.wall_end_x if wall_prepared else 0.0,
            optimization_prepared.result.chain.valid if optimization_prepared else False,
            len(topfill_prepared.result.placements) if topfill_prepared else 0,
            topfill_prepared.result.top_volume_added if topfill_prepared else 0.0,
            max((layer.layer_index for layer in topfill_prepared.result.layers),default=0) if topfill_prepared else 0,
            len(layer_prepared.result.added_placements) if layer_prepared else 0,
            layer_prepared.result.status=="SUCCESS" if layer_prepared else False,
            layer_prepared.result.door_seal["door_coverage"] if layer_prepared else 0.0,
            direction_plan.status=="READY" if direction_plan else False,
            direction_plan.actual_validation.get("display_direction_valid",False) if direction_plan else False,
            rebuild_result.status=="SUCCESS" if rebuild_result else False,
            rebuild_result.best_layout.layout_id if rebuild_result else "",
            rebuild_result.best_layout.score.global_score if rebuild_result else 0.0,
            recomposition_result.status=="SUCCESS" if recomposition_result else False,
            recomposition_result.best.changed_count if recomposition_result else 0,
            recomposition_result.best.changed_count/max(len(placements),1) if recomposition_result else 0.0,
            recomposition_result.best.score.global_score if recomposition_result else 0.0,
            wall_repack_result.status=="SUCCESS" if wall_repack_result else False,
            wall_repack_result.gap_before_m if wall_repack_result else 0.0,
            wall_repack_result.display_continuity if wall_repack_result else 0.0,
            True,
            prepared.door_wall.door_plane_clearance if has_door_wall else 0.0,
            prepared.door_wall.coverage if has_door_wall else 0.0,
            transport_validation.valid if transport_validation else True,
            len(residual_prepared.result.placements) if residual_prepared else 0,
            residual_prepared.result.added_volume if residual_prepared else 0.0,
        )
        from src.constraints.transport import BrakingStabilityValidator
        braking_report = BrakingStabilityValidator().validate(container, tuple(placements))
        self.last_braking_report = braking_report
        self.last_diagnostics = diagnostics
        main_solution.telemetry.runtime_ms += (time.perf_counter() - started) * 1000.0
        main_solution.telemetry.door_readiness = {
            **(main_solution.telemetry.door_readiness or {}),
            "door_wall_committed": has_door_wall, "door_wall_score": score,
            "door_zone_reserved": has_door_wall, "door_orientation_valid": has_door_wall,
            "door_wall_locked": has_door_wall, "door_wall_count": diagnostics.door_wall_count,
            "reserved_range": [prepared.door_context.blocked_area.x1, prepared.door_context.blocked_area.x2] if prepared.door_context else [container.Lx, container.Lx],
            "support_type": "DOOR_WALL_SUPPORT" if has_door_wall else "NONE", "integration": diagnostics.to_dict(),
            "door_plane_clearance_m": prepared.door_wall.door_plane_clearance if has_door_wall else 0.0,
            "door_area_coverage": prepared.door_wall.coverage if has_door_wall else 0.0,
            "door_width_coverage": prepared.door_wall.width_coverage if has_door_wall else 0.0,
            "door_height_coverage": prepared.door_wall.height_coverage if has_door_wall else 0.0,
            "transport_force_validation": transport_validation.to_dict() if transport_validation else {},
            "braking_stability": braking_report.to_dict(),
        }
        main_solution.telemetry.wall_plan_search_metrics = {
            **(main_solution.telemetry.wall_plan_search_metrics or {}),
            "cargo_wall_engine": "BLK007F1", "cargo_wall_count": diagnostics.cargo_wall_count,
            "cargo_wall_placements": diagnostics.cargo_wall_placements,
            "cargo_wall_end_x": diagnostics.cargo_wall_end_x,
            "braking_stability": braking_report.to_dict(),
            "available_top_regions": list(wall_prepared.plan.build.available_top_regions) if wall_prepared else [],
            "wall_plan": wall_prepared.plan.to_dict() if wall_prepared else None,
            "wall_optimization": optimization_prepared.result.to_dict() if optimization_prepared else None,
            "wall_optimization_attempt": self.last_wall_optimization_attempt,
            "layer_optimization": layer_prepared.result.to_dict() if layer_prepared else None,
            "loading_direction": direction_plan.to_dict() if direction_plan else None,
            "global_rebuild": rebuild_result.to_dict() if rebuild_result else None,
            "cargo_recomposition": recomposition_result.to_dict() if recomposition_result else None,
            "multisku_wall_recomposition": multisku_wall_result.to_dict() if multisku_wall_result else None,
            "three_d_layer_recomposition": layer_recomposition_result.to_dict() if layer_recomposition_result else None,
            "wall_internal_repacking": wall_repack_result.to_dict() if wall_repack_result else None,
            "wall_interface_repair": wall_interface_repair.to_dict() if wall_interface_repair else None,
            "residual_filling": residual_prepared.result.to_dict() if residual_prepared else None,
            "cargo_intelligence": intelligence.to_dict(),
            "structural_lock_count":len(structural_locks),
            "structural_lock_rejections":list(self.last_structural_lock_rejections),
        }
        if topfill_prepared:
            main_solution.telemetry.top_fill_metrics=topfill_prepared.result.to_dict()
        return SolverSolution(
            status="SUCCESS" if validation.is_valid else "INVALID",
            container=container, placements=placements, placed_count=len(placements),
            unplaced_count=max(0, required - len(placements)),
            volume_utilization_pct=100.0 * total_volume / container.volume,
            total_weight_kg=sum(p.weight_kg for p in placements),
            validation_result=validation, telemetry=main_solution.telemetry,
        )
