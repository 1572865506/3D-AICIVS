
"""
Gap Filler Engine for Solver V2.

Scans inter-column, inter-layer, and residual gap spaces across the container
and performs dense packing (grid/array repetition) of small-sized SKUs (prioritizing flat orientations)
with full verification through HardValidationPipeline or authoritative validation rules.
"""
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass
import math

from backend.solver_v2.domain.models import (
    ContainerSpec,
    CargoSKU,
    Placement,
    Point3D,
    Orientation3D,
    PlacementContext,
    OrientationMode,
    PackingRole,
    ZoneType,
)
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.spaces.engine import FreeSpaceEngine
from backend.solver_v2.world.state import WorldState
from backend.solver_v2.feasibility.pipeline import HardValidationPipeline
from backend.solver_v2.candidates.generator import CandidatePlacement
from backend.solver_v2.zones.manager import AdaptiveZoneManager
from backend.solver_v2.quantity.manager import QuantityManager, SpatialReservationManager
from backend.solver_v2.door.elastic_frontier import ElasticDoorFrontier


@dataclass
class GapFillResult:
    placements_added: int
    volume_added_m3: float
    iterations: int
    rejection_reasons: Dict[str, int]


class GapFiller:
    """
    Scans inter-column, inter-layer, and residual gap spaces across the container,
    and attempts dense flat/compact packing of small SKUs, verified by HardValidationPipeline.
    """

    def __init__(
        self,
        container: ContainerSpec,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
        min_gap_dim: float = 0.05,
    ):
        self.container = container
        self.geom_epsilon = geom_epsilon
        self.min_gap_dim = min_gap_dim
        self.validator_pipeline = HardValidationPipeline(geom_epsilon=geom_epsilon)


    def scan_and_fill(
        self,
        world_state: WorldState,
        cargo_list: List[CargoSKU],
        qty_mgr: Optional[QuantityManager] = None,
        space_engine: Optional[FreeSpaceEngine] = None,
        zone_mgr: Optional[AdaptiveZoneManager] = None,
        res_mgr: Optional[SpatialReservationManager] = None,
        elastic_frontier: Optional[ElasticDoorFrontier] = None,
        max_rounds: int = 15,
    ) -> GapFillResult:
        """
        Executes gap fill dense scanning on active WorldState.
        """
        if zone_mgr is None:
            zone_mgr = AdaptiveZoneManager(container=self.container)
        if space_engine is None:
            space_engine = FreeSpaceEngine(container=self.container)
            for p in world_state.placements:
                space_engine.on_placement_replayed(p)

        sku_catalog = {c.sku_id: c for c in cargo_list}
        total_placed_count = 0
        total_vol_added = 0.0

        for round_idx in range(max_rounds):
            placed_in_round = 0
            
            if qty_mgr:
                unplaced_skus = [sku_catalog[sid] for sid in qty_mgr.get_sku_priorities(context=PlacementContext.GAP_FILL) if sid in sku_catalog]
            else:
                unplaced_skus = [
                    c for c in cargo_list
                    if world_state.get_remaining_quantity(c.sku_id) > 0
                ]

            if not unplaced_skus:
                break

            unplaced_skus.sort(key=lambda c: (
                c.box.volume,
                -(world_state.get_remaining_quantity(c.sku_id) if not qty_mgr else qty_mgr.get_remaining(c.sku_id))
            ))

            ems_list = space_engine.get_all_ems()
            ems_list.sort(key=lambda e: (e.min_x, e.min_z, e.min_y))

            for ems in ems_list:
                ems_dx = ems.max_x - ems.min_x
                ems_dy = ems.max_y - ems.min_y
                ems_dz = ems.max_z - ems.min_z

                if ems_dx < self.min_gap_dim or ems_dy < self.min_gap_dim or ems_dz < self.min_gap_dim:
                    continue

                placed_in_ems = False

                for sku in unplaced_skus:
                    rem_q = qty_mgr.get_remaining(sku.sku_id) if qty_mgr else world_state.get_remaining_quantity(sku.sku_id)
                    if rem_q <= 0:
                        continue

                    orientations = self._get_gap_orientations(sku)

                    for ori in orientations:
                        if ori.dx > ems_dx + 1e-4 or ori.dy > ems_dy + 1e-4 or ori.dz > ems_dz + 1e-4:
                            continue

                        nx = max(1, int((ems_dx + 1e-4) / ori.dx))
                        ny = max(1, int((ems_dy + 1e-4) / ori.dy))
                        nz = max(1, int((ems_dz + 1e-4) / ori.dz))

                        if sku.stacking_policy.max_stack_layers:
                            nz = min(nz, sku.stacking_policy.max_stack_layers)

                        for lz in range(nz):
                            for ix in range(nx):
                                for iy in range(ny):
                                    if rem_q <= 0:
                                        break

                                    px = round(ems.min_x + ix * ori.dx, 4)
                                    py = round(ems.min_y + iy * ori.dy, 4)
                                    pz = round(ems.min_z + lz * ori.dz, 4)

                                    cand = CandidatePlacement(
                                        sku_id=sku.sku_id,
                                        position=Point3D(x=px, y=py, z=pz),
                                        orientation=ori,
                                        context=PlacementContext.GAP_FILL,
                                        weight_kg=sku.weight_kg,
                                    )

                                    is_valid, _ = self.validator_pipeline.is_feasible(
                                        candidate=cand,
                                        sku=sku,
                                        world_state=world_state,
                                        zone_mgr=zone_mgr,
                                        res_mgr=res_mgr,
                                        elastic_frontier=elastic_frontier,
                                        context=PlacementContext.GAP_FILL,
                                    )

                                    if is_valid:
                                        step_idx = world_state.placement_count
                                        plc = cand.to_placement(
                                            placement_id=f'gap_{step_idx:04d}_{sku.sku_id}',
                                            instance_id=f'inst_gap_{step_idx:04d}',
                                            step_index=step_idx,
                                        )
                                        world_state.commit(plc)
                                        space_engine.on_placement_committed(plc)
                                        if qty_mgr:
                                            qty_mgr.record_placement(sku.sku_id, context=PlacementContext.GAP_FILL)
                                        
                                        rem_q -= 1
                                        total_placed_count += 1
                                        placed_in_round += 1
                                        total_vol_added += plc.volume
                                        placed_in_ems = True

                                    if rem_q <= 0:
                                        break
                            if rem_q <= 0:
                                break


                        if placed_in_ems:
                            break
                    if placed_in_ems:
                        break

            if placed_in_round == 0:
                break

        return GapFillResult(
            placements_added=total_placed_count,
            volume_added_m3=total_vol_added,
            iterations=round_idx + 1,
            rejection_reasons=dict(self.validator_pipeline.rejection_counts),
        )

    def _get_gap_orientations(self, sku: CargoSKU) -> List[Orientation3D]:
        raw_oris = sku.orientation_policy.get_legal_orientations(sku.box, PlacementContext.GAP_FILL)
        if not raw_oris:
            x, y, z = sku.box.x, sku.box.y, sku.box+z
            raw_oris = [
                Orientation3D(dx=x, dy=y, dz=z, name='UPRIGHT_NORMAL', is_upright=True),
                Orientation3D(dx=y, dy=x, dz=z, name='UPRIGHT_ROTATED', is_upright=True),
                Orientation3D(dx=x, dy=z, dz=y, name='FLAT_XZ', is_flat=True, is_upright=False),
                Orientation3D(dx=z, dy=x, dz=y, name='FLAT_ZX', is_flat=True, is_upright=False),
                Orientation3D(dx=y, dy=z, dz=x, name='SIDE_YZ', is_side=True, is_upright=False),
                Orientation3D(dx=z, dy=y, dz=x, name='SIDE_ZY', is_side=True, is_upright=False),
            ]

        min_dim = min(sku.box.x, sku.box.y, sku.box.z)
        raw_oris.sort(key=lambda o: (
            0 if abs(o.dz - min_dim) < 1e-4 else (1 if o.is_flat else (2 if o.is_side else 3)),
            o.dz,
            o.dx * o.dy
        ))
        return raw_oris
