"""
Domain models for Pattern Engine (Agent 08 - Wall / Top Fill / Door).
Defines structured block, layer, and wall slice patterns for aggregating identical or compatible cartons.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Tuple, Optional, Dict, Any

from backend.solver_v2.domain.models import (
    BoxDim,
    Point3D,
    Orientation3D,
    CargoSKU,
    Placement,
    PlacementContext,
)
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON


class PatternType(str, Enum):
    BLOCK = "BLOCK"            # 3D homogeneous block (nx x ny x nz)
    LAYER = "LAYER"            # 2D layer (nx x ny x 1)
    WALL_SLICE = "WALL_SLICE"  # Full transverse wall slice (1 x ny x nz)
    PINWHEEL = "PINWHEEL"      # Interlocked interlocking pattern
    COMPOSITE = "COMPOSITE"    # Multi-orientation or multi-SKU composite block


@dataclass(frozen=True)
class ItemOffset:
    """Relative offset and orientation of a single cargo item within a pattern block."""
    sku_id: str
    relative_position: Point3D  # Offset relative to block origin (0, 0, 0)
    orientation: Orientation3D
    weight_kg: float


@dataclass(frozen=True)
class PackedBlock:
    """
    Concrete aggregated pattern block representing multiple identical or arranged cartons.
    """
    pattern_id: str
    pattern_type: PatternType
    sku_id: str
    bounding_box: BoxDim
    total_cartons: int
    total_weight_kg: float
    item_offsets: Tuple[ItemOffset, ...]
    nx: int = 1
    ny: int = 1
    nz: int = 1
    unit_orientation: Optional[Orientation3D] = None
    volume_efficiency: float = 1.0

    @property
    def volume(self) -> float:
        return self.bounding_box.volume

    def instantiate(
        self,
        anchor_position: Point3D,
        context: PlacementContext = PlacementContext.MAIN_WALL,
        placement_id_prefix: str = "p",
        start_index: int = 0,
        step_index: int = 0,
    ) -> List[Placement]:
        """
        Instantiates the PackedBlock into concrete Placement objects at the specified anchor position.
        """
        placements: List[Placement] = []
        for idx, offset in enumerate(self.item_offsets):
            pos = Point3D(
                x=anchor_position.x + offset.relative_position.x,
                y=anchor_position.y + offset.relative_position.y,
                z=anchor_position.z + offset.relative_position.z,
            )
            pid = f"{placement_id_prefix}_{start_index + idx}"
            inst_id = f"inst_{self.sku_id}_{start_index + idx}"
            p = Placement(
                placement_id=pid,
                instance_id=inst_id,
                sku_id=offset.sku_id,
                position=pos,
                orientation=offset.orientation,
                weight_kg=offset.weight_kg,
                context=context,
                step_index=step_index,
            )
            placements.append(p)
        return placements


@dataclass(frozen=True)
class PatternCandidate:
    """
    Evaluated pattern candidate proposed for placement in a target space.
    """
    block: PackedBlock
    anchor_position: Point3D
    context: PlacementContext
    score: float = 0.0
    is_valid: bool = True
    rejection_reason: Optional[str] = None

    @property
    def bounding_aabb(self) -> AABB:
        return AABB(
            min_x=self.anchor_position.x,
            min_y=self.anchor_position.y,
            min_z=self.anchor_position.z,
            max_x=self.anchor_position.x + self.block.bounding_box.x,
            max_y=self.anchor_position.y + self.block.bounding_box.y,
            max_z=self.anchor_position.z + self.block.bounding_box.z,
        )
