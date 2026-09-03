"""
Elastic Recovery Scanner for Solver V2 (OPT-05 / Step 5.3).

Core Idea:
After all previous constructive packing and post-processing passes (Compaction, Swap) are complete,
scans residual 3D cavity and gap spaces across the container to recover and pack SKUs that were
subject to elastic reduction or deferred due to tight initial space constraints.

Algorithm:
1. Identify all elastic SKUs with remaining unplaced inventory (required > placed, is_elastic or reduction_allowed).
2. Discover all maximal empty spaces (EMS) and residual pockets using FreeSpaceEngine and surface anchors.
3. Attempt dense multi-orientation grid packing of unplaced elastic SKUs into available residual spaces.
4. Verify container boundaries, collision avoidance, bottom support ratio, and stacking constraints for every placement.
5. Compute elastic recovery volume and elastic utilization improvement (Acceptance standard: delta >= 1.0%).
"""
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any, Union, Set
from collections import Counter
import math

from backend.solver_v2.domain.models import (
    ContainerSpec,
    CargoSKU,
    Placement,
    PlacementContext,
    Point3D,
    Orientation3D,
    OrientationMode,
    ZoneType,
    BoxDim,
)
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.spaces.engine import FreeSpaceEngine


@dataclass
class ElasticRecoveryResult:
    """Telemetry and metrics report produced by ElasticRecoveryScanner."""
    placements: List[Placement]
    recovered_elastic_count: int
    recovered_elastic_volume_m3: float
    elastic_utilization_before_pct: float
    elastic_utilization_after_pct: float
    elastic_utilization_delta_pct: float
    is_valid: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recovered_elastic_count": self.recovered_elastic_count,
            "recovered_elastic_volume_m3": round(self.recovered_elastic_volume_m3, 4),
            "elastic_utilization_before_pct": round(self.elastic_utilization_before_pct, 4),
            "elastic_utilization_after_pct": round(self.elastic_utilization_after_pct, 4),
            "elastic_utilization_delta_pct": round(self.elastic_utilization_delta_pct, 4),
            "is_valid": self.is_valid,
        }


class ElasticRecoveryScanner:
    """
    Scans residual cavity spaces after compaction and swap optimization
    to recover elastically reduced or unplaced SKUs.
    """

    def __init__(
        self,
        container: Optional[ContainerSpec] = None,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
        min_gap_dim: float = 0.05,
        max_scan_rounds: int = 15,
    ):
        self.container = container or ContainerSpec(
            code="40HQ",
            inner_dim=BoxDim(12.024, 2.350, 2.690),
            max_payload_kg=26000.0,
        )
        self.geom_epsilon = geom_epsilon
        self.min_gap_dim = min_gap_dim
        self.max_scan_rounds = max_scan_rounds

    def scan_and_recover(
        self,
        placements: List[Placement],
        cargo_list: List[CargoSKU],
        container: Optional[ContainerSpec] = None,
    ) -> ElasticRecoveryResult:
        """
        Scans residual free space to recover unplaced elastic SKUs.
        
        Args:
            placements: Existing placements after constructive solver and compaction/swap passes.
            cargo_list: Complete manifest of CargoSKUs.
            container: Optional container specification override.
            
        Returns:
            ElasticRecoveryResult with new placements and elastic utilization delta.
        """
        c = container or self.container
        eps = self.geom_epsilon
        z_contact_tol = max(1e-3, eps * 2)
        container_vol = c.volume

        sku_map: Dict[str, CargoSKU] = {s.sku_id: s for s in cargo_list}
        placed_counts = Counter(p.sku_id for p in placements)

        # Identify candidate elastic SKUs: is_elastic=True or reduction_allowed or min_quantity < required
        def is_elastic_sku(s: CargoSKU) -> bool:
            return (
                s.quantity.is_elastic
                or (s.cargo_profile and s.cargo_profile.placement_policy.reduction_allowed)
                or s.quantity.min_quantity < s.quantity.required
            )

        elastic_sku_ids = {s.sku_id for s in cargo_list if is_elastic_sku(s)}
        # If no explicit elastic flags found, consider all SKUs with unplaced items
        if not elastic_sku_ids:
            elastic_sku_ids = {s.sku_id for s in cargo_list}

        # Calculate initial elastic volume and utilization
        init_elastic_vol = sum(
            p.orientation.volume for p in placements if p.sku_id in elastic_sku_ids
        )
        init_elastic_util = (init_elastic_vol / container_vol) * 100.0 if container_vol > 0 else 0.0

        # Track remaining unplaced quantities
        unplaced_counts: Dict[str, int] = {}
        for s in cargo_list:
            req = s.quantity.required
            placed = placed_counts.get(s.sku_id, 0)
            unplaced_counts[s.sku_id] = max(0, req - placed)

        current_placements = list(placements)
        current_weight = sum(p.weight_kg for p in current_placements)
        space_engine = FreeSpaceEngine(container=c)
        for p in current_placements:
            space_engine.on_placement_replayed(p)

        instance_counter = 20000 + len(current_placements)
        total_recovered_count = 0
        total_recovered_vol = 0.0

        # Helper to check collision against all current placements
        def collides_with_placements(bx: float, by: float, bz: float, bdx: float, bdy: float, bdz: float) -> bool:
            for p in current_placements:
                ox = min(bx + bdx, p.position.x + p.orientation.dx) - max(bx, p.position.x)
                oy = min(by + bdy, p.position.y + p.orientation.dy) - max(by, p.position.y)
                oz = min(bz + bdz, p.position.z + p.orientation.dz) - max(bz, p.position.z)
                if ox > eps and oy > eps and oz > eps:
                    return True
            return False

        # Helper to check support ratio
        def check_support(
            bx: float, by: float, bz: float, bdx: float, bdy: float, bdz: float,
            sku: CargoSKU,
        ) -> bool:
            if bz <= eps:
                return True
            if sku.stacking_policy.must_be_on_floor:
                return False

            min_ratio = sku.stacking_policy.min_support_ratio
            total_supp_area = 0.0

            for p in current_placements:
                if abs((p.position.z + p.orientation.dz) - bz) <= z_contact_tol:
                    ox = min(bx + bdx, p.position.x + p.orientation.dx) - max(bx, p.position.x)
                    oy = min(by + bdy, p.position.y + p.orientation.dy) - max(by, p.position.y)
                    if ox > eps and oy > eps:
                        supp_sku = sku_map.get(p.sku_id)
                        if supp_sku and not supp_sku.stacking_policy.allow_stacking_on_top:
                            return False
                        total_supp_area += ox * oy

            base_area = bdx * bdy
            ratio = total_supp_area / base_area if base_area > 0 else 0.0
            return ratio >= min_ratio - eps

        # Recovery scan rounds
        for round_idx in range(self.max_scan_rounds):
            placed_in_round = 0

            # Target unplaced elastic SKUs sorted by smaller volume first (easier to fit into residual gaps)
            target_skus = [
                sku_map[sid] for sid in elastic_sku_ids
                if sid in sku_map and unplaced_counts.get(sid, 0) > 0
            ]
            if not target_skus:
                break

            target_skus.sort(key=lambda s: (s.box.volume, -unplaced_counts.get(s.sku_id, 0)))

            ems_list = space_engine.get_all_ems()
            # Sort EMS by x ascending (inner wall to door), z ascending (bottom to top), y ascending
            ems_list.sort(key=lambda e: (e.min_x, e.min_z, e.min_y))

            for ems in ems_list:
                ems_dx = ems.max_x - ems.min_x
                ems_dy = ems.max_y - ems.min_y
                ems_dz = ems.max_z - ems.min_z

                if ems_dx < self.min_gap_dim or ems_dy < self.min_gap_dim or ems_dz < self.min_gap_dim:
                    continue

                for sku in target_skus:
                    rem_q = unplaced_counts.get(sku.sku_id, 0)
                    if rem_q <= 0:
                        continue

                    # Weight capacity check
                    if c.max_payload_kg > 0 and current_weight + sku.weight_kg > c.max_payload_kg + eps:
                        continue

                    # Get legal orientations for GAP_FILL
                    orientations = sku.orientation_policy.get_legal_orientations(sku.box, PlacementContext.GAP_FILL)
                    if not orientations:
                        bx, by, bz = sku.box.x, sku.box.y, sku.box.z
                        orientations = [
                            Orientation3D(dx=bx, dy=by, dz=bz, name="UPRIGHT_NORMAL", is_upright=True),
                            Orientation3D(dx=by, dy=bx, dz=bz, name="UPRIGHT_ROTATED", is_upright=True),
                        ]
                        if sku.orientation_policy.allow_flat:
                            orientations.append(Orientation3D(dx=bx, dy=bz, dz=by, name="FLAT_XZ", is_flat=True, is_upright=False))
                            orientations.append(Orientation3D(dx=bz, dy=bx, dz=by, name="FLAT_ZX", is_flat=True, is_upright=False))

                    # Sort orientations: prefer flat / lower height for gap filling
                    orientations.sort(key=lambda o: (o.dz, o.dx * o.dy))

                    for ori in orientations:
                        if rem_q <= 0:
                            break
                        if ori.dx > ems_dx + eps or ori.dy > ems_dy + eps or ori.dz > ems_dz + eps:
                            continue

                        nx = max(1, int((ems_dx + eps) / ori.dx))
                        ny = max(1, int((ems_dy + eps) / ori.dy))
                        nz = max(1, int((ems_dz + eps) / ori.dz))

                        if sku.stacking_policy.max_stack_layers:
                            nz = min(nz, sku.stacking_policy.max_stack_layers)

                        for kz in range(nz):
                            if rem_q <= 0:
                                break
                            for kx in range(nx):
                                if rem_q <= 0:
                                    break
                                for ky in range(ny):
                                    if rem_q <= 0:
                                        break
                                    px = round(ems.min_x + kx * ori.dx, 6)
                                    py = round(ems.min_y + ky * ori.dy, 6)
                                    pz = round(ems.min_z + kz * ori.dz, 6)

                                    if px + ori.dx > c.Lx + eps or py + ori.dy > c.Ly + eps or pz + ori.dz > c.Lz + eps:
                                        continue

                                    if c.max_payload_kg > 0 and current_weight + sku.weight_kg > c.max_payload_kg + eps:
                                        break

                                    if collides_with_placements(px, py, pz, ori.dx, ori.dy, ori.dz):
                                        continue

                                    if not check_support(px, py, pz, ori.dx, ori.dy, ori.dz, sku):
                                        continue

                                    # Commit recovered placement
                                    instance_counter += 1
                                    rec_p = Placement(
                                        placement_id=f"REC_ELASTIC_{instance_counter}",
                                        instance_id=f"INST_REC_{instance_counter}",
                                        sku_id=sku.sku_id,
                                        position=Point3D(px, py, pz),
                                        orientation=ori,
                                        weight_kg=sku.weight_kg,
                                        context=PlacementContext.GAP_FILL,
                                        step_index=len(current_placements),
                                    )

                                    current_placements.append(rec_p)
                                    space_engine.on_placement_committed(rec_p)
                                    current_weight += sku.weight_kg
                                    unplaced_counts[sku.sku_id] -= 1
                                    rem_q -= 1
                                    total_recovered_count += 1
                                    total_recovered_vol += rec_p.orientation.volume
                                    placed_in_round += 1

            if placed_in_round == 0:
                break

        # Calculate final elastic volume and utilization
        final_elastic_vol = sum(
            p.orientation.volume for p in current_placements if p.sku_id in elastic_sku_ids
        )
        final_elastic_util = (final_elastic_vol / container_vol) * 100.0 if container_vol > 0 else 0.0
        delta_elastic_util = final_elastic_util - init_elastic_util

        return ElasticRecoveryResult(
            placements=current_placements,
            recovered_elastic_count=total_recovered_count,
            recovered_elastic_volume_m3=total_recovered_vol,
            elastic_utilization_before_pct=init_elastic_util,
            elastic_utilization_after_pct=final_elastic_util,
            elastic_utilization_delta_pct=delta_elastic_util,
            is_valid=True,
        )
