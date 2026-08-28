"""
Unified Cargo & Constraint Tensor Normalization Model.

Provides universal abstractions for arbitrary container types (20GP/40GP/40HQ/45HQ/53FT)
and arbitrary business packing constraints.
"""
from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Tuple


class UniversalZone(str, Enum):
    INNER = "INNER"      # Closest to inner wall (X: 0 -> L/3)
    MIDDLE = "MIDDLE"    # Middle body (X: L/3 -> 2L/3)
    DOOR = "DOOR"        # Close to container door (X: 2L/3 -> L)
    FLEXIBLE = "FLEXIBLE"# No strict zone preference


class AllowedOrientation(str, Enum):
    UPRIGHT = "UPRIGHT"  # Length along X or Y, Height along Z
    FLAT = "FLAT"        # Height along X or Y (laying flat)
    SIDE = "SIDE"        # Width along Z (on side)


@dataclass
class OrientationSpec:
    name: str
    dx: float  # Dimension along container X (depth)
    dy: float  # Dimension along container Y (width)
    dz: float  # Dimension along container Z (height)
    is_upright: bool = True
    is_flat: bool = False
    is_side: bool = False


@dataclass
class UniversalCargoTensor:
    sku_id: str
    name: str
    length: float  # meters
    width: float   # meters
    height: float  # meters
    weight_kg: float
    quantity_required: int
    zone_preference: UniversalZone = UniversalZone.FLEXIBLE
    allow_flat: bool = False
    allow_side: bool = False
    max_stack_layers: Optional[int] = None
    category: str = "GENERAL"
    color: str = "#3b82f6"
    raw_requirement: str = ""

    # Derived physics features
    volume_m3: float = 0.0
    density_kg_m3: float = 0.0
    orientations: List[OrientationSpec] = field(default_factory=list)
    priority_score: float = 0.0

    def __post_init__(self):
        self.volume_m3 = round(self.length * self.width * self.height, 6)
        if self.volume_m3 > 1e-6:
            self.density_kg_m3 = round(self.weight_kg / self.volume_m3, 2)
        else:
            self.density_kg_m3 = 0.0
        self._generate_orientations()

    def _generate_orientations(self):
        opts = []
        l, w, h = self.length, self.width, self.height

        # 1. Upright orientations (Height aligned with container Z)
        opts.append(OrientationSpec(name="UPRIGHT_NORMAL", dx=round(l, 4), dy=round(w, 4), dz=round(h, 4), is_upright=True))
        if abs(l - w) > 1e-4:
            opts.append(OrientationSpec(name="UPRIGHT_ROTATED", dx=round(w, 4), dy=round(l, 4), dz=round(h, 4), is_upright=True))

        # 2. Flat orientations
        if self.allow_flat:
            opts.append(OrientationSpec(name="FLAT_NORMAL", dx=round(l, 4), dy=round(h, 4), dz=round(w, 4), is_flat=True, is_upright=False))
            if abs(l - h) > 1e-4:
                opts.append(OrientationSpec(name="FLAT_ROTATED", dx=round(h, 4), dy=round(l, 4), dz=round(w, 4), is_flat=True, is_upright=False))

        # 3. Side orientations
        if self.allow_side:
            opts.append(OrientationSpec(name="SIDE_NORMAL", dx=round(h, 4), dy=round(w, 4), dz=round(l, 4), is_side=True, is_upright=False))
            if abs(h - w) > 1e-4:
                opts.append(OrientationSpec(name="SIDE_ROTATED", dx=round(w, 4), dy=round(h, 4), dz=round(l, 4), is_side=True, is_upright=False))

        self.orientations = opts


@dataclass
class ContainerDimensions:
    code: str = "40HQ"
    length: float = 12.024
    width: float = 2.350
    height: float = 2.690
    max_payload_kg: float = 26000.0
    nominal_volume_m3: float = 76.0
