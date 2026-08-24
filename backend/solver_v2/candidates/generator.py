"""
Candidate Generator for Solver V2 (Agent 05 / P0 BLK-001 Phase 2).
Generates concrete CandidatePlacement items by combining:
- Geometric anchors classified by category (FLOOR_FRONTIER, SUPPORTED_FRONTIER, WALL_FRONTIER, etc.)
- ActivePackingFrontier & WallSurfaceMap valley fill anchors
- Continuous Floor Frontier Recovery (rebuild_floor_frontier)
- Cheap support pre-filtering (has_possible_support)
- Category-aware candidate budgeting & multi-SKU non-blocking continuation
"""
from dataclasses import dataclass, field
from typing import List, Optional, Set, Dict, Tuple, Any

from backend.solver_v2.domain.models import (
    BoxDim,
    Point3D,
    Orientation3D,
    Placement,
    PlacementContext,
    ZoneType,
    CargoSKU,
)
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.spaces.types import AnchorCategory, ClassifiedAnchor
from backend.solver_v2.world.state import WorldState
from backend.solver_v2.spaces.engine import FreeSpaceEngine
from backend.solver_v2.orientation.manager import OrientationEngine, OrientationCandidate
from backend.solver_v2.zones.manager import AdaptiveZoneManager
from backend.solver_v2.quantity.manager import QuantityManager
from backend.solver_v2.structure.wall_surface import WallSurfaceMap, ActivePackingFrontier, ValleyRegion


@dataclass
class CandidateBudget:
    """Category-aware candidate budget allocation."""
    floor: int = 80
    supported: int = 80
    wall: int = 60
    ems: int = 40
    ep: int = 40
    exploration: int = 40

    @classmethod
    def from_total(cls, total: int = 300) -> "CandidateBudget":
        """Calculates balanced per-category quotas from a total candidate budget."""
        floor = max(40, int(total * 0.30))
        supported = max(40, int(total * 0.30))
        wall = max(20, int(total * 0.15))
        ems = max(15, int(total * 0.10))
        ep = max(15, int(total * 0.10))
        exploration = max(10, total - (floor + supported + wall + ems + ep))
        return cls(floor=floor, supported=supported, wall=wall, ems=ems, ep=ep, exploration=max(10, exploration))


@dataclass
class CandidatePlacement:
    """A generated candidate placement before committing into WorldState."""
    sku_id: str
    position: Point3D
    orientation: Orientation3D
    context: PlacementContext
    weight_kg: float
    orientation_penalty: float = 0.0
    score: float = 0.0
    anchor_category: AnchorCategory = AnchorCategory.EXPLORATION
    action_type: str = "CONTINUE_ROW"
    score_breakdown: Dict[str, float] = field(default_factory=dict)
    topfill_region_id: Optional[str] = None
    topfill_layer_capacity: int = 0

    @property
    def x(self) -> float:
        return self.position.x

    @property
    def y(self) -> float:
        return self.position.y

    @property
    def z(self) -> float:
        return self.position.z

    @property
    def dx(self) -> float:
        return self.orientation.dx

    @property
    def dy(self) -> float:
        return self.orientation.dy

    @property
    def dz(self) -> float:
        return self.orientation.dz

    @property
    def aabb(self) -> AABB:
        return AABB(self.x, self.y, self.z, self.x + self.dx, self.y + self.dy, self.z + self.dz)

    def to_placement(self, placement_id: str, instance_id: str, step_index: int = 0) -> Placement:
        return Placement(
            placement_id=placement_id,
            instance_id=instance_id,
            sku_id=self.sku_id,
            position=self.position,
            orientation=self.orientation,
            weight_kg=self.weight_kg,
            context=self.context,
            step_index=step_index,
        )


class CandidateGenerator:
    """
    Produces candidate placements from classified 3D anchors, active frontier maps, orientation policies, and zone rules.
    Equipped with cheap support pre-filter, category-aware scheduling, and continuous frontier recovery.
    """

    def __init__(self, geom_epsilon: float = DEFAULT_GEOM_EPSILON):
        self.geom_epsilon = geom_epsilon
        self.last_telemetry: Dict[str, Any] = {}

    def has_possible_support(
        self,
        world_state: WorldState,
        pos: Point3D,
        ori: Orientation3D,
    ) -> bool:
        """
        Cheap pre-filter: quickly determines if a candidate has physical supporting contact below.
        - z <= eps: 100% floor support -> True
        - z > eps: checks if there is any box top face directly beneath the candidate footprint
        """
        eps = self.geom_epsilon
        if pos.z <= eps:
            return True

        x, y, z = pos.x, pos.y, pos.z
        dx, dy, dz = ori.dx, ori.dy, ori.dz

        support_aabb = AABB(x, y, z - 0.05, x + dx, y + dy, z + eps)
        touching = world_state.spatial_index.query_intersect(support_aabb, eps=eps)
        if not touching:
            return False

        # Quick check: at least one box whose top is near z and overlaps base
        for item in touching:
            p: Optional[Placement] = item.data
            if p is None:
                continue
            p_top = p.position.z + p.orientation.dz
            if abs(p_top - z) <= eps:
                p_min_x, p_max_x = p.position.x, p.position.x + p.orientation.dx
                p_min_y, p_max_y = p.position.y, p.position.y + p.orientation.dy
                ox = max(0.0, min(x + dx, p_max_x) - max(x, p_min_x))
                oy = max(0.0, min(y + dy, p_max_y) - max(y, p_min_y))
                if ox > eps and oy > eps:
                    return True

        return False

    def generate_candidates(
        self,
        world_state: WorldState,
        space_engine: FreeSpaceEngine,
        orientation_engine: OrientationEngine,
        zone_mgr: AdaptiveZoneManager,
        qty_mgr: QuantityManager,
        active_skus: List[CargoSKU],
        context: PlacementContext = PlacementContext.GENERAL,
        target_zone: Optional[ZoneType] = None,
        max_candidates: int = 500,
        budget: Optional[CandidateBudget] = None,
        is_wall_stalled: bool = False,
    ) -> List[CandidatePlacement]:
        """
        Generates filtered candidate placements across classified anchors with category quotas and frontier recovery.
        """
        candidates: List[CandidatePlacement] = []
        eps = self.geom_epsilon
        container = world_state.container

        # 1. Filter SKUs with remaining quota
        eligible_skus = [s for s in active_skus if qty_mgr.can_place(s.sku_id)]
        if not eligible_skus:
            return []

        # BLK-004: TOP_FILL never consumes generic free-space/frontier anchors.
        # It is activated only through continuous LogicalWall.TopSurface regions.
        if context == PlacementContext.TOP_FILL:
            from backend.solver_v2.topfill.planner import TopFillPlanner
            region_candidates = TopFillPlanner(container).generate_region_candidates(
                world_state=world_state,
                active_skus=eligible_skus,
                max_candidates=max_candidates,
                cargo_catalog=world_state._cargo_catalog,
            )
            self.last_telemetry = {
                "anchors_generated_by_type": {AnchorCategory.TOP_SURFACE.value: len(region_candidates)},
                "anchors_sampled_by_type": {AnchorCategory.TOP_SURFACE.value: len(region_candidates)},
                "candidates_generated_by_anchor_type": {AnchorCategory.TOP_SURFACE.value: len(region_candidates)},
                "floor_frontier_count": 0,
                "supported_frontier_count": 0,
                "wall_frontier_count": 0,
                "topfill_region_bound": True,
            }
            return region_candidates

        # 2. Collect and classify anchors
        classified_anchors = space_engine.get_classified_anchors(world_state=world_state)
        
        # 3. Active Packing Frontier & Continuous Floor Rebuild
        wall_map = WallSurfaceMap(container=container, geom_epsilon=eps)
        max_allowed_x = container.Lx - (zone_mgr.door_zone_length_m if context != PlacementContext.DOOR_SEAL else 0.0)
        frontier = wall_map.extract_active_packing_frontier(world_state.placements, max_allowed_x=max_allowed_x)

        # Supplement floor and valley anchors
        existing_floor_points = {(round(a.x, 3), round(a.y, 3)) for a in classified_anchors.get(AnchorCategory.FLOOR_FRONTIER, [])}
        for fa in frontier.floor_frontier_anchors:
            if (round(fa.x, 3), round(fa.y, 3)) not in existing_floor_points:
                classified_anchors[AnchorCategory.FLOOR_FRONTIER].append(fa)
                existing_floor_points.add((round(fa.x, 3), round(fa.y, 3)))

        # Add valley anchors to GAP_FILL / SUPPORTED_FRONTIER
        for v in frontier.valleys:
            v_pt = v.anchor
            classified_anchors[AnchorCategory.GAP_FILL].append(
                ClassifiedAnchor(
                    point=v_pt,
                    category=AnchorCategory.GAP_FILL,
                    support_z=v.min_z,
                    priority_score=100.0 * v.depth_m,
                )
            )

        # Sort floor frontier: lowest X first (rear to front), then Y
        classified_anchors[AnchorCategory.FLOOR_FRONTIER].sort(key=lambda a: (round(a.x, 4), round(a.y, 4)))

        # Telemetry: record anchor counts
        anchors_generated_by_type = {cat.value: len(anchs) for cat, anchs in classified_anchors.items()}
        anchors_sampled_by_type = {cat.value: 0 for cat in AnchorCategory}
        candidates_generated_by_anchor_type = {cat.value: 0 for cat in AnchorCategory}

        # 4. Resolve category budget
        cat_budget = budget or CandidateBudget.from_total(max_candidates)

        category_budgets: Dict[AnchorCategory, int] = {
            AnchorCategory.FLOOR_FRONTIER: cat_budget.floor,
            AnchorCategory.SUPPORTED_FRONTIER: cat_budget.supported,
            AnchorCategory.WALL_FRONTIER: cat_budget.wall,
            AnchorCategory.EMS_CORNER: cat_budget.ems,
            AnchorCategory.TOP_SURFACE: cat_budget.ep,
            AnchorCategory.EXTREME_POINT: cat_budget.ep,
            AnchorCategory.GAP_FILL: cat_budget.exploration,
            AnchorCategory.EXPLORATION: cat_budget.exploration,
        }

        # Prioritized sequence of category evaluation (if wall stalled, prioritize floor and valley fill)
        if is_wall_stalled:
            cat_sequence = [
                AnchorCategory.FLOOR_FRONTIER,
                AnchorCategory.GAP_FILL,
                AnchorCategory.WALL_FRONTIER,
                AnchorCategory.SUPPORTED_FRONTIER,
                AnchorCategory.EMS_CORNER,
                AnchorCategory.TOP_SURFACE,
                AnchorCategory.EXTREME_POINT,
                AnchorCategory.EXPLORATION,
            ]
        else:
            cat_sequence = [
                AnchorCategory.FLOOR_FRONTIER,
                AnchorCategory.SUPPORTED_FRONTIER,
                AnchorCategory.WALL_FRONTIER,
                AnchorCategory.GAP_FILL,
                AnchorCategory.EMS_CORNER,
                AnchorCategory.TOP_SURFACE,
                AnchorCategory.EXTREME_POINT,
                AnchorCategory.EXPLORATION,
            ]

        seen_keys: Set[Tuple[str, float, float, float, float, float, float]] = set()

        for cat in cat_sequence:
            cat_anchors = classified_anchors.get(cat, [])
            if not cat_anchors:
                continue

            cat_cand_count = 0
            cat_max = category_budgets.get(cat, 50)

            for anch in cat_anchors:
                if cat_cand_count >= cat_max:
                    break

                x, y, z = anch.x, anch.y, anch.z

                # Boundary pre-check on anchor point
                if x >= container.Lx - eps or y >= container.Ly - eps or z >= container.Lz - eps:
                    continue

                anchors_sampled_by_type[cat.value] += 1

                for sku in eligible_skus:
                    if cat_cand_count >= cat_max:
                        break

                    # Target zone pre-filter
                    if target_zone is not None and sku.target_zone and sku.target_zone != target_zone:
                        continue

                    # Floor only constraint pre-filter
                    if sku.stacking_policy.must_be_on_floor and z > eps:
                        continue

                    ori_cands = orientation_engine.get_candidate_orientations(
                        sku=sku,
                        context=context,
                    )

                    for oc in ori_cands:
                        if cat_cand_count >= cat_max:
                            break

                        ori = oc.orientation
                        dx, dy, dz = ori.dx, ori.dy, ori.dz

                        # Container boundary pre-check
                        if (x + dx > container.Lx + eps or
                            y + dy > container.Ly + eps or
                            z + dz > container.Lz + eps):
                            continue

                        # Cheap support pre-filter: eliminate blatantly floating candidates
                        if z > eps and not self.has_possible_support(world_state, Point3D(x, y, z), ori):
                            continue

                        key = (
                            sku.sku_id,
                            round(x, 4),
                            round(y, 4),
                            round(z, 4),
                            round(dx, 4),
                            round(dy, 4),
                            round(dz, 4),
                        )
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)

                        cand = CandidatePlacement(
                            sku_id=sku.sku_id,
                            position=Point3D(x, y, z),
                            orientation=ori,
                            context=context,
                            weight_kg=sku.weight_kg,
                            orientation_penalty=oc.penalty_score,
                            anchor_category=cat,
                        )
                        candidates.append(cand)
                        cat_cand_count += 1
                        candidates_generated_by_anchor_type[cat.value] += 1

        self.last_telemetry = {
            "anchors_generated_by_type": anchors_generated_by_type,
            "anchors_sampled_by_type": anchors_sampled_by_type,
            "candidates_generated_by_anchor_type": candidates_generated_by_anchor_type,
            "floor_frontier_count": len(classified_anchors.get(AnchorCategory.FLOOR_FRONTIER, [])),
            "supported_frontier_count": len(classified_anchors.get(AnchorCategory.SUPPORTED_FRONTIER, [])),
            "wall_frontier_count": len(classified_anchors.get(AnchorCategory.WALL_FRONTIER, [])),
            "valleys_detected_count": len(frontier.valleys),
        }

        return candidates
