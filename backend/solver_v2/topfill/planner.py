"""
Top Fill Planner and Conditional Flat Display Placement Engine for Solver V2 (Agent 08).
Implements the cleanroom top-fill specifications from docs/ORIENTATION_TOPFILL.md and tests_spec/TOPFILL_TESTS.md.
"""
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any, Set
from collections import Counter
import math

from backend.solver_v2.domain.models import (
    BoxDim,
    Point3D,
    Orientation3D,
    CargoSKU,
    Placement,
    PlacementContext,
    ContainerSpec,
    OrientationMode,
    OrientationPolicy,
    TopFillAdmissionState,
    ZoneType,
)
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.orientation.manager import OrientationEngine
from backend.solver_v2.patterns.models import PackedBlock, ItemOffset, PatternType
from backend.solver_v2.physics.support_graph import SupportGraph
from backend.solver_v2.physics.load_propagation import LoadPropagationEngine
from backend.solver_v2.physics.contact_graph import ContactGraph
from backend.solver_v2.world.state import WorldState
from backend.solver_v2.structure.wall_model import LogicalWall, TopSurfaceCell
from backend.solver_v2.structure.cavity_classifier import AdvancedCavityClassifier
from backend.solver_v2.candidates.generator import CandidatePlacement
from backend.solver_v2.feasibility.pipeline import HardValidationPipeline
from backend.solver_v2.zones.manager import AdaptiveZoneManager
from backend.solver_v2.physics.evaluator import PhysicsStabilityEngine
from backend.solver_v2.spaces.types import AnchorCategory
from backend.solver_v2.quantity.manager import QuantityManager, SpatialReservationManager


@dataclass(frozen=True)
class ConditionalFlatCheckResult:
    """Detailed multi-criteria validation result for conditional flat placement."""
    is_valid: bool
    is_upright_preferred: bool
    upright_fits: bool
    flat_policy_allowed: bool
    support_ratio: float
    support_ratio_passed: bool
    unsupported_span_m: float
    unsupported_span_passed: bool
    lower_compression_passed: bool
    flat_layer_count: int
    flat_layer_limit_passed: bool
    allow_stacking_on_top_passed: bool
    penalty_score: float
    rejection_reasons: Tuple[str, ...]

    @property
    def primary_rejection_reason(self) -> Optional[str]:
        return self.rejection_reasons[0] if self.rejection_reasons else None


@dataclass(frozen=True)
class TopFillSpace:
    """An identified residual headspace above committed cargo."""
    space_aabb: AABB
    base_cargo_ids: Tuple[str, ...]
    min_headspace_z: float
    max_headspace_z: float
    available_height: float


@dataclass(frozen=True)
class TopFillEligibility:
    sku_id: str
    geometrically_compatible: bool
    policy_compatible: bool
    physically_compatible: bool
    inventory_available: bool
    eligible: bool
    rejection_reasons: Tuple[str, ...] = ()


@dataclass(frozen=True)
class TopFillAdmissionDiagnostic:
    region_id: str
    sku_id: str
    policy_state: str
    admission_source: str
    orientation: Optional[str]
    geometry_pass: bool
    inventory_pass: bool
    support_pass: bool
    bridge_pass: bool
    compression_pass: bool
    stack_pass: bool
    stability_pass: bool
    zone_pass: bool
    handling_pass: bool
    collision_pass: bool
    oob_pass: bool
    effective_max_layers: int
    admitted: bool
    rejection_reason: str


@dataclass(frozen=True)
class RegionLocalCandidate:
    """One admitted SKU/orientation retained in a region-local candidate pool."""
    sku_id: str
    orientation: Orientation3D
    remaining_quantity: int
    effective_max_layers: int
    support_requirement: float
    compression_limit: float
    stability_constraints: Dict[str, Any]
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sku": self.sku_id,
            "orientation": self.orientation.name,
            "footprint_x": self.orientation.dx,
            "footprint_y": self.orientation.dy,
            "height": self.orientation.dz,
            "unit_volume": self.orientation.volume,
            "remaining_quantity": self.remaining_quantity,
            "effective_max_layers": self.effective_max_layers,
            "support_requirement": self.support_requirement,
            "compression_limit": self.compression_limit,
            "stability_constraints": self.stability_constraints,
            "source": self.source,
        }


@dataclass(frozen=True)
class ResidualRectangle:
    """Non-overlapping guillotine residual on one supported Z plane."""
    rectangle_id: str
    x0: float
    x1: float
    y0: float
    y1: float
    base_z: float
    layer: int

    @property
    def area(self) -> float:
        return max(0.0, self.x1 - self.x0) * max(0.0, self.y1 - self.y0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rectangle_id": self.rectangle_id,
            "x_range": [self.x0, self.x1],
            "y_range": [self.y0, self.y1],
            "base_z": self.base_z,
            "layer": self.layer,
            "area": self.area,
        }


@dataclass(frozen=True)
class TopFillRegion:
    """Continuous, load-bearing region extracted from a LogicalWall TopSurface."""
    region_id: str
    logical_wall_id: str
    x_range: Tuple[float, float]
    y_range: Tuple[float, float]
    base_z: float
    available_height: float
    support_area: float
    support_coverage: float
    local_flatness: float
    max_load: float
    allowed_skus: Tuple[str, ...]
    supporting_carton_ids: Tuple[str, ...] = ()
    geometrically_compatible: Tuple[str, ...] = ()
    policy_compatible: Tuple[str, ...] = ()
    physically_compatible: Tuple[str, ...] = ()
    inventory_available: Tuple[str, ...] = ()
    eligible: Tuple[str, ...] = ()
    eligibility_by_sku: Dict[str, TopFillEligibility] = field(default_factory=dict)

    @property
    def aabb(self) -> AABB:
        return AABB(
            self.x_range[0], self.y_range[0], self.base_z,
            self.x_range[1], self.y_range[1], self.base_z + self.available_height,
        )

    @property
    def usable_volume(self) -> float:
        # Use the actual continuous supporting area, not the component's bounding
        # rectangle (which would over-count holes in L-shaped residual surfaces).
        return self.support_area * self.available_height


@dataclass(frozen=True)
class TopFillCandidateEvaluation:
    """Unified gate result using orientation, hard validation, load and stability engines."""
    is_valid: bool
    hard_validation_passed: bool
    orientation_context_passed: bool
    support_passed: bool
    compression_passed: bool
    item_stability_passed: bool
    cluster_stability_passed: bool
    wall_stability_passed: bool
    layer_limit_passed: bool
    cavity_passed: bool
    rejection_reasons: Tuple[str, ...]


@dataclass
class TopFillDeploymentResult:
    placed: List[Placement] = field(default_factory=list)
    rejected_insufficient_support: int = 0
    rejected_compression: int = 0
    rejected_orientation_context: int = 0
    rejected_max_layers: int = 0
    rejected_stability: int = 0
    region_funnels: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    region_plans: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @property
    def placed_count(self) -> int:
        return len(self.placed)


class TopFillPlanner:
    """
    Identifies top residual headspace and plans conditional flat / upright cargo filling.
    """

    def __init__(
        self,
        container: ContainerSpec,
        orientation_engine: Optional[OrientationEngine] = None,
        load_engine: Optional[LoadPropagationEngine] = None,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
    ):
        self.container = container
        self.orientation_engine = orientation_engine or OrientationEngine(geom_epsilon=geom_epsilon)
        self.load_engine = load_engine or LoadPropagationEngine()
        self.geom_epsilon = geom_epsilon
        self.hard_validator = HardValidationPipeline(geom_epsilon=geom_epsilon)
        self.physics_engine = PhysicsStabilityEngine(geom_epsilon=geom_epsilon)

    def extract_top_fill_regions(
        self,
        world_state: WorldState,
        cargo_catalog: Optional[Dict[str, CargoSKU]] = None,
        min_support_area_m2: float = 0.01,
        height_tolerance_m: float = 0.02,
        qty_mgr: Optional[QuantityManager] = None,
    ) -> List[TopFillRegion]:
        """Extract continuous coplanar support components from LogicalWall.top_surface."""
        catalog = cargo_catalog or world_state._cargo_catalog
        regions: List[TopFillRegion] = []
        for wall in world_state.get_walls():
            if not isinstance(wall, LogicalWall) or wall.top_surface is None:
                continue
            cells = [c for c in wall.top_surface.cells if c.z < self.container.Lz - self.geom_epsilon]
            if not cells:
                continue
            res = wall.top_surface.resolution_m
            keyed: Dict[Tuple[int, int], TopSurfaceCell] = {
                (int(round(c.min_x / res)), int(round(c.min_y / res))): c for c in cells
            }
            visited: Set[Tuple[int, int]] = set()
            wall_region_idx = 1
            for key, first in sorted(keyed.items()):
                if key in visited:
                    continue
                component: List[TopSurfaceCell] = []
                queue = [key]
                visited.add(key)
                while queue:
                    current = queue.pop()
                    cell = keyed[current]
                    component.append(cell)
                    for neighbor in ((current[0] - 1, current[1]), (current[0] + 1, current[1]),
                                     (current[0], current[1] - 1), (current[0], current[1] + 1)):
                        other = keyed.get(neighbor)
                        if other is not None and neighbor not in visited and abs(other.z - cell.z) <= height_tolerance_m:
                            visited.add(neighbor)
                            queue.append(neighbor)

                support_area = sum(c.area_m2 for c in component)
                if support_area < min_support_area_m2:
                    continue
                x0 = min(c.min_x for c in component)
                x1 = max(c.max_x for c in component)
                y0 = min(c.min_y for c in component)
                y1 = max(c.max_y for c in component)
                bbox_area = max((x1 - x0) * (y1 - y0), self.geom_epsilon)
                coverage = min(1.0, support_area / bbox_area)
                mean_z = sum(c.z * c.area_m2 for c in component) / support_area
                variance = sum((c.z - mean_z) ** 2 * c.area_m2 for c in component) / support_area
                flatness = 1.0 / (1.0 + 2.0 * math.sqrt(variance))
                base_z = max(c.z for c in component)
                supporting_ids = tuple(sorted({c.placement_id for c in component}))
                max_load = self._region_max_load(world_state, supporting_ids, catalog)
                eligibility = {
                    sku.sku_id: self._evaluate_region_eligibility(
                        sku, x1 - x0, y1 - y0, base_z,
                        self.container.Lz - base_z, coverage, max_load, qty_mgr,
                    )
                    for sku in catalog.values()
                }
                geometric = tuple(sorted(k for k, v in eligibility.items() if v.geometrically_compatible))
                policy = tuple(sorted(k for k, v in eligibility.items() if v.policy_compatible))
                physical = tuple(sorted(k for k, v in eligibility.items() if v.physically_compatible))
                inventory = tuple(sorted(k for k, v in eligibility.items() if v.inventory_available))
                eligible = tuple(sorted(k for k, v in eligibility.items() if v.eligible))
                regions.append(TopFillRegion(
                    region_id=f"{wall.wall_id}_TOP_{wall_region_idx:03d}",
                    logical_wall_id=wall.wall_id,
                    x_range=(x0, x1),
                    y_range=(y0, y1),
                    base_z=base_z,
                    available_height=max(0.0, self.container.Lz - base_z),
                    support_area=support_area,
                    support_coverage=coverage,
                    local_flatness=flatness,
                    max_load=max_load,
                    allowed_skus=eligible,
                    supporting_carton_ids=supporting_ids,
                    geometrically_compatible=geometric,
                    policy_compatible=policy,
                    physically_compatible=physical,
                    inventory_available=inventory,
                    eligible=eligible,
                    eligibility_by_sku=eligibility,
                ))
                wall_region_idx += 1
        regions.sort(key=lambda r: (r.usable_volume, r.support_area, r.local_flatness), reverse=True)
        return regions

    def _region_max_load(self, world_state: WorldState, supporting_ids: Tuple[str, ...], catalog: Dict[str, CargoSKU]) -> float:
        load_report = self.load_engine.compute_loads(world_state.support_graph, catalog)
        remaining: List[float] = []
        for pid in supporting_ids:
            placement = world_state._placement_map.get(pid)
            if placement is None:
                continue
            sku = catalog.get(placement.sku_id)
            if sku is None or not sku.stacking_policy.allow_stacking_on_top:
                return 0.0
            limit = sku.stacking_policy.max_bearing_kg
            if limit is not None:
                current = load_report.item_reports.get(pid)
                remaining.append(max(0.0, limit - (current.accumulated_upper_load_kg if current else 0.0)))
        return min(remaining) if remaining else max(0.0, self.container.max_payload_kg - world_state.total_weight_kg)

    def _sku_can_use_region(self, sku: CargoSKU, width_x: float, width_y: float, base_z: float, available_height: float, support_coverage: float) -> bool:
        target = AABB(0.0, 0.0, base_z, width_x, width_y, base_z + available_height)
        candidates = self.orientation_engine.get_candidate_orientations(
            sku, PlacementContext.TOP_FILL, target_space=target,
            min_support_ratio=support_coverage, base_height=base_z,
        )
        return bool(candidates) and not sku.stacking_policy.must_be_on_floor

    def _evaluate_region_eligibility(
        self,
        sku: CargoSKU,
        width_x: float,
        width_y: float,
        base_z: float,
        available_height: float,
        support_coverage: float,
        max_load: float,
        qty_mgr: Optional[QuantityManager],
    ) -> TopFillEligibility:
        """Keep geometry, declared policy, physics and inventory as independent facts."""
        eps = self.geom_epsilon
        orientations = (
            (sku.box.x, sku.box.y, sku.box.z), (sku.box.y, sku.box.x, sku.box.z),
            (sku.box.x, sku.box.z, sku.box.y), (sku.box.z, sku.box.x, sku.box.y),
            (sku.box.y, sku.box.z, sku.box.x), (sku.box.z, sku.box.y, sku.box.x),
        )
        geometry_ok = any(dx <= width_x + eps and dy <= width_y + eps and dz <= available_height + eps
                          for dx, dy, dz in orientations)
        rules = [r for r in sku.orientation_policy.effective_rules() if OrientationPolicy.context_region(PlacementContext.TOP_FILL) in r.allowed_regions]
        profile = sku.cargo_profile
        top_policy = profile.top_fill_policy if profile is not None else None
        policy_ok = bool(rules)
        if top_policy is not None:
            if top_policy.admission_state == TopFillAdmissionState.DENY:
                policy_ok = False
            elif top_policy.admission_state == TopFillAdmissionState.AUTO:
                # AUTO may only use already-declared TOP_FILL orientation rules.
                policy_ok = (
                    bool(rules)
                    and base_z + eps >= top_policy.min_base_height
                    and support_coverage + eps >= top_policy.min_support_ratio
                    and ZoneType.ROOF_ONLY not in profile.zone_policy.forbidden
                )
            else:
                policy_ok = (
                    top_policy.enabled
                    and bool(set(top_policy.allowed_orientations + top_policy.conditional_orientations))
                    and base_z + eps >= top_policy.min_base_height
                    and support_coverage + eps >= top_policy.min_support_ratio
                    and ZoneType.ROOF_ONLY not in profile.zone_policy.forbidden
                )
        required_support = max(
            sku.stacking_policy.min_support_ratio,
            top_policy.min_support_ratio if top_policy is not None else 0.0,
        )
        physics_ok = (
            not sku.stacking_policy.must_be_on_floor
            and support_coverage + eps >= required_support
            and sku.weight_kg <= max_load + eps
        )
        inventory_ok = (
            qty_mgr.can_place(sku.sku_id, context=PlacementContext.TOP_FILL)
            if qty_mgr is not None else sku.quantity.required > 0
        )
        reasons: List[str] = []
        if not geometry_ok:
            reasons.append("GEOMETRY_INCOMPATIBLE")
        if not policy_ok:
            reasons.append("POLICY_INCOMPATIBLE")
        if not physics_ok:
            if support_coverage + eps < required_support:
                reasons.append("INSUFFICIENT_SUPPORT")
            if sku.weight_kg > max_load + eps:
                reasons.append("COMPRESSION_LIMIT")
            if sku.stacking_policy.must_be_on_floor:
                reasons.append("FLOOR_ONLY")
        if not inventory_ok:
            reasons.append("INVENTORY_UNAVAILABLE")
        eligible = geometry_ok and policy_ok and physics_ok and inventory_ok
        return TopFillEligibility(
            sku_id=sku.sku_id,
            geometrically_compatible=geometry_ok,
            policy_compatible=policy_ok,
            physically_compatible=physics_ok,
            inventory_available=inventory_ok,
            eligible=eligible,
            rejection_reasons=tuple(reasons),
        )

    def diagnose_region_admission(
        self,
        world_state: WorldState,
        region: TopFillRegion,
        sku: CargoSKU,
        inventory_available: bool,
        zone_mgr: Optional[AdaptiveZoneManager] = None,
    ) -> TopFillAdmissionDiagnostic:
        """Explain admission without mutating policy, inventory, or WorldState."""
        profile = sku.cargo_profile
        state = (
            profile.top_fill_policy.admission_state
            if profile is not None else TopFillAdmissionState.DENY
        )
        source = profile.top_fill_policy.source.value if profile is not None else "DEFAULT"
        eligibility = region.eligibility_by_sku.get(sku.sku_id)
        geometry_pass = bool(eligibility and eligibility.geometrically_compatible)
        support_required = sku.stacking_policy.min_support_ratio
        if profile is not None:
            support_required = max(support_required, profile.top_fill_policy.min_support_ratio)
        support_pass = region.support_coverage + self.geom_epsilon >= support_required
        bridge_pass = support_pass and region.local_flatness >= 0.95
        compression_pass = sku.weight_kg <= region.max_load + self.geom_epsilon

        orientations = self.orientation_engine.get_candidate_orientations(
            sku=sku,
            context=PlacementContext.TOP_FILL,
            target_space=region.aabb,
            min_support_ratio=region.support_coverage,
            base_height=region.base_z,
        )
        handling_pass = True
        if profile is not None and profile.handling_policy.keep_upright:
            upright = [candidate for candidate in orientations if candidate.orientation.is_upright]
            handling_pass = bool(upright)
            orientations = upright

        chosen = orientations[0].orientation if orientations else None
        effective_layers = self.calculate_layer_capacity(sku, chosen, region) if chosen is not None else 0
        stack_pass = not sku.stacking_policy.must_be_on_floor and effective_layers > 0
        catalog = world_state._cargo_catalog
        for pid in region.supporting_carton_ids:
            lower = world_state._placement_map.get(pid)
            lower_sku = catalog.get(lower.sku_id) if lower is not None else None
            if lower_sku is None:
                continue
            lower_policy = lower_sku.stacking_policy
            category = sku.cargo_class
            if (
                not lower_policy.allow_stacking_on_top
                or (not lower_policy.stack_on_self and lower.sku_id == sku.sku_id)
                or category in lower_policy.forbidden_above_categories
                or (lower_policy.allowed_above_categories and category not in lower_policy.allowed_above_categories)
            ):
                stack_pass = False
                break

        stability_pass = (
            chosen is not None
            and region.local_flatness >= 0.95
            and support_pass
            and effective_layers > 0
        )
        zone_pass = False
        collision_pass = False
        oob_pass = False
        if chosen is not None:
            candidate_box = AABB(
                region.x_range[0], region.y_range[0], region.base_z,
                region.x_range[0] + chosen.dx,
                region.y_range[0] + chosen.dy,
                region.base_z + chosen.dz,
            )
            oob_pass = candidate_box.is_within_bounds(
                self.container.Lx, self.container.Ly, self.container.Lz, eps=self.geom_epsilon,
            )
            collision_pass = not world_state.spatial_index.query_intersect(candidate_box, eps=self.geom_epsilon)
            active_zone = zone_mgr or AdaptiveZoneManager(self.container)
            zone_pass, _ = active_zone.check_hard_zone_compliance(
                sku, candidate_box.min_x, candidate_box.min_y, candidate_box.min_z,
                chosen.dx, chosen.dy, chosen.dz,
            )

        policy_rule_pass = bool(eligibility and eligibility.policy_compatible)
        admitted = all((
            state != TopFillAdmissionState.DENY,
            policy_rule_pass,
            geometry_pass,
            inventory_available,
            chosen is not None,
            support_pass,
            bridge_pass,
            compression_pass,
            stack_pass,
            stability_pass,
            zone_pass,
            handling_pass,
            collision_pass,
            oob_pass,
        ))
        if state == TopFillAdmissionState.DENY:
            rejection = "USER_DENY"
        elif state == TopFillAdmissionState.ALLOW and not admitted:
            rejection = "USER_RULE"
        elif not geometry_pass:
            rejection = "AUTO_GEOMETRY_FAIL"
        elif not inventory_available:
            rejection = "AUTO_INVENTORY_FAIL"
        elif not handling_pass:
            rejection = "AUTO_HANDLING_FAIL"
        elif chosen is None or not collision_pass or not oob_pass:
            rejection = "AUTO_GEOMETRY_FAIL"
        elif not support_pass or not bridge_pass:
            rejection = "AUTO_SUPPORT_FAIL"
        elif not compression_pass:
            rejection = "AUTO_COMPRESSION_FAIL"
        elif not stack_pass:
            rejection = "AUTO_STACK_FAIL"
        elif not stability_pass:
            rejection = "AUTO_STABILITY_FAIL"
        elif not zone_pass:
            rejection = "AUTO_ZONE_FAIL"
        elif state == TopFillAdmissionState.AUTO:
            rejection = "AUTO_PASS"
        else:
            rejection = "USER_RULE"
        return TopFillAdmissionDiagnostic(
            region_id=region.region_id,
            sku_id=sku.sku_id,
            policy_state=state.value,
            admission_source=source,
            orientation=chosen.name if chosen is not None else None,
            geometry_pass=geometry_pass,
            inventory_pass=inventory_available,
            support_pass=support_pass,
            bridge_pass=bridge_pass,
            compression_pass=compression_pass,
            stack_pass=stack_pass,
            stability_pass=stability_pass,
            zone_pass=zone_pass,
            handling_pass=handling_pass,
            collision_pass=collision_pass,
            oob_pass=oob_pass,
            effective_max_layers=effective_layers,
            admitted=admitted,
            rejection_reason=rejection,
        )

    def identify_top_spaces(
        self,
        world_state: WorldState,
        min_top_height_m: float = 0.05,
    ) -> List[TopFillSpace]:
        """
        Identifies headspace above existing cargo placements up to the container ceiling (Lz).
        """
        return [
            TopFillSpace(
                space_aabb=region.aabb,
                base_cargo_ids=region.supporting_carton_ids,
                min_headspace_z=region.base_z,
                max_headspace_z=self.container.Lz,
                available_height=round(region.available_height, 4),
            )
            for region in self.extract_top_fill_regions(world_state)
            if region.available_height >= min_top_height_m - self.geom_epsilon
        ]

    def evaluate_conditional_flat_placement(
        self,
        sku: CargoSKU,
        candidate_placement: Placement,
        world_state: WorldState,
        target_space: Optional[AABB] = None,
        catalog: Optional[Dict[str, CargoSKU]] = None,
    ) -> ConditionalFlatCheckResult:
        """
        Strictly evaluates all criteria from docs/ORIENTATION_TOPFILL.md & tests_spec/TOPFILL_TESTS.md:
        1. Upright preference vs fit: if target space has room for upright, upright is preferred (penalty 0 vs >0).
        2. Flat policy permitted: policy.allow_flat must be True and context must be allowed.
        3. Support ratio: support ratio >= sku.stacking_policy.min_support_ratio.
        4. Unsupported span: max unsupported span <= sku.stacking_policy.max_unsupported_span_m.
        5. Lower cargo compression: accumulated upper load <= lower items' max_bearing_kg.
        6. Lower cargo top-stacking: lower items must have allow_stacking_on_top == True.
        7. Flat layer count: consecutive flat layers <= policy.max_flat_stack_layers.
        """
        reasons: List[str] = []
        eps = self.geom_epsilon
        policy = sku.orientation_policy
        stack_policy = sku.stacking_policy

        # Check if placement orientation is flat vs upright
        is_flat = candidate_placement.orientation.is_flat
        is_upright = candidate_placement.orientation.is_upright
        cand_aabb = AABB.from_placement(candidate_placement)

        # 1. Upright fit check in target headspace
        upright_height = sku.box.z
        space_height = target_space.dz if target_space is not None else (self.container.Lz - candidate_placement.min_z)
        upright_fits = (space_height + eps) >= upright_height

        # If upright fits and we are in main body / or topfill with enough room, upright is preferred
        is_upright_preferred = upright_fits

        # 2. Flat policy check
        flat_policy_allowed = True
        if is_flat:
            flat_rule = policy.rule_for(OrientationMode.FLAT, candidate_placement.context)
            if flat_rule is None:
                flat_policy_allowed = False
                reasons.append("Flat orientation forbidden by SKU orientation policy")

        # 3. Support & Unsupported Span check
        # Query supporting lower items from world state
        lower_placements = [
            p for p in world_state.placements
            if abs(p.max_z - candidate_placement.min_z) <= eps
            and not (p.max_x <= candidate_placement.min_x + eps or p.min_x >= candidate_placement.max_x - eps)
            and not (p.max_y <= candidate_placement.min_y + eps or p.min_y >= candidate_placement.max_y - eps)
        ]

        # Is placement directly on floor?
        is_on_floor = candidate_placement.min_z <= eps
        if is_on_floor:
            support_ratio = 1.0
            unsupported_span = 0.0
            support_ratio_passed = True
            unsupported_span_passed = True
            allow_top_stack_passed = True
            compression_passed = True
        else:
            base_area = candidate_placement.orientation.dx * candidate_placement.orientation.dy
            supported_area = 0.0
            max_span_x = 0.0
            max_span_y = 0.0

            allow_top_stack_passed = True
            for lp in lower_placements:
                # Overlap on XY plane
                ox = max(0.0, min(candidate_placement.max_x, lp.max_x) - max(candidate_placement.min_x, lp.min_x))
                oy = max(0.0, min(candidate_placement.max_y, lp.max_y) - max(candidate_placement.min_y, lp.min_y))
                supported_area += (ox * oy)

                # Check if lower SKU allows top stacking
                if catalog and lp.sku_id in catalog:
                    lower_sku = catalog[lp.sku_id]
                    if not lower_sku.stacking_policy.allow_stacking_on_top:
                        allow_top_stack_passed = False
                        reasons.append(f"Lower cargo {lp.placement_id} ({lp.sku_id}) forbids stacking on top")

            support_ratio = min(1.0, supported_area / base_area) if base_area > 0 else 0.0
            required_support = stack_policy.min_support_ratio
            active_rule = policy.rule_for(
                OrientationMode.FLAT if is_flat else OrientationMode.UPRIGHT,
                candidate_placement.context,
            )
            if active_rule and active_rule.min_support_ratio is not None:
                required_support = max(required_support, active_rule.min_support_ratio)
            support_ratio_passed = support_ratio >= (required_support - eps)
            if not support_ratio_passed:
                reasons.append(
                    f"Support ratio {support_ratio:.2%} < required {required_support:.2%}"
                )

            # Compute unsupported overhang spans along X and Y
            if lower_placements:
                min_supp_x = min(lp.min_x for lp in lower_placements)
                max_supp_x = max(lp.max_x for lp in lower_placements)
                min_supp_y = min(lp.min_y for lp in lower_placements)
                max_supp_y = max(lp.max_y for lp in lower_placements)

                overhang_x_left = max(0.0, min_supp_x - candidate_placement.min_x)
                overhang_x_right = max(0.0, candidate_placement.max_x - max_supp_x)
                overhang_y_left = max(0.0, min_supp_y - candidate_placement.min_y)
                overhang_y_right = max(0.0, candidate_placement.max_y - max_supp_y)

                internal_gaps: List[float] = []
                for ordered, low_attr, high_attr in (
                    (sorted(lower_placements, key=lambda p: p.min_x), "min_x", "max_x"),
                    (sorted(lower_placements, key=lambda p: p.min_y), "min_y", "max_y"),
                ):
                    for left_item, right_item in zip(ordered, ordered[1:]):
                        internal_gaps.append(max(0.0, getattr(right_item, low_attr) - getattr(left_item, high_attr)))
                unsupported_span = max(
                    [overhang_x_left, overhang_x_right, overhang_y_left, overhang_y_right] + internal_gaps
                )
            else:
                unsupported_span = max(candidate_placement.orientation.dx, candidate_placement.orientation.dy)

            unsupported_span_passed = unsupported_span <= (stack_policy.max_unsupported_span_m + eps)
            if not unsupported_span_passed:
                reasons.append(
                    f"Unsupported span {unsupported_span:.3f}m > allowed {stack_policy.max_unsupported_span_m:.3f}m"
                )

            # 4. Compression check on lower cargo
            compression_passed = True
            if catalog:
                # Simulate load propagation if placed
                sim_sg = SupportGraph(self.container, geom_epsilon=eps)
                for p in world_state.placements:
                    sim_sg.add_placement(p)
                sim_sg.add_placement(candidate_placement)

                load_rep = self.load_engine.compute_loads(sim_sg, catalog)
                if not load_rep.is_valid:
                    compression_passed = False
                    for pid, irep in load_rep.item_reports.items():
                        if irep.is_bearing_exceeded:
                            reasons.append(f"Bearing limit exceeded on supporting item {pid} ({irep.accumulated_upper_load_kg:.1f}kg > {irep.max_bearing_kg:.1f}kg)")
                        if irep.is_no_stack_violated:
                            reasons.append(f"No-stacking violated on supporting item {pid}")

        # 5. Flat layer count check
        flat_layer_limit_passed = True
        flat_layer_count = 1 if is_flat else 0
        if is_flat and not is_on_floor:
            # Count how many consecutive flat layers lie directly beneath this placement
            curr_lower = lower_placements
            while curr_lower:
                flat_under = [p for p in curr_lower if p.orientation.is_flat]
                if not flat_under:
                    break
                flat_layer_count += 1
                next_lower_z = min(p.min_z for p in flat_under)
                curr_lower = [
                    p for p in world_state.placements
                    if abs(p.max_z - next_lower_z) <= eps
                ]

            flat_rule = policy.rule_for(OrientationMode.FLAT, candidate_placement.context)
            max_flat_layers = (
                flat_rule.max_top_fill_layers
                if flat_rule and flat_rule.max_top_fill_layers is not None
                else policy.max_flat_stack_layers
            )
            if flat_layer_count > max_flat_layers:
                flat_layer_limit_passed = False
                reasons.append(
                    f"Flat stack layer count {flat_layer_count} > max allowed {max_flat_layers}"
                )

        # 6. Overall Validity
        is_valid = (
            flat_policy_allowed
            and support_ratio_passed
            and unsupported_span_passed
            and allow_top_stack_passed
            and compression_passed
            and flat_layer_limit_passed
        )

        # Penalty calculation
        penalty = 0.0
        if is_flat:
            penalty += policy.flat_orientation_penalty
        if not is_valid:
            penalty += 10000.0

        return ConditionalFlatCheckResult(
            is_valid=is_valid,
            is_upright_preferred=is_upright_preferred,
            upright_fits=upright_fits,
            flat_policy_allowed=flat_policy_allowed,
            support_ratio=round(support_ratio, 4),
            support_ratio_passed=support_ratio_passed,
            unsupported_span_m=round(unsupported_span, 4),
            unsupported_span_passed=unsupported_span_passed,
            lower_compression_passed=compression_passed,
            flat_layer_count=flat_layer_count,
            flat_layer_limit_passed=flat_layer_limit_passed,
            allow_stacking_on_top_passed=allow_top_stack_passed,
            penalty_score=penalty,
            rejection_reasons=tuple(reasons),
        )

    def calculate_layer_capacity(self, sku: CargoSKU, orientation: Orientation3D, region: TopFillRegion) -> int:
        """Finite proof-based height/stack/compression/stability layer capacity."""
        if orientation.dz <= self.geom_epsilon:
            return 0
        geometry_layers = max(0, int((region.available_height + self.geom_epsilon) // orientation.dz))
        layers = geometry_layers
        mode = OrientationMode.FLAT if orientation.is_flat else (
            OrientationMode.SIDE if orientation.is_side else OrientationMode.UPRIGHT
        )
        rule = sku.orientation_policy.rule_for(mode, PlacementContext.TOP_FILL)
        if rule and rule.max_top_fill_layers is not None:
            layers = min(layers, rule.max_top_fill_layers)
        if sku.stacking_policy.max_stack_layers is not None:
            layers = min(layers, sku.stacking_policy.max_stack_layers)
        if sku.weight_kg > self.geom_epsilon:
            compression_layers = max(0, int((region.max_load + self.geom_epsilon) // sku.weight_kg))
            layers = min(layers, compression_layers)
        required_support = sku.stacking_policy.min_support_ratio
        if sku.cargo_profile is not None:
            top_policy = sku.cargo_profile.top_fill_policy
            required_support = max(required_support, top_policy.min_support_ratio)
            if top_policy.admission_state != TopFillAdmissionState.AUTO and top_policy.max_layers > 0:
                layers = min(layers, top_policy.max_layers)
        stability_layers = geometry_layers if (
            region.support_coverage + self.geom_epsilon >= required_support
            and region.local_flatness >= 0.95
        ) else 0
        layers = min(layers, stability_layers)
        return layers

    def generate_region_candidates(
        self,
        world_state: WorldState,
        active_skus: List[CargoSKU],
        max_candidates: int = 100,
        cargo_catalog: Optional[Dict[str, CargoSKU]] = None,
        qty_mgr: Optional[QuantityManager] = None,
    ) -> List[CandidatePlacement]:
        """Generate region-bound candidates in the required region/SKU/orientation order."""
        catalog = cargo_catalog or world_state._cargo_catalog
        regions = self.extract_top_fill_regions(world_state, catalog, qty_mgr=qty_mgr)
        candidates: List[CandidatePlacement] = []
        for region in regions:
            for sku in active_skus:
                if len(candidates) >= max_candidates:
                    return candidates
                if sku.sku_id not in region.eligible or sku.weight_kg > region.max_load + self.geom_epsilon:
                    continue
                ori_candidates = self.orientation_engine.get_candidate_orientations(
                    sku=sku,
                    context=PlacementContext.TOP_FILL,
                    target_space=region.aabb,
                    min_support_ratio=region.support_coverage,
                    base_height=region.base_z,
                )
                upright_fits = any(c.orientation.is_upright for c in ori_candidates)
                for ori_cand in ori_candidates:
                    ori = ori_cand.orientation
                    rule = sku.orientation_policy.rule_for(
                        OrientationMode.FLAT if ori.is_flat else (OrientationMode.SIDE if ori.is_side else OrientationMode.UPRIGHT),
                        PlacementContext.TOP_FILL,
                    )
                    if ori.is_flat and rule and rule.condition == "UPRIGHT_DOES_NOT_FIT" and upright_fits:
                        continue
                    capacity = self.calculate_layer_capacity(sku, ori, region)
                    if capacity <= 0:
                        continue
                    nx = int((region.x_range[1] - region.x_range[0] + self.geom_epsilon) // ori.dx)
                    ny = int((region.y_range[1] - region.y_range[0] + self.geom_epsilon) // ori.dy)
                    for ix in range(max(0, nx)):
                        for iy in range(max(0, ny)):
                            position = Point3D(
                                region.x_range[0] + ix * ori.dx,
                                region.y_range[0] + iy * ori.dy,
                                region.base_z,
                            )
                            cand = CandidatePlacement(
                                sku_id=sku.sku_id,
                                position=position,
                                orientation=ori,
                                context=PlacementContext.TOP_FILL,
                                weight_kg=sku.weight_kg,
                                orientation_penalty=ori_cand.penalty_score,
                                anchor_category=AnchorCategory.TOP_SURFACE,
                                action_type="TOP_FILL",
                                topfill_region_id=region.region_id,
                                topfill_layer_capacity=capacity,
                            )
                            check = self.evaluate_conditional_flat_placement(
                                sku, cand.to_placement("topfill_probe", "topfill_probe"),
                                world_state, target_space=region.aabb, catalog=None,
                            )
                            if not check.is_valid:
                                continue
                            cand.score_breakdown = self.score_topfill_candidate(cand, sku, region)
                            cand.score = sum(cand.score_breakdown.values())
                            candidates.append(cand)
                            if len(candidates) >= max_candidates:
                                return candidates
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    def score_topfill_candidate(
        self, candidate: CandidatePlacement, sku: CargoSKU, region: TopFillRegion,
    ) -> Dict[str, float]:
        volume = candidate.orientation.volume
        residual_height = max(0.0, region.available_height - candidate.orientation.dz)
        residual_layers = residual_height / max(candidate.orientation.dz, self.geom_epsilon)
        x_end = candidate.position.x + candidate.orientation.dx
        y_end = candidate.position.y + candidate.orientation.dy
        row_complete = 1.0 if abs(y_end - region.y_range[1]) <= self.geom_epsilon else 0.0
        layer_complete = 1.0 if abs(x_end - region.x_range[1]) <= self.geom_epsilon and row_complete else 0.0
        region_dx = region.x_range[1] - region.x_range[0]
        region_dy = region.y_range[1] - region.y_range[0]
        residual_x = region_dx % candidate.orientation.dx if candidate.orientation.dx > self.geom_epsilon else region_dx
        residual_y = region_dy % candidate.orientation.dy if candidate.orientation.dy > self.geom_epsilon else region_dy
        small_height_fragment = residual_height if 0.0 < residual_height < 0.12 else 0.0
        # Penalize residual strips by their actual projected area. This keeps the
        # TopSurface grid from turning a nearly complete row into 5-10cm slivers.
        planar_fragment_area = residual_x * region_dy + residual_y * max(0.0, region_dx - residual_x)
        max_residual_strip = max(residual_x, residual_y)
        target = sku.cargo_profile.top_fill_policy.residual_height_target if sku.cargo_profile is not None else None
        residual_penalty = abs(residual_height - target) if target is not None else residual_layers
        return {
            "top_fill_volume_gain": volume * 1000.0,
            "residual_height_penalty": -residual_penalty * 5.0,
            "top_row_completion": row_complete * 20.0,
            "top_layer_completion": layer_complete * 30.0,
            "support_quality": region.support_coverage * 25.0,
            "surface_compatibility": region.local_flatness * 20.0,
            "fragmentation_penalty": -(
                small_height_fragment * 100.0
                + planar_fragment_area * 100.0
                + max_residual_strip * 100.0
            ),
        }

    def evaluate_topfill_candidate(
        self,
        candidate: CandidatePlacement,
        sku: CargoSKU,
        region: TopFillRegion,
        world_state: WorldState,
        cargo_catalog: Dict[str, CargoSKU],
        zone_mgr: Optional[AdaptiveZoneManager] = None,
        res_mgr: Optional[SpatialReservationManager] = None,
        defer_plan_level_validation: bool = False,
    ) -> TopFillCandidateEvaluation:
        """Run the existing hard, SupportGraph/load, item, cluster and wall validators."""
        reasons: List[str] = []
        if candidate.context != PlacementContext.TOP_FILL or candidate.topfill_region_id != region.region_id:
            reasons.append("Orientation context is not bound to the target TopFillRegion")
        mode = OrientationMode.FLAT if candidate.orientation.is_flat else (
            OrientationMode.SIDE if candidate.orientation.is_side else OrientationMode.UPRIGHT
        )
        rule = sku.orientation_policy.rule_for(mode, PlacementContext.TOP_FILL)
        orientation_passed = rule is not None and candidate.context == PlacementContext.TOP_FILL
        if not orientation_passed:
            reasons.append("Orientation is forbidden in TOP_FILL context")

        placement = candidate.to_placement(
            placement_id=f"blk004_probe_{len(world_state.placements)}",
            instance_id="blk004_probe",
        )
        conditional = self.evaluate_conditional_flat_placement(
            sku, placement, world_state, target_space=region.aabb, catalog=cargo_catalog,
        )
        reasons.extend(conditional.rejection_reasons)
        hard_ok, hard_reason = self.hard_validator.is_feasible(
            candidate, sku, world_state, zone_mgr or AdaptiveZoneManager(self.container),
            res_mgr=res_mgr,
            context=PlacementContext.TOP_FILL,
        )
        if not hard_ok and hard_reason:
            reasons.append(hard_reason)

        if defer_plan_level_validation:
            # BLK-006E draft plans remain isolated and can never be returned
            # directly. Per-placement hard geometry, declared orientation,
            # support, unsupported span and load/compression checks above stay
            # active; whole-system stability/cavity is evaluated once for the
            # complete repair candidate before monotonic acceptance.
            physics = None
            item_ok = cluster_ok = wall_ok = True
            load_ok = conditional.lower_compression_passed
        else:
            physics = self.physics_engine.evaluate_system(
                self.container, world_state.placements + [placement], cargo_catalog,
            )
            item_report = physics.item_stability_reports.get(placement.placement_id)
            item_ok = bool(item_report and item_report.is_stable)
            cluster_ok = all(cr.is_stable for cr in physics.cluster_stability_reports if placement.placement_id in cr.placement_ids)
            wall_ok = all(wr.is_stable for wr in physics.wall_stability_reports if placement.placement_id in wr.placement_ids)
            load_ok = physics.load_report.is_valid
            if not load_ok:
                reasons.extend(physics.compression_violations)
            if not item_ok:
                reasons.append("Item stability validation failed")
            if not cluster_ok:
                reasons.append("Cluster stability validation failed")
            if not wall_ok:
                reasons.append("Wall stability validation failed")

        # Profile-backed Top Fill is the authoritative BLK-004B path. Legacy
        # CargoSKU inputs retain their accepted BLK-004 behavior and avoid an
        # unbudgeted whole-container voxel pass per candidate.
        cavity_ok = True
        if sku.cargo_profile is not None and not defer_plan_level_validation:
            cavity = AdvancedCavityClassifier(self.container).classify_cavities(
                world_state.placements + [placement]
            )
            cavity_ok = not cavity.enclosed_cavities and cavity.bridge_void_count == 0
            if not cavity_ok:
                reasons.append(
                    f"Top Fill would create enclosed/bridge void "
                    f"({len(cavity.enclosed_cavities)}/{cavity.bridge_void_count})"
                )

        layer_ok = conditional.flat_layer_limit_passed and candidate.topfill_layer_capacity > 0
        valid = (
            orientation_passed and hard_ok and conditional.support_ratio_passed
            and conditional.unsupported_span_passed and load_ok
            and item_ok and cluster_ok and wall_ok and layer_ok and cavity_ok
        )
        return TopFillCandidateEvaluation(
            is_valid=valid,
            hard_validation_passed=hard_ok,
            orientation_context_passed=orientation_passed,
            support_passed=conditional.support_ratio_passed and conditional.unsupported_span_passed,
            compression_passed=load_ok,
            item_stability_passed=item_ok,
            cluster_stability_passed=cluster_ok,
            wall_stability_passed=wall_ok,
            layer_limit_passed=layer_ok,
            cavity_passed=cavity_ok,
            rejection_reasons=tuple(dict.fromkeys(reasons)),
        )

    def build_region_candidate_pool(
        self,
        world_state: WorldState,
        region: TopFillRegion,
        qty_mgr: QuantityManager,
        cargo_catalog: Dict[str, CargoSKU],
        zone_mgr: Optional[AdaptiveZoneManager] = None,
    ) -> List[RegionLocalCandidate]:
        """Retain every safely-admitted orientation; do not collapse to one SKU."""
        pool: List[RegionLocalCandidate] = []
        for sku in cargo_catalog.values():
            remaining = qty_mgr.get_remaining(sku.sku_id, PlacementContext.TOP_FILL)
            diagnostic = self.diagnose_region_admission(
                world_state, region, sku, remaining > 0, zone_mgr,
            )
            if not diagnostic.admitted:
                continue
            profile = sku.cargo_profile
            state = profile.top_fill_policy.admission_state if profile is not None else TopFillAdmissionState.DENY
            orientations = self.orientation_engine.get_candidate_orientations(
                sku=sku,
                context=PlacementContext.TOP_FILL,
                target_space=region.aabb,
                min_support_ratio=region.support_coverage,
                base_height=region.base_z,
            )
            upright_fits = any(item.orientation.is_upright for item in orientations)
            for oriented in orientations:
                orientation = oriented.orientation
                # AUTO proves safety, but never manufactures a dangerous orientation.
                if state == TopFillAdmissionState.AUTO and not orientation.is_upright:
                    continue
                mode = OrientationMode.FLAT if orientation.is_flat else (
                    OrientationMode.SIDE if orientation.is_side else OrientationMode.UPRIGHT
                )
                rule = sku.orientation_policy.rule_for(mode, PlacementContext.TOP_FILL)
                if rule is None:
                    continue
                if orientation.is_flat and rule.condition == "UPRIGHT_DOES_NOT_FIT" and upright_fits:
                    continue
                layers = self.calculate_layer_capacity(sku, orientation, region)
                if layers <= 0:
                    continue
                support = sku.stacking_policy.min_support_ratio
                if profile is not None:
                    support = max(support, profile.top_fill_policy.min_support_ratio)
                pool.append(RegionLocalCandidate(
                    sku_id=sku.sku_id,
                    orientation=orientation,
                    remaining_quantity=remaining,
                    effective_max_layers=layers,
                    support_requirement=support,
                    compression_limit=region.max_load,
                    stability_constraints={
                        "anti_tip_required": bool(profile and profile.stability_policy.anti_tip_required),
                        "max_unsupported_span": sku.stacking_policy.max_unsupported_span_m,
                        "group_stability_required": bool(profile and profile.stability_policy.group_stability_required),
                        "wall_stability_required": bool(profile and profile.stability_policy.wall_stability_required),
                    },
                    source="AUTO" if state == TopFillAdmissionState.AUTO else "USER_DEFINED",
                ))
        return pool

    def _split_residual(
        self,
        rect: ResidualRectangle,
        orientation: Orientation3D,
        anchor: str,
        sequence: int,
        max_layers: int,
    ) -> List[ResidualRectangle]:
        """Guillotine split into disjoint right/front-or-back and supported layer residuals."""
        eps = self.geom_epsilon
        dx, dy = orientation.dx, orientation.dy
        prefix = f"{rect.rectangle_id}_{sequence}"
        pieces: List[ResidualRectangle] = []
        if anchor == "FRONT":
            px0, py0 = rect.x0, rect.y0
            pieces.extend([
                ResidualRectangle(f"{prefix}_RIGHT", px0 + dx, rect.x1, rect.y0, rect.y1, rect.base_z, rect.layer),
                ResidualRectangle(f"{prefix}_BACK", px0, px0 + dx, py0 + dy, rect.y1, rect.base_z, rect.layer),
            ])
        else:
            px0, py0 = rect.x0, rect.y1 - dy
            pieces.extend([
                ResidualRectangle(f"{prefix}_RIGHT", px0 + dx, rect.x1, rect.y0, rect.y1, rect.base_z, rect.layer),
                ResidualRectangle(f"{prefix}_FRONT", px0, px0 + dx, rect.y0, py0, rect.base_z, rect.layer),
            ])
        if rect.layer < max_layers:
            pieces.append(ResidualRectangle(
                f"{prefix}_LAYER", px0, px0 + dx, py0, py0 + dy,
                rect.base_z + orientation.dz, rect.layer + 1,
            ))
        return [p for p in pieces if p.area > eps * eps and p.base_z < self.container.Lz - eps]

    def _normalize_residuals(self, rectangles: List[ResidualRectangle]) -> List[ResidualRectangle]:
        """Remove containment and merge only exact, coplanar rectangular unions."""
        eps = self.geom_epsilon
        kept: List[ResidualRectangle] = []
        for rect in sorted(rectangles, key=lambda r: (r.base_z, r.layer, -r.area)):
            if any(
                abs(rect.base_z - other.base_z) <= eps
                and rect.x0 >= other.x0 - eps and rect.x1 <= other.x1 + eps
                and rect.y0 >= other.y0 - eps and rect.y1 <= other.y1 + eps
                for other in kept
            ):
                continue
            kept.append(rect)
        changed = True
        while changed:
            changed = False
            for i, left in enumerate(kept):
                for j in range(i + 1, len(kept)):
                    right = kept[j]
                    if abs(left.base_z - right.base_z) > eps or left.layer != right.layer:
                        continue
                    merged = None
                    if abs(left.y0 - right.y0) <= eps and abs(left.y1 - right.y1) <= eps:
                        if abs(left.x1 - right.x0) <= eps or abs(right.x1 - left.x0) <= eps:
                            merged = ResidualRectangle(
                                f"{left.rectangle_id}+{right.rectangle_id}", min(left.x0, right.x0), max(left.x1, right.x1),
                                left.y0, left.y1, left.base_z, left.layer,
                            )
                    elif abs(left.x0 - right.x0) <= eps and abs(left.x1 - right.x1) <= eps:
                        if abs(left.y1 - right.y0) <= eps or abs(right.y1 - left.y0) <= eps:
                            merged = ResidualRectangle(
                                f"{left.rectangle_id}+{right.rectangle_id}", left.x0, left.x1,
                                min(left.y0, right.y0), max(left.y1, right.y1), left.base_z, left.layer,
                            )
                    if merged is not None:
                        kept = [r for k, r in enumerate(kept) if k not in (i, j)] + [merged]
                        changed = True
                        break
                if changed:
                    break
        return kept

    def _local_options(
        self,
        region: TopFillRegion,
        pool: List[RegionLocalCandidate],
        residuals: List[ResidualRectangle],
        qty_mgr: QuantityManager,
        strategy: str = "LEGACY_BALANCED",
        lookahead_depth: int = 2,
    ) -> List[Tuple[float, RegionLocalCandidate, int, str, CandidatePlacement]]:
        """Generate and rank all pool×residual anchors with depth-two geometric continuation."""
        eps = self.geom_epsilon
        raw: List[Tuple[float, RegionLocalCandidate, int, str, CandidatePlacement]] = []
        for rect_index, rect in enumerate(residuals):
            for entry in pool:
                if qty_mgr.get_remaining(entry.sku_id, PlacementContext.TOP_FILL) <= 0:
                    continue
                ori = entry.orientation
                if rect.layer > entry.effective_max_layers or ori.dx > rect.x1 - rect.x0 + eps or ori.dy > rect.y1 - rect.y0 + eps:
                    continue
                if rect.base_z + ori.dz > self.container.Lz + eps:
                    continue
                for anchor in ("FRONT", "BACK"):
                    y = rect.y0 if anchor == "FRONT" else rect.y1 - ori.dy
                    candidate = CandidatePlacement(
                        sku_id=entry.sku_id,
                        position=Point3D(rect.x0, y, rect.base_z),
                        orientation=ori,
                        context=PlacementContext.TOP_FILL,
                        weight_kg=0.0,
                        anchor_category=AnchorCategory.TOP_SURFACE,
                        action_type="TOP_FILL_REGION_PACK",
                        topfill_region_id=region.region_id,
                        topfill_layer_capacity=entry.effective_max_layers,
                    )
                    rect_area = max(rect.area, eps)
                    fill_ratio = ori.dx * ori.dy / rect_area
                    split = self._split_residual(rect, ori, anchor, 0, entry.effective_max_layers)
                    fragments = [p.area for p in split if p.layer == rect.layer]
                    fragmentation = (len(fragments) - 1) + (min(fragments) / rect_area if fragments else 0.0)
                    remaining = qty_mgr.get_remaining(entry.sku_id, PlacementContext.TOP_FILL)
                    footprint = ori.dx * ori.dy
                    residual_area = sum(piece.area for piece in split if piece.layer == rect.layer)
                    rectangularity = max(fragments, default=0.0) / max(residual_area, eps)
                    layer_completion = max(0.0, 1.0 - residual_area / rect_area)
                    base_score = (
                        fill_ratio * 100.0 + ori.volume * 1000.0
                        + min(remaining, 4) * 1.5 + rect.layer * 2.0
                        + region.support_coverage * 10.0 + region.local_flatness * 10.0
                        - fragmentation * 12.0
                    )
                    strategy_bonus = {
                        "VOLUME_FIRST": ori.volume * 2500.0,
                        "HEIGHT_FIRST": (ori.dz / max(region.available_height, eps)) * 120.0,
                        "FOOTPRINT_FIRST": fill_ratio * 140.0,
                        "RESIDUAL_MATCH": rectangularity * 100.0 - fragmentation * 20.0,
                        "LAYER_COMPLETION": layer_completion * 160.0,
                        "MIXED_SKU": min(remaining, 8) * 4.0 + footprint * 15.0,
                        "ORIENTATION_DIVERSITY": (25.0 if ori.name.endswith("ROTATED") else 10.0),
                        "REGION_FIRST": region.usable_volume * 4.0 + fill_ratio * 80.0,
                    }.get(strategy, 0.0)
                    immediate = base_score + strategy_bonus
                    raw.append((immediate, entry, rect_index, anchor, candidate))
        # Depth-two bounded lookahead: estimate the best continuation after each seed.
        ranked: List[Tuple[float, RegionLocalCandidate, int, str, CandidatePlacement]] = []
        for immediate, entry, rect_index, anchor, candidate in raw:
            next_rects = residuals[:rect_index] + residuals[rect_index + 1:]
            next_rects += self._split_residual(
                residuals[rect_index], entry.orientation, anchor, 1, entry.effective_max_layers,
            )
            continuation = 0.0
            if lookahead_depth <= 1:
                ranked.append((immediate, entry, rect_index, anchor, candidate))
                continue
            for other in pool:
                ori = other.orientation
                if qty_mgr.get_remaining(other.sku_id, PlacementContext.TOP_FILL) <= 0:
                    continue
                for next_rect in next_rects:
                    if next_rect.layer <= other.effective_max_layers and ori.dx <= next_rect.x1 - next_rect.x0 + eps and ori.dy <= next_rect.y1 - next_rect.y0 + eps and next_rect.base_z + ori.dz <= self.container.Lz + eps:
                        continuation = max(continuation, ori.volume * 700.0 + ori.dx * ori.dy / max(next_rect.area, eps) * 60.0)
            ranked.append((immediate + continuation, entry, rect_index, anchor, candidate))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked

    @staticmethod
    def _failure_stage(evaluation: TopFillCandidateEvaluation) -> str:
        reasons = " ".join(evaluation.rejection_reasons).lower()
        if "collision" in reasons or "overlap" in reasons:
            return "COLLISION"
        if not evaluation.support_passed or "support" in reasons or "bridge" in reasons:
            return "SUPPORT"
        if not evaluation.layer_limit_passed:
            return "LAYER_LIMIT"
        if not evaluation.item_stability_passed or not evaluation.cluster_stability_passed or not evaluation.wall_stability_passed:
            return "STABILITY"
        return "ATTEMPT_FAILED"

    def deploy_conditional_top_fill(
        self,
        world_state: WorldState,
        qty_mgr: QuantityManager,
        cargo_catalog: Dict[str, CargoSKU],
        zone_mgr: AdaptiveZoneManager,
        res_mgr: Optional[SpatialReservationManager] = None,
        max_placements: int = 12,
        strategy: str = "LEGACY_BALANCED",
        lookahead_depth: int = 2,
        defer_plan_level_validation: bool = False,
    ) -> TopFillDeploymentResult:
        """Bounded region-local packing; never releases or modifies door reservations."""
        result = TopFillDeploymentResult()
        regions = self.extract_top_fill_regions(world_state, cargo_catalog, qty_mgr=qty_mgr)
        if strategy in ("REGION_FIRST", "VOLUME_FIRST", "FOOTPRINT_FIRST"):
            regions = sorted(regions, key=lambda item: (-item.usable_volume, item.region_id))
        elif strategy == "HEIGHT_FIRST":
            regions = sorted(regions, key=lambda item: (-item.available_height, -item.usable_volume, item.region_id))
        else:
            regions = sorted(regions, key=lambda item: item.region_id)
        # The legacy number is now a per-pass seed budget. Region packing may use
        # up to three continuations per seed, but stays bounded and local.
        total_budget = max_placements * 3
        per_region_budget = max(2, max_placements // 3)
        for region in regions:
            pool = self.build_region_candidate_pool(world_state, region, qty_mgr, cargo_catalog, zone_mgr)
            budget_exhausted = len(result.placed) >= total_budget
            funnel = Counter({stage: 0 for stage in (
                "NOT_GENERATED", "PRUNED", "RANKED_OUT", "ATTEMPT_FAILED", "COLLISION",
                "SUPPORT", "STABILITY", "LAYER_LIMIT", "INVENTORY", "REGION_EXHAUSTED", "COMMITTED",
            )})
            funnel["admitted_candidate_count"] = len(pool)
            generated_keys: Set[Tuple[str, str]] = set()
            attempted_keys: Set[Tuple[str, str]] = set()
            residuals = [ResidualRectangle(
                f"{region.region_id}_BASE", region.x_range[0], region.x_range[1],
                region.y_range[0], region.y_range[1], region.base_z, 1,
            )]
            committed: List[Placement] = []
            rejection_reasons: Counter = Counter()
            attempts = 0
            while len(committed) < per_region_budget and len(result.placed) < total_budget:
                options = self._local_options(
                    region, pool, residuals, qty_mgr,
                    strategy=strategy, lookahead_depth=lookahead_depth,
                )
                funnel["generated_candidate_count"] += len(options)
                funnel["ranked_candidate_count"] += len(options)
                for _, entry, _, _, _ in options:
                    generated_keys.add((entry.sku_id, entry.orientation.name))
                if not options:
                    funnel["REGION_EXHAUSTED"] += 1
                    break
                # Full physical validation is intentionally bounded to the best
                # region-local continuations; all others remain visible as ranked-out.
                attempt_window = min(12, len(options))
                funnel["RANKED_OUT"] += max(0, len(options) - attempt_window)
                placed_this_round = False
                for _, entry, rect_index, anchor, candidate in options[:attempt_window]:
                    if not qty_mgr.can_place(entry.sku_id, PlacementContext.TOP_FILL):
                        funnel["INVENTORY"] += 1
                        continue
                    sku = cargo_catalog[entry.sku_id]
                    candidate.weight_kg = sku.weight_kg
                    funnel["attempted_candidate_count"] += 1
                    attempted_keys.add((entry.sku_id, entry.orientation.name))
                    attempts += 1
                    evaluation = self.evaluate_topfill_candidate(
                        candidate, sku, region, world_state, cargo_catalog, zone_mgr, res_mgr,
                        defer_plan_level_validation=defer_plan_level_validation,
                    )
                    if not evaluation.is_valid:
                        stage = self._failure_stage(evaluation)
                        funnel[stage] += 1
                        for reason in evaluation.rejection_reasons:
                            rejection_reasons[reason] += 1
                        if stage == "SUPPORT":
                            result.rejected_insufficient_support += 1
                        elif not evaluation.compression_passed:
                            result.rejected_compression += 1
                        elif not evaluation.orientation_context_passed:
                            result.rejected_orientation_context += 1
                        elif stage == "LAYER_LIMIT":
                            result.rejected_max_layers += 1
                        else:
                            result.rejected_stability += 1
                        continue
                    placement = candidate.to_placement(
                        placement_id=f"topfill_{len(world_state.placements):04d}_{sku.sku_id}",
                        instance_id=f"inst_topfill_{len(world_state.placements):04d}",
                        step_index=len(world_state.placements),
                    )
                    world_state.commit(placement)
                    qty_mgr.record_placement(sku.sku_id, context=PlacementContext.TOP_FILL)
                    result.placed.append(placement)
                    committed.append(placement)
                    funnel["COMMITTED"] += 1
                    chosen_rect = residuals[rect_index]
                    residuals = residuals[:rect_index] + residuals[rect_index + 1:] + self._split_residual(
                        chosen_rect, entry.orientation, anchor, len(committed), entry.effective_max_layers,
                    )
                    residuals = self._normalize_residuals(residuals)
                    placed_this_round = True
                    break
                if not placed_this_round:
                    funnel["REGION_EXHAUSTED"] += 1
                    break
            admitted_keys = {(item.sku_id, item.orientation.name) for item in pool}
            funnel["NOT_GENERATED"] = len(admitted_keys - generated_keys)
            funnel["PRUNED"] = len(admitted_keys) if budget_exhausted else len(generated_keys - attempted_keys)
            funnel["committed_candidate_count"] = len(committed)
            placed_volume = sum(p.volume for p in committed)
            result.region_funnels[region.region_id] = dict(funnel)
            result.region_plans[region.region_id] = {
                "region_id": region.region_id,
                "logical_wall_id": region.logical_wall_id,
                "usable_volume": region.usable_volume,
                "admitted_candidates": [item.to_dict() for item in pool],
                "generated_candidates": funnel["generated_candidate_count"],
                "attempted_candidates": funnel["attempted_candidate_count"],
                "committed_placements": [
                    {
                        "placement_id": p.placement_id, "sku": p.sku_id,
                        "orientation": p.orientation.name, "layer": 1 + int(round((p.position.z - region.base_z) / max(p.orientation.dz, self.geom_epsilon))),
                        "position": [p.position.x, p.position.y, p.position.z], "volume": p.volume,
                    }
                    for p in committed
                ],
                "placed_volume": placed_volume,
                "utilization": placed_volume / region.usable_volume if region.usable_volume > self.geom_epsilon else 0.0,
                "layer_count": len({round(p.position.z, 6) for p in committed}),
                "sku_mix": dict(Counter(p.sku_id for p in committed)),
                "orientation_mix": dict(Counter(p.orientation.name for p in committed)),
                "residual_rectangles": [rect.to_dict() for rect in residuals],
                "rejection_reasons": dict(rejection_reasons),
                "funnel": dict(funnel),
                "attempt_count": attempts,
                "strategy": strategy,
                "lookahead_depth": lookahead_depth,
                "plan_level_validation_deferred": defer_plan_level_validation,
            }
        return result

    def generate_topfill_block(
        self,
        sku: CargoSKU,
        target_headspace: TopFillSpace,
        world_state: WorldState,
        max_quantity: Optional[int] = None,
        catalog: Optional[Dict[str, CargoSKU]] = None,
    ) -> Optional[PackedBlock]:
        """
        Generates an aggregated TopFillBlock fitting the given TopFillSpace.
        Prefers upright if upright fits; otherwise conditionally selects flat if permitted.
        """
        avail_qty = sku.quantity.required if max_quantity is None else min(sku.quantity.required, max_quantity)
        if avail_qty <= 0:
            return None

        space_aabb = target_headspace.space_aabb
        dx_sku, dy_sku, dz_sku = sku.box.x, sku.box.y, sku.box.z

        # Check if upright fits
        upright_rule = sku.orientation_policy.rule_for(OrientationMode.UPRIGHT, PlacementContext.TOP_FILL)
        flat_rule = sku.orientation_policy.rule_for(OrientationMode.FLAT, PlacementContext.TOP_FILL)
        if space_aabb.dz >= dz_sku - self.geom_epsilon and upright_rule:
            ori = Orientation3D(dx=dx_sku, dy=dy_sku, dz=dz_sku, name="UPRIGHT_NORMAL", is_upright=True)
        elif flat_rule:
            ori = Orientation3D(dx=dx_sku, dy=dz_sku, dz=dy_sku, name="FLAT_XZ", is_flat=True, is_upright=False)
        else:
            return None

        # Determine grid nx, ny, nz
        nx = max(1, int((space_aabb.dx + self.geom_epsilon) // ori.dx))
        ny = max(1, int((space_aabb.dy + self.geom_epsilon) // ori.dy))
        nz = max(1, int((space_aabb.dz + self.geom_epsilon) // ori.dz))

        if ori.is_flat:
            max_layers = flat_rule.max_top_fill_layers if flat_rule and flat_rule.max_top_fill_layers is not None else sku.orientation_policy.max_flat_stack_layers
            nz = min(nz, max_layers)

        # Scale down if exceeds available quantity
        while nx * ny * nz > avail_qty and (nx > 1 or ny > 1 or nz > 1):
            if nx >= ny and nx > 1:
                nx -= 1
            elif ny > 1:
                ny -= 1
            elif nz > 1:
                nz -= 1

        if nx * ny * nz > avail_qty or nx * ny * nz < 1:
            return None

        offsets: List[ItemOffset] = []
        for ix in range(nx):
            for iy in range(ny):
                for iz in range(nz):
                    offsets.append(
                        ItemOffset(
                            sku_id=sku.sku_id,
                            relative_position=Point3D(
                                x=round(ix * ori.dx, 6),
                                y=round(iy * ori.dy, 6),
                                z=round(iz * ori.dz, 6),
                            ),
                            orientation=ori,
                            weight_kg=sku.weight_kg,
                        )
                    )

        bx = round(nx * ori.dx, 6)
        by = round(ny * ori.dy, 6)
        bz = round(nz * ori.dz, 6)
        pid = f"TOPFILL_{sku.sku_id}_{nx}x{ny}x{nz}_{ori.name}"

        return PackedBlock(
            pattern_id=pid,
            pattern_type=PatternType.LAYER if nz == 1 else PatternType.BLOCK,
            sku_id=sku.sku_id,
            bounding_box=BoxDim(x=bx, y=by, z=bz),
            total_cartons=nx * ny * nz,
            total_weight_kg=nx * ny * nz * sku.weight_kg,
            item_offsets=tuple(offsets),
            nx=nx,
            ny=ny,
            nz=nz,
            unit_orientation=ori,
            volume_efficiency=1.0,
        )
