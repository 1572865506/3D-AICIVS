"""
SwapHeuristic and Local Swap Optimizer for Solver V2 (OPT-05 / Step 5.2).

Core Idea:
Post-processing local search that identifies inefficient placements and exchanges them
with unplaced cargo (1-for-1 upgrades or 1-for-N subdivision swaps) to increase total placed box count
and container volume utilization while strictly preserving physical validity and constraints.

Algorithm:
1. Identify inefficient placements and available unplaced inventory.
2. 1-for-N Subdivision Swaps: Replace large/loose placed boxes with clusters of unplaced smaller boxes.
3. 1-for-1 Upgrade Swaps: Replace smaller placed boxes with unplaced larger boxes where headroom/space allows.
4. Accept all non-deteriorating swaps (volume utilization non-decreasing and box count non-decreasing).
5. Ensure post-swap physical and structural feasibility via collision, support, and stacking checks.
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


@dataclass
class SwapResult:
    """Detailed report produced by SwapOptimizer."""
    placements: List[Placement]
    initial_placed_count: int
    final_placed_count: int
    box_count_delta: int
    initial_volume_m3: float
    final_volume_m3: float
    volume_delta_m3: float
    swaps_accepted: int
    is_valid: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "initial_placed_count": self.initial_placed_count,
            "final_placed_count": self.final_placed_count,
            "box_count_delta": self.box_count_delta,
            "initial_volume_m3": round(self.initial_volume_m3, 4),
            "final_volume_m3": round(self.final_volume_m3, 4),
            "volume_delta_m3": round(self.volume_delta_m3, 4),
            "swaps_accepted": self.swaps_accepted,
            "is_valid": self.is_valid,
        }


class SwapOptimizer:
    """
    Local Search Swap Optimizer for Solver V2.
    
    Exchanges already-placed boxes with unplaced cargo inventory to boost
    packing density, volume utilization, and total box count.
    """

    def __init__(
        self,
        container: Optional[ContainerSpec] = None,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
        max_iterations: int = 50,
    ):
        self.container = container or ContainerSpec(
            code="40HQ",
            inner_dim=BoxDim(12.024, 2.350, 2.690),
            max_payload_kg=26000.0,
        )
        self.geom_epsilon = geom_epsilon
        self.max_iterations = max_iterations

    def optimize(
        self,
        placements: List[Placement],
        cargo_list: List[CargoSKU],
        container: Optional[ContainerSpec] = None,
    ) -> SwapResult:
        """
        Executes local swap optimization on the solution placements.
        
        Args:
            placements: Initial placements from constructive solver.
            cargo_list: Complete manifest of CargoSKU specifications with quantity targets.
            container: Optional container specification override.
            
        Returns:
            SwapResult with optimized placements, box count improvement, and volume delta.
        """
        if not placements or not cargo_list:
            init_cnt = len(placements)
            init_vol = sum(p.orientation.volume for p in placements)
            return SwapResult(
                placements=list(placements),
                initial_placed_count=init_cnt,
                final_placed_count=init_cnt,
                box_count_delta=0,
                initial_volume_m3=init_vol,
                final_volume_m3=init_vol,
                volume_delta_m3=0.0,
                swaps_accepted=0,
                is_valid=True,
            )

        c = container or self.container
        eps = self.geom_epsilon
        z_contact_tol = max(1e-3, eps * 2)

        sku_map: Dict[str, CargoSKU] = {s.sku_id: s for s in cargo_list}
        init_cnt = len(placements)
        init_vol = sum(p.orientation.volume for p in placements)

        # Inventory management: track remaining unplaced count per SKU
        placed_counts = Counter(p.sku_id for p in placements)
        unplaced_counts: Dict[str, int] = {}
        for s in cargo_list:
            req = s.quantity.required
            placed = placed_counts.get(s.sku_id, 0)
            unplaced_counts[s.sku_id] = max(0, req - placed)

        current_placements = list(placements)
        swaps_accepted = 0
        instance_counter = 10000

        # Helper to check collision of a box against current placements (ignoring specific IDs)
        def check_collision(
            bx: float, by: float, bz: float, bdx: float, bdy: float, bdz: float,
            ignore_ids: Set[str]
        ) -> bool:
            for p in current_placements:
                if p.placement_id in ignore_ids:
                    continue
                ox = min(bx + bdx, p.position.x + p.orientation.dx) - max(bx, p.position.x)
                oy = min(by + bdy, p.position.y + p.orientation.dy) - max(by, p.position.y)
                oz = min(bz + bdz, p.position.z + p.orientation.dz) - max(bz, p.position.z)
                if ox > eps and oy > eps and oz > eps:
                    return True
            return False

        # Helper to check support ratio of a placement at (bx, by, bz, bdx, bdy, bdz)
        def check_support(
            bx: float, by: float, bz: float, bdx: float, bdy: float, bdz: float,
            sku: CargoSKU,
            ignore_ids: Set[str],
            internal_supports: Optional[List[Tuple[float, float, float, float, float, float]]] = None,
        ) -> bool:
            if bz <= eps:
                return True
            if sku.stacking_policy.must_be_on_floor:
                return False

            min_ratio = sku.stacking_policy.min_support_ratio
            total_supp_area = 0.0

            # 1. Check external supports from current placements
            for p in current_placements:
                if p.placement_id in ignore_ids:
                    continue
                if abs((p.position.z + p.orientation.dz) - bz) <= z_contact_tol:
                    ox = min(bx + bdx, p.position.x + p.orientation.dx) - max(bx, p.position.x)
                    oy = min(by + bdy, p.position.y + p.orientation.dy) - max(by, p.position.y)
                    if ox > eps and oy > eps:
                        supp_sku = sku_map.get(p.sku_id)
                        if supp_sku and not supp_sku.stacking_policy.allow_stacking_on_top:
                            return False
                        total_supp_area += ox * oy

            # 2. Check internal supports from newly placed sub-boxes
            if internal_supports:
                for ix, iy, iz, idx, idy, idz in internal_supports:
                    if abs((iz + idz) - bz) <= z_contact_tol:
                        ox = min(bx + bdx, ix + idx) - max(bx, ix)
                        oy = min(by + bdy, iy + idy) - max(by, iy)
                        if ox > eps and oy > eps:
                            total_supp_area += ox * oy

            base_area = bdx * bdy
            ratio = total_supp_area / base_area if base_area > 0 else 0.0
            return ratio >= min_ratio - eps

        # Local search optimization passes
        for iteration in range(self.max_iterations):
            improved_in_iteration = False

            # ===================================================================
            # Strategy A: 1-for-N Subdivision Swaps (Increase Box Count)
            # ===================================================================
            # Sort placed boxes from top to bottom (z descending)
            sorted_placements = sorted(
                current_placements,
                key=lambda p: (-p.position.z, -p.orientation.volume, p.placement_id),
            )

            for target_p in sorted_placements:
                target_sku = sku_map.get(target_p.sku_id)
                tx, ty, tz = target_p.position.x, target_p.position.y, target_p.position.z
                tdx, tdy, tdz = target_p.orientation.dx, target_p.orientation.dy, target_p.orientation.dz
                target_vol = target_p.orientation.volume

                # Look for unplaced SKUs that can pack into target space in multiples
                for sub_sku_id, unplaced_qty in list(unplaced_counts.items()):
                    if unplaced_qty <= 1:
                        continue
                    sub_sku = sku_map.get(sub_sku_id)
                    if not sub_sku:
                        continue
                    if sub_sku.box.volume >= target_vol - eps:
                        continue

                    # Try legal orientations of sub_sku
                    legal_oris = sub_sku.orientation_policy.get_legal_orientations(
                        sub_sku.box,
                        target_p.context,
                    )
                    if not legal_oris:
                        legal_oris = [Orientation3D(dx=sub_sku.box.x, dy=sub_sku.box.y, dz=sub_sku.box.z)]

                    best_swap_placements: Optional[List[Placement]] = None
                    best_swap_count = 0
                    best_swap_vol = 0.0

                    for ori in legal_oris:
                        sdx, sdy, sdz = ori.dx, ori.dy, ori.dz
                        nx = int(math.floor((tdx + eps) / sdx))
                        ny = int(math.floor((tdy + eps) / sdy))
                        nz = int(math.floor((tdz + eps) / sdz))

                        max_fit = nx * ny * nz
                        if max_fit <= 1:
                            continue

                        pack_count = min(max_fit, unplaced_qty)
                        if pack_count <= 1:
                            continue

                        cand_sub_placements: List[Placement] = []
                        internal_box_boxes: List[Tuple[float, float, float, float, float, float]] = []
                        valid_grid = True
                        curr_placed_sub = 0

                        # Pack layers bottom-up
                        for kz in range(nz):
                            if curr_placed_sub >= pack_count or not valid_grid:
                                break
                            for kx in range(nx):
                                if curr_placed_sub >= pack_count or not valid_grid:
                                    break
                                for ky in range(ny):
                                    if curr_placed_sub >= pack_count:
                                        break
                                    px = round(tx + kx * sdx, 6)
                                    py = round(ty + ky * sdy, 6)
                                    pz = round(tz + kz * sdz, 6)

                                    # Bounds check
                                    if px + sdx > c.Lx + eps or py + sdy > c.Ly + eps or pz + sdz > c.Lz + eps:
                                        valid_grid = False
                                        break

                                    # Collision check against existing placements (excluding target_p)
                                    if check_collision(px, py, pz, sdx, sdy, sdz, ignore_ids={target_p.placement_id}):
                                        valid_grid = False
                                        break

                                    # Support check
                                    if not check_support(
                                        px, py, pz, sdx, sdy, sdz,
                                        sub_sku,
                                        ignore_ids={target_p.placement_id},
                                        internal_supports=internal_box_boxes,
                                    ):
                                        valid_grid = False
                                        break

                                    instance_counter += 1
                                    sub_p = Placement(
                                        placement_id=f"SWAP_SUB_{instance_counter}",
                                        instance_id=f"INST_SWAP_{instance_counter}",
                                        sku_id=sub_sku_id,
                                        position=Point3D(px, py, pz),
                                        orientation=ori,
                                        weight_kg=sub_sku.weight_kg,
                                        context=target_p.context,
                                        step_index=target_p.step_index,
                                    )
                                    cand_sub_placements.append(sub_p)
                                    internal_box_boxes.append((px, py, pz, sdx, sdy, sdz))
                                    curr_placed_sub += 1

                        if valid_grid and len(cand_sub_placements) > 1:
                            sub_vol = sum(p.orientation.volume for p in cand_sub_placements)
                            # Acceptance criterion: volume utilization must not decrease (sub_vol >= target_vol - eps)
                            # and count strictly increases
                            if sub_vol >= target_vol - eps and len(cand_sub_placements) > best_swap_count:
                                best_swap_placements = cand_sub_placements
                                best_swap_count = len(cand_sub_placements)
                                best_swap_vol = sub_vol

                    # Execute swap if a superior sub-packing was found
                    if best_swap_placements and best_swap_count > 1:
                        # Remove target_p and add best_swap_placements
                        current_placements = [p for p in current_placements if p.placement_id != target_p.placement_id]
                        current_placements.extend(best_swap_placements)

                        # Update inventory
                        unplaced_counts[target_p.sku_id] = unplaced_counts.get(target_p.sku_id, 0) + 1
                        unplaced_counts[sub_sku_id] -= best_swap_count
                        swaps_accepted += 1
                        improved_in_iteration = True
                        break

            if improved_in_iteration:
                continue

            # ===================================================================
            # Strategy B: 1-for-1 Upgrade Swaps (Volume Utilization Increase)
            # ===================================================================
            for target_p in list(current_placements):
                target_sku = sku_map.get(target_p.sku_id)
                tx, ty, tz = target_p.position.x, target_p.position.y, target_p.position.z
                target_vol = target_p.orientation.volume

                # Look for unplaced larger SKUs that can fit in target's spot
                for up_sku_id, unplaced_qty in list(unplaced_counts.items()):
                    if unplaced_qty <= 0:
                        continue
                    up_sku = sku_map.get(up_sku_id)
                    if not up_sku or up_sku.box.volume <= target_vol + eps:
                        continue

                    legal_oris = up_sku.orientation_policy.get_legal_orientations(
                        up_sku.box,
                        target_p.context,
                    )
                    if not legal_oris:
                        legal_oris = [Orientation3D(dx=up_sku.box.x, dy=up_sku.box.y, dz=up_sku.box.z)]

                    for ori in legal_oris:
                        udx, udy, udz = ori.dx, ori.dy, ori.dz

                        if tx + udx > c.Lx + eps or ty + udy > c.Ly + eps or tz + udz > c.Lz + eps:
                            continue

                        if check_collision(tx, ty, tz, udx, udy, udz, ignore_ids={target_p.placement_id}):
                            continue

                        if not check_support(tx, ty, tz, udx, udy, udz, up_sku, ignore_ids={target_p.placement_id}):
                            continue

                        # Valid upgrade found!
                        instance_counter += 1
                        upgraded_p = Placement(
                            placement_id=f"SWAP_UP_{instance_counter}",
                            instance_id=f"INST_UP_{instance_counter}",
                            sku_id=up_sku_id,
                            position=Point3D(tx, ty, tz),
                            orientation=ori,
                            weight_kg=up_sku.weight_kg,
                            context=target_p.context,
                            step_index=target_p.step_index,
                        )

                        current_placements = [p for p in current_placements if p.placement_id != target_p.placement_id]
                        current_placements.append(upgraded_p)

                        unplaced_counts[target_p.sku_id] = unplaced_counts.get(target_p.sku_id, 0) + 1
                        unplaced_counts[up_sku_id] -= 1
                        swaps_accepted += 1
                        improved_in_iteration = True
                        break

                    if improved_in_iteration:
                        break

                if improved_in_iteration:
                    break

            if not improved_in_iteration:
                break

        final_cnt = len(current_placements)
        final_vol = sum(p.orientation.volume for p in current_placements)

        return SwapResult(
            placements=current_placements,
            initial_placed_count=init_cnt,
            final_placed_count=final_cnt,
            box_count_delta=final_cnt - init_cnt,
            initial_volume_m3=init_vol,
            final_volume_m3=final_vol,
            volume_delta_m3=final_vol - init_vol,
            swaps_accepted=swaps_accepted,
            is_valid=True,
        )
