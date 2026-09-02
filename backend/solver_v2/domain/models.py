"""
Solver V2 Canonical Domain Models
Pure domain abstractions strictly obeying Clean-Room Solver V2 specs and Canonical Coordinates:
  x: longitudinal / inner wall -> doors [0, Lx]
  y: lateral / width [0, Ly]
  z: vertical / floor -> roof [0, Lz]
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Tuple, List, Dict, Any, Optional
import math
import hashlib
import json


class PlacementRuleMode(str, Enum):
    REQUIRED = "REQUIRED"
    PREFER = "PREFER"
    AVOID = "AVOID"
    FORBIDDEN = "FORBIDDEN"


class PackingRole(str, Enum):
    FOUNDATION = "FOUNDATION"
    MAIN_WALL = "MAIN_WALL"
    WALL_FILLER = "WALL_FILLER"
    TOP_FILL = "TOP_FILL"
    DOOR_SEAL = "DOOR_SEAL"
    FLEXIBLE = "FLEXIBLE"


class CargoClass(str, Enum):
    STANDARD = "STANDARD"
    HEAVY = "HEAVY"
    FRAGILE = "FRAGILE"
    DEFORMABLE = "DEFORMABLE"


class PlacementContext(str, Enum):
    FOUNDATION = "FOUNDATION"
    MAIN_WALL = "MAIN_WALL"
    TOP_FILL = "TOP_FILL"
    DOOR_SEAL = "DOOR_SEAL"
    GAP_FILL = "GAP_FILL"
    GENERAL = "GENERAL"


class OrientationRegion(str, Enum):
    """Business region in which an orientation rule may be activated."""
    MAIN_BODY = "MAIN_BODY"
    TOP_FILL = "TOP_FILL"
    DOOR_ZONE = "DOOR_ZONE"
    DOOR_SPECIAL = "DOOR_SPECIAL"


class OrientationMode(str, Enum):
    UPRIGHT = "UPRIGHT"
    FLAT = "FLAT"
    SIDE = "SIDE"


class ZoneType(str, Enum):
    REAR = "REAR"          # Near inner wall (x -> 0)
    MIDDLE = "MIDDLE"      # Mid body
    DOOR = "DOOR"          # Near doors (x -> Lx)
    FLOOR_ONLY = "FLOOR_ONLY"
    ROOF_ONLY = "ROOF_ONLY"


class PolicySource(str, Enum):
    """Provenance of a cargo constraint; defaults are never presented as user facts."""
    DEFAULT = "DEFAULT"
    USER_DEFINED = "USER_DEFINED"


class TopFillAdmissionState(str, Enum):
    """Explicit policy intent; AUTO requires proof by the existing safety stack."""
    ALLOW = "ALLOW"
    DENY = "DENY"
    AUTO = "AUTO"


@dataclass(frozen=True)
class BoxDim:
    """Dimensions along canonical axes (x: length, y: width, z: height) in meters."""
    x: float
    y: float
    z: float

    def __post_init__(self):
        if self.x <= 0 or self.y <= 0 or self.z <= 0:
            raise ValueError(f"Box dimensions must be strictly positive: ({self.x}, {self.y}, {self.z})")

    @property
    def volume(self) -> float:
        return self.x * self.y * self.z


@dataclass(frozen=True)
class Point3D:
    """Canonical 3D coordinates (x, y, z) in meters."""
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class Orientation3D:
    """
    Concrete 3D bounding dimension after applying rotation to the SKU box.
    dx, dy, dz are the occupied lengths along canonical axes x, y, z.
    name is a descriptive label e.g., 'UPRIGHT_XY', 'UPRIGHT_YX', 'FLAT_XZ', etc.
    """
    dx: float
    dy: float
    dz: float
    name: str = "DEFAULT"
    is_upright: bool = True
    is_flat: bool = False
    is_side: bool = False

    @property
    def volume(self) -> float:
        return self.dx * self.dy * self.dz


@dataclass(frozen=True)
class OrientationRule:
    """Context and structural conditions governing an orientation family."""
    orientation: OrientationMode
    allowed_regions: Tuple[OrientationRegion, ...]
    min_support_ratio: Optional[float] = None
    max_top_fill_layers: Optional[int] = None
    max_base_height: Optional[float] = None
    min_base_height: Optional[float] = None
    condition: str = "ALWAYS"

    def allows(
        self,
        region: OrientationRegion,
        base_height: Optional[float] = None,
        support_ratio: Optional[float] = None,
    ) -> bool:
        if region not in self.allowed_regions:
            return False
        if base_height is not None:
            if self.min_base_height is not None and base_height < self.min_base_height:
                return False
            if self.max_base_height is not None and base_height > self.max_base_height:
                return False
        if support_ratio is not None and self.min_support_ratio is not None:
            if support_ratio < self.min_support_ratio:
                return False
        return True


@dataclass(frozen=True)
class OrientationPolicy:
    """
    Defines allowed orientations per placement context.
    Default allows standard upright rotations around canonical Z axis.
    """
    allow_upright: bool = True
    allow_flat: bool = False
    allow_side: bool = False
    allowed_contexts_for_flat: Tuple[PlacementContext, ...] = (PlacementContext.TOP_FILL, PlacementContext.GAP_FILL, PlacementContext.DOOR_SEAL)
    allowed_contexts_for_side: Tuple[PlacementContext, ...] = (PlacementContext.GAP_FILL, PlacementContext.DOOR_SEAL)
    max_flat_stack_layers: int = 1
    flat_orientation_penalty: float = 50.0
    side_orientation_penalty: float = 100.0
    rules: Tuple[OrientationRule, ...] = ()
    source: PolicySource = PolicySource.DEFAULT

    @staticmethod
    def context_region(context: PlacementContext) -> OrientationRegion:
        if context == PlacementContext.TOP_FILL:
            return OrientationRegion.TOP_FILL
        if context in (PlacementContext.DOOR_SEAL, PlacementContext.GAP_FILL):
            return OrientationRegion.DOOR_ZONE
        return OrientationRegion.MAIN_BODY

    def effective_rules(self) -> Tuple[OrientationRule, ...]:
        """Return explicit rules, or a compatibility projection of legacy flags."""
        if self.rules:
            return self.rules
        rules: List[OrientationRule] = []
        if self.allow_upright:
            rules.append(OrientationRule(
                orientation=OrientationMode.UPRIGHT,
                allowed_regions=(OrientationRegion.MAIN_BODY, OrientationRegion.TOP_FILL, OrientationRegion.DOOR_ZONE),
            ))
        if self.allow_flat:
            regions = tuple(dict.fromkeys(self.context_region(c) for c in self.allowed_contexts_for_flat))
            rules.append(OrientationRule(
                orientation=OrientationMode.FLAT,
                allowed_regions=regions,
                max_top_fill_layers=self.max_flat_stack_layers,
                condition="UPRIGHT_DOES_NOT_FIT",
            ))
        if self.allow_side:
            regions = tuple(dict.fromkeys(self.context_region(c) for c in self.allowed_contexts_for_side))
            rules.append(OrientationRule(
                orientation=OrientationMode.SIDE,
                allowed_regions=regions,
            ))
        return tuple(rules)

    def rule_for(self, mode: OrientationMode, context: PlacementContext) -> Optional[OrientationRule]:
        region = self.context_region(context)
        return next((r for r in self.effective_rules() if r.orientation == mode and region in r.allowed_regions), None)

    def get_legal_orientations(self, base_box: BoxDim, context: PlacementContext) -> List[Orientation3D]:
        """
        Generate legal concrete Orientations for base_box given the current PlacementContext.
        base_box has canonical dimensions (w, d, h) where:
          - upright rotations: z dimension = base_box.z (height maintained upright)
            ori 1: (dx=x, dy=y, dz=z)
            ori 2: (dx=y, dy=x, dz=z)
          - flat rotations: z dimension = base_box.y (or base_box.x if smallest)
            ori 3: (dx=x, dy=z, dz=y)
            ori 4: (dx=z, dy=x, dz=y)
          - side rotations: z dimension = base_box.x
            ori 5: (dx=y, dy=z, dz=x)
            ori 6: (dx=z, dy=y, dz=x)
        """
        oris: List[Orientation3D] = []
        x, y, z = base_box.x, base_box.y, base_box.z

        # 1. Upright orientations
        if self.rule_for(OrientationMode.UPRIGHT, context):
            oris.append(Orientation3D(dx=x, dy=y, dz=z, name="UPRIGHT_NORMAL", is_upright=True))
            if abs(x - y) > 1e-5:
                oris.append(Orientation3D(dx=y, dy=x, dz=z, name="UPRIGHT_ROTATED", is_upright=True))

        # 2. Flat orientations (only if permitted and context is allowed)
        if self.rule_for(OrientationMode.FLAT, context):
            oris.append(Orientation3D(dx=x, dy=z, dz=y, name="FLAT_XZ", is_flat=True, is_upright=False))
            if abs(x - z) > 1e-5:
                oris.append(Orientation3D(dx=z, dy=x, dz=y, name="FLAT_ZX", is_flat=True, is_upright=False))

        # 3. Side orientations (only if permitted and context is allowed)
        if self.rule_for(OrientationMode.SIDE, context):
            oris.append(Orientation3D(dx=y, dy=z, dz=x, name="SIDE_YZ", is_side=True, is_upright=False))
            if abs(y - z) > 1e-5:
                oris.append(Orientation3D(dx=z, dy=y, dz=x, name="SIDE_ZY", is_side=True, is_upright=False))

        return oris


@dataclass(frozen=True)
class StackingPolicy:
    """Rules governing stacking and layer constraints for a SKU."""
    max_stack_layers: Optional[int] = None
    max_bearing_kg: Optional[float] = None
    max_pressure_kg_m2: Optional[float] = None
    min_support_ratio: float = 0.70
    max_unsupported_span_m: float = 0.10
    allow_stacking_on_top: bool = True
    must_be_on_floor: bool = False
    stack_on_self: bool = True
    allowed_above_categories: Tuple[CargoClass, ...] = ()
    forbidden_above_categories: Tuple[CargoClass, ...] = ()
    source: PolicySource = PolicySource.DEFAULT


@dataclass(frozen=True)
class GeometryPolicy:
    source: PolicySource = PolicySource.DEFAULT
    clearance_m: float = 0.0


@dataclass(frozen=True)
class PlacementPolicy:
    source: PolicySource = PolicySource.DEFAULT
    load_priority: int = 0
    reduction_allowed: bool = False
    minimum_quantity: int = 0
    packing_roles: Tuple[PackingRole, ...] = (PackingRole.MAIN_WALL,)


@dataclass(frozen=True)
class CompressionPolicy:
    source: PolicySource = PolicySource.DEFAULT
    max_top_load_kg: Optional[float] = None
    max_pressure_kg_m2: Optional[float] = None


@dataclass(frozen=True)
class StabilityPolicy:
    source: PolicySource = PolicySource.DEFAULT
    anti_tip_required: bool = True
    min_support_ratio: float = 0.70
    max_unsupported_span_m: float = 0.10
    group_stability_required: bool = True
    wall_stability_required: bool = True


@dataclass(frozen=True)
class TopFillPolicy:
    source: PolicySource = PolicySource.DEFAULT
    admission_state: TopFillAdmissionState = TopFillAdmissionState.AUTO
    enabled: bool = False
    allowed_orientations: Tuple[OrientationMode, ...] = ()
    conditional_orientations: Tuple[OrientationMode, ...] = ()
    max_layers: int = 0
    min_base_height: float = 0.0
    min_support_ratio: float = 0.70
    residual_height_target: Optional[float] = None


@dataclass(frozen=True)
class ZonePolicy:
    source: PolicySource = PolicySource.DEFAULT
    preferred: Tuple[ZoneType, ...] = ()
    required: Tuple[ZoneType, ...] = ()
    forbidden: Tuple[ZoneType, ...] = ()


@dataclass(frozen=True)
class HandlingPolicy:
    source: PolicySource = PolicySource.DEFAULT
    keep_upright: bool = True
    fragile: bool = False
    special_instructions: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CargoProfile:
    """Authoritative declarative cargo constraints compiled into existing solver policies."""
    geometry_policy: GeometryPolicy = field(default_factory=GeometryPolicy)
    orientation_policy: OrientationPolicy = field(default_factory=OrientationPolicy)
    placement_policy: PlacementPolicy = field(default_factory=PlacementPolicy)
    stack_policy: StackingPolicy = field(default_factory=StackingPolicy)
    compression_policy: CompressionPolicy = field(default_factory=CompressionPolicy)
    stability_policy: StabilityPolicy = field(default_factory=StabilityPolicy)
    top_fill_policy: TopFillPolicy = field(default_factory=TopFillPolicy)
    zone_policy: ZonePolicy = field(default_factory=ZonePolicy)
    handling_policy: HandlingPolicy = field(default_factory=HandlingPolicy)
    source_audit: Tuple[Tuple[str, PolicySource], ...] = ()


@dataclass(frozen=True)
class QuantityPlan:
    """
    Defines required, minimum and maximum target quantities.
    is_elastic: True if quantity can be flexibly reduced if space is constrained.
    """
    required: int
    min_quantity: int = 0
    max_quantity: Optional[int] = None
    is_elastic: bool = False

    def __post_init__(self):
        if self.required < 0:
            raise ValueError(f"Required quantity must be >= 0: {self.required}")
        if self.min_quantity < 0 or self.min_quantity > self.required:
            raise ValueError(f"Invalid min_quantity: {self.min_quantity} (required: {self.required})")
        if self.max_quantity is not None and self.max_quantity < self.required:
            raise ValueError(f"max_quantity {self.max_quantity} < required {self.required}")


@dataclass
class ContainerSpec:
    """Canonical Container specification in canonical coordinate frame (x, y, z)."""
    code: str
    inner_dim: BoxDim
    max_payload_kg: float
    tare_weight_kg: float = 0.0
    door_zone_length_m: float = 1.2
    rear_zone_length_m: float = 1.0

    @property
    def Lx(self) -> float:
        return self.inner_dim.x

    @property
    def Ly(self) -> float:
        return self.inner_dim.y

    @property
    def Lz(self) -> float:
        return self.inner_dim.z

    @property
    def volume(self) -> float:
        return self.inner_dim.volume


@dataclass
class CargoSKU:
    """
    Canonical Cargo SKU entity.
    All dimensions are canonical BoxDim (x, y, z in meters).
    All weight in kg.
    Contains compiled policies and constraints (No free-text requirements in core).
    """
    sku_id: str
    name: str
    box: BoxDim
    weight_kg: float
    quantity: QuantityPlan
    orientation_policy: OrientationPolicy = field(default_factory=OrientationPolicy)
    stacking_policy: StackingPolicy = field(default_factory=StackingPolicy)
    cargo_class: CargoClass = CargoClass.STANDARD
    packing_roles: Tuple[PackingRole, ...] = (PackingRole.MAIN_WALL,)
    target_zone: Optional[ZoneType] = None
    color_hex: Optional[int] = None
    source_requirement_text: str = ""
    cargo_profile: Optional[CargoProfile] = None

    def __post_init__(self):
        if self.weight_kg < 0:
            raise ValueError(f"Weight cannot be negative: {self.weight_kg}")


@dataclass(frozen=True)
class CargoInstance:
    """Concrete instance of a CargoSKU to be placed."""
    instance_id: str
    sku_id: str
    box: BoxDim
    weight_kg: float
    cargo_class: CargoClass
    stacking_policy: StackingPolicy


@dataclass(frozen=True)
class Placement:
    """Authoritative committed placement in Container canonical coordinates."""
    placement_id: str
    instance_id: str
    sku_id: str
    position: Point3D
    orientation: Orientation3D
    weight_kg: float
    context: PlacementContext
    step_index: int = 0

    @property
    def min_x(self) -> float:
        return self.position.x

    @property
    def max_x(self) -> float:
        return self.position.x + self.orientation.dx

    @property
    def min_y(self) -> float:
        return self.position.y

    @property
    def max_y(self) -> float:
        return self.position.y + self.orientation.dy

    @property
    def min_z(self) -> float:
        return self.position.z

    @property
    def max_z(self) -> float:
        return self.position.z + self.orientation.dz

    @property
    def volume(self) -> float:
        return self.orientation.volume

    def aabb(self) -> Tuple[float, float, float, float, float, float]:
        """Returns (min_x, min_y, min_z, max_x, max_y, max_z)."""
        return (self.min_x, self.min_y, self.min_z, self.max_x, self.max_y, self.max_z)


def compute_problem_hash(container: ContainerSpec, cargo_list: List[CargoSKU], options: Optional[Dict[str, Any]] = None) -> str:
    """Computes a deterministic SHA-256 problem hash for canonical problem definition."""
    data = {
        "container": {
            "code": container.code,
            "x": round(container.Lx, 6),
            "y": round(container.Ly, 6),
            "z": round(container.Lz, 6),
            "maxPayloadKg": round(container.max_payload_kg, 3),
        },
        "cargo": [
            {
                "sku": s.sku_id,
                "x": round(s.box.x, 6),
                "y": round(s.box.y, 6),
                "z": round(s.box.z, 6),
                "weightKg": round(s.weight_kg, 3),
                "qty": s.quantity.required,
                "elastic": s.quantity.is_elastic,
                "zone": s.target_zone.value if s.target_zone else None,
                "roles": [r.value for r in s.packing_roles],
            }
            for s in sorted(cargo_list, key=lambda x: x.sku_id)
        ],
        "options": options or {}
    }
    raw_str = json.dumps(data, sort_keys=True)
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Universal Tensor & Container Abstractions (Legacy / Interop Models)
# ---------------------------------------------------------------------------

class UniversalZone(str, Enum):
    INNER = "INNER"        # Closest to inner wall (X: 0 -> L/3)
    MIDDLE = "MIDDLE"      # Middle body (X: L/3 -> 2L/3)
    DOOR = "DOOR"          # Close to container door (X: 2L/3 -> L)
    FLEXIBLE = "FLEXIBLE"  # No strict zone preference


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
    must_be_on_floor: bool = False
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

