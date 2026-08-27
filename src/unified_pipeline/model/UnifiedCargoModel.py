"""
Unified Cargo Model Entity.

Comprehensive mathematical feature tensor M_SKU = <G, P, S, Z, R> representing
all physical, mechanical, geometric, zoning, and elastic constraints.
"""
from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Dict, List, Optional, Set, Tuple


class ZonePreference(str, Enum):
    INNER = "INNER"       # 放柜子最里面 (X in [0, 3m])
    MIDDLE = "MIDDLE"     # 放中间 (X in [3, 9m])
    DOOR = "DOOR"         # 封柜门 / 门端 (X in [9, 12m])
    GENERAL = "GENERAL"   # 通用区位


class PackingRole(str, Enum):
    CORE_WALL = "CORE_WALL"       # 大件/大单品主骨架整垛货
    FLANK_FILLER = "FLANK_FILLER" # 侧翼整垛配对件
    TOP_FILLER = "TOP_FILLER"     # 顶层平铺件
    TAIL_PIECE = "TAIL_PIECE"     # 整垛后剩余的尾数散件


@dataclass
class OrientationOption:
    name: str
    dx: float
    dy: float
    dz: float
    is_upright: bool
    is_flat: bool
    is_side: bool


@dataclass
class UnifiedCargoModel:
    sku_id: str
    name: str
    length: float
    width: float
    height: float
    weight_kg: float
    quantity_required: int
    quantity_min: int = 0
    
    # 1. Geometric morphology tensor G
    volume_m3: float = 0.0
    base_area_m2: float = 0.0
    aspect_ratio_lambda: float = 0.0
    
    # 2. Physical & Mechanics vector P
    density_kg_m3: float = 0.0
    max_bearing_kg: Optional[float] = None
    max_pressure_kg_m2: Optional[float] = None
    max_stack_layers: Optional[int] = None
    min_support_ratio: float = 0.70
    allow_stacking_on_top: bool = True
    stack_on_self: bool = True
    
    # 3. Permissible poses S
    allow_upright: bool = True
    allow_flat: bool = False
    allow_side: bool = False
    keep_upright: bool = False
    orientations: List[OrientationOption] = field(default_factory=list)
    
    # 4. Spatial Zone potential field Z
    zone_preference: ZonePreference = ZonePreference.GENERAL
    zone_mu_x: float = 6.0
    zone_sigma_x: float = 3.0
    priority_score: float = 0.0
    
    # 5. Packing role & Elastic policies R
    packing_role: PackingRole = PackingRole.CORE_WALL
    allow_reduction: bool = False
    raw_requirement: str = ""
    category: str = "GENERAL"

    def __post_init__(self):
        # 1. Compute geometric attributes
        self.volume_m3 = round(self.length * self.width * self.height, 6)
        min_base = min(self.length, self.width)
        max_base = max(self.length, self.width)
        self.base_area_m2 = round(min_base * max_base, 6)
        if min_base > 1e-4:
            self.aspect_ratio_lambda = round(self.height / min_base, 3)
        else:
            self.aspect_ratio_lambda = 1.0

        # 2. Compute density
        if self.volume_m3 > 1e-9:
            self.density_kg_m3 = round(self.weight_kg / self.volume_m3, 2)
        else:
            self.density_kg_m3 = 0.0

        # 3. Parse Zone parameters
        if self.zone_preference == ZonePreference.INNER:
            self.zone_mu_x = 0.8
            self.zone_sigma_x = 1.5
        elif self.zone_preference == ZonePreference.DOOR:
            self.zone_mu_x = 11.2
            self.zone_sigma_x = 1.2
        elif self.zone_preference == ZonePreference.MIDDLE:
            self.zone_mu_x = 6.0
            self.zone_sigma_x = 2.5
        else:
            self.zone_mu_x = 6.0
            self.zone_sigma_x = 6.0

        # 4. Generate permissible orientations
        if not self.orientations:
            self._generate_default_orientations()

    def _generate_default_orientations(self):
        opts = []
        # Upright: height is Z
        opts.append(OrientationOption("UPRIGHT_0", self.length, self.width, self.height, True, False, False))
        if abs(self.length - self.width) > 1e-4:
            opts.append(OrientationOption("UPRIGHT_90", self.width, self.length, self.height, True, False, False))
        
        # Flat: width is Z
        if self.allow_flat and not self.keep_upright:
            opts.append(OrientationOption("FLAT_0", self.length, self.height, self.width, False, True, False))
            opts.append(OrientationOption("FLAT_90", self.height, self.length, self.width, False, True, False))

        # Side: length is Z
        if self.allow_side and not self.keep_upright:
            opts.append(OrientationOption("SIDE_0", self.width, self.height, self.length, False, False, True))
            opts.append(OrientationOption("SIDE_90", self.height, self.width, self.length, False, False, True))

        self.orientations = opts

    def zone_potential_at(self, x: float) -> float:
        """Returns spatial affinity potential in [-1.0, 1.0] at position x along container length."""
        diff = x - self.zone_mu_x
        gauss = math.exp(- (diff * diff) / (2.0 * self.zone_sigma_x * self.zone_sigma_x))
        return gauss
