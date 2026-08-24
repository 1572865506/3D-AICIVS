"""
Pattern Generator Engine for Solver V2 (Agent 08 - Wall / Top Fill / Door).
Generates structured 3D Blocks, 2D Layers, Wall Slices, and Pinwheel patterns.
"""
from typing import List, Optional, Tuple, Dict, Any
import math

from backend.solver_v2.domain.models import (
    BoxDim,
    Point3D,
    Orientation3D,
    CargoSKU,
    PlacementContext,
    ContainerSpec,
)
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.orientation.manager import OrientationEngine
from backend.solver_v2.patterns.models import (
    PatternType,
    ItemOffset,
    PackedBlock,
    PatternCandidate,
)


class PatternGenerator:
    """
    Generates legal, geometrically compact cargo patterns.
    Reduces combinatorial search complexity by grouping identical or compatible items into blocks.
    """

    def __init__(
        self,
        container: Optional[ContainerSpec] = None,
        orientation_engine: Optional[OrientationEngine] = None,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
    ):
        self.container = container
        self.orientation_engine = orientation_engine or OrientationEngine(geom_epsilon=geom_epsilon)
        self.geom_epsilon = geom_epsilon

    def generate_blocks_for_sku(
        self,
        sku: CargoSKU,
        context: PlacementContext = PlacementContext.MAIN_WALL,
        target_space: Optional[AABB] = None,
        max_quantity: Optional[int] = None,
        max_nx: int = 10,
        max_ny: int = 10,
        max_nz: int = 10,
    ) -> List[PackedBlock]:
        """
        Generates homogeneous 3D Block and Layer patterns for a single SKU.
        Respects orientation policy, target space dimensions, stacking limits, and available quantity.
        """
        blocks: List[PackedBlock] = []
        avail_qty = sku.quantity.required if max_quantity is None else min(sku.quantity.required, max_quantity)
        if avail_qty <= 0:
            return blocks

        # 1. Get legal orientations for the SKU in this context
        ori_candidates = self.orientation_engine.get_candidate_orientations(
            sku=sku,
            context=context,
            target_space=target_space,
        )

        max_stack_layers = sku.stacking_policy.max_stack_layers

        for cand in ori_candidates:
            ori = cand.orientation
            dx, dy, dz = ori.dx, ori.dy, ori.dz

            # Determine maximum possible grid counts (nx, ny, nz)
            limit_nx = max_nx
            limit_ny = max_ny
            limit_nz = max_nz

            if target_space is not None:
                limit_nx = min(limit_nx, int((target_space.dx + self.geom_epsilon) // dx))
                limit_ny = min(limit_ny, int((target_space.dy + self.geom_epsilon) // dy))
                limit_nz = min(limit_nz, int((target_space.dz + self.geom_epsilon) // dz))

            if self.container is not None:
                limit_nx = min(limit_nx, int((self.container.Lx + self.geom_epsilon) // dx))
                limit_ny = min(limit_ny, int((self.container.Ly + self.geom_epsilon) // dy))
                limit_nz = min(limit_nz, int((self.container.Lz + self.geom_epsilon) // dz))

            if max_stack_layers is not None:
                limit_nz = min(limit_nz, max_stack_layers)

            limit_nx = max(1, limit_nx)
            limit_ny = max(1, limit_ny)
            limit_nz = max(1, limit_nz)

            # Generate grid variations
            for nx in range(1, limit_nx + 1):
                for ny in range(1, limit_ny + 1):
                    for nz in range(1, limit_nz + 1):
                        count = nx * ny * nz
                        if count > avail_qty:
                            continue

                        # Determine Pattern Type
                        if nz == 1 and (nx > 1 or ny > 1):
                            ptype = PatternType.LAYER
                        elif nx == 1 and ny > 1 and nz > 1:
                            ptype = PatternType.WALL_SLICE
                        else:
                            ptype = PatternType.BLOCK

                        block = self._build_homogeneous_block(
                            sku=sku,
                            orientation=ori,
                            nx=nx,
                            ny=ny,
                            nz=nz,
                            pattern_type=ptype,
                        )
                        blocks.append(block)

        # Sort blocks by carton count descending, then by volume descending
        blocks.sort(key=lambda b: (b.total_cartons, b.volume), reverse=True)
        return blocks

    def generate_wall_slices(
        self,
        sku: CargoSKU,
        container_ly: float,
        container_lz: float,
        context: PlacementContext = PlacementContext.MAIN_WALL,
        max_quantity: Optional[int] = None,
    ) -> List[PackedBlock]:
        """
        Generates full-width transverse wall slice patterns (1 x ny x nz)
        that span the container cross-section as completely as possible.
        """
        slices: List[PackedBlock] = []
        avail_qty = sku.quantity.required if max_quantity is None else min(sku.quantity.required, max_quantity)
        if avail_qty <= 0:
            return slices

        ori_candidates = self.orientation_engine.get_candidate_orientations(
            sku=sku,
            context=context,
        )

        max_stack_layers = sku.stacking_policy.max_stack_layers

        for cand in ori_candidates:
            ori = cand.orientation
            dx, dy, dz = ori.dx, ori.dy, ori.dz

            max_ny = int((container_ly + self.geom_epsilon) // dy)
            max_nz = int((container_lz + self.geom_epsilon) // dz)

            if max_stack_layers is not None:
                max_nz = min(max_nz, max_stack_layers)

            if max_ny < 1 or max_nz < 1:
                continue

            for ny in range(1, max_ny + 1):
                for nz in range(1, max_nz + 1):
                    count = ny * nz
                    if count > avail_qty:
                        continue

                    block = self._build_homogeneous_block(
                        sku=sku,
                        orientation=ori,
                        nx=1,
                        ny=ny,
                        nz=nz,
                        pattern_type=PatternType.WALL_SLICE,
                    )
                    slices.append(block)

        # Sort by cross-sectional fill area (dy*ny * dz*nz) descending
        slices.sort(
            key=lambda b: (b.bounding_box.y * b.bounding_box.z, b.total_cartons),
            reverse=True,
        )
        return slices

    def generate_pinwheel_layers(
        self,
        sku: CargoSKU,
        target_width: float,
        target_depth: float,
        context: PlacementContext = PlacementContext.MAIN_WALL,
        max_quantity: Optional[int] = None,
    ) -> List[PackedBlock]:
        """
        Generates interlocked 4-item or 5-item Pinwheel / interlocking layers when SKU allows rotation.
        A standard pinwheel uses alternating orientations around a central core.
        """
        patterns: List[PackedBlock] = []
        avail_qty = sku.quantity.required if max_quantity is None else min(sku.quantity.required, max_quantity)
        if avail_qty < 4:
            return patterns

        # Check if SKU allows upright rotated orientation
        base_x, base_y, base_z = sku.box.x, sku.box.y, sku.box.z
        if abs(base_x - base_y) <= self.geom_epsilon:
            return patterns  # Square base doesn't form asymmetric pinwheels

        ori_normal = Orientation3D(dx=base_x, dy=base_y, dz=base_z, name="UPRIGHT_NORMAL", is_upright=True)
        ori_rotated = Orientation3D(dx=base_y, dy=base_x, dz=base_z, name="UPRIGHT_ROTATED", is_upright=True)

        # Classic 4-box pinwheel:
        # Box 1: (0, 0) oriented (base_x, base_y)
        # Box 2: (base_x, 0) oriented (base_y, base_x)
        # Box 3: (base_x + base_y - base_x, base_x) etc.
        # Outer dimension is (base_x + base_y) x (base_x + base_y)
        pw_dim_x = base_x + base_y
        pw_dim_y = base_x + base_y
        pw_dim_z = base_z

        if pw_dim_x <= target_depth + self.geom_epsilon and pw_dim_y <= target_width + self.geom_epsilon:
            offsets = (
                ItemOffset(sku.sku_id, Point3D(0.0, 0.0, 0.0), ori_normal, sku.weight_kg),
                ItemOffset(sku.sku_id, Point3D(base_x, 0.0, 0.0), ori_rotated, sku.weight_kg),
                ItemOffset(sku.sku_id, Point3D(base_y, base_x, 0.0), ori_normal, sku.weight_kg),
                ItemOffset(sku.sku_id, Point3D(0.0, base_y, 0.0), ori_rotated, sku.weight_kg),
            )
            block = PackedBlock(
                pattern_id=f"PW4_{sku.sku_id}_{round(pw_dim_x, 2)}x{round(pw_dim_y, 2)}",
                pattern_type=PatternType.PINWHEEL,
                sku_id=sku.sku_id,
                bounding_box=BoxDim(x=pw_dim_x, y=pw_dim_y, z=pw_dim_z),
                total_cartons=4,
                total_weight_kg=4 * sku.weight_kg,
                item_offsets=offsets,
                nx=2,
                ny=2,
                nz=1,
                volume_efficiency=(4 * sku.box.volume) / (pw_dim_x * pw_dim_y * pw_dim_z),
            )
            patterns.append(block)

        return patterns

    def _build_homogeneous_block(
        self,
        sku: CargoSKU,
        orientation: Orientation3D,
        nx: int,
        ny: int,
        nz: int,
        pattern_type: PatternType,
    ) -> PackedBlock:
        dx, dy, dz = orientation.dx, orientation.dy, orientation.dz
        bx = round(nx * dx, 6)
        by = round(ny * dy, 6)
        bz = round(nz * dz, 6)
        total_count = nx * ny * nz
        total_weight = total_count * sku.weight_kg

        offsets: List[ItemOffset] = []
        for ix in range(nx):
            for iy in range(ny):
                for iz in range(nz):
                    offsets.append(
                        ItemOffset(
                            sku_id=sku.sku_id,
                            relative_position=Point3D(
                                x=round(ix * dx, 6),
                                y=round(iy * dy, 6),
                                z=round(iz * dz, 6),
                            ),
                            orientation=orientation,
                            weight_kg=sku.weight_kg,
                        )
                    )

        pid = f"{pattern_type.value}_{sku.sku_id}_{nx}x{ny}x{nz}_{orientation.name}"
        return PackedBlock(
            pattern_id=pid,
            pattern_type=pattern_type,
            sku_id=sku.sku_id,
            bounding_box=BoxDim(x=bx, y=by, z=bz),
            total_cartons=total_count,
            total_weight_kg=total_weight,
            item_offsets=tuple(offsets),
            nx=nx,
            ny=ny,
            nz=nz,
            unit_orientation=orientation,
            volume_efficiency=1.0,
        )
