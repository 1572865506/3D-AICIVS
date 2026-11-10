"""
Aggregate structure generation and candidate management for Solver V2 (Agent 09 / P0 BLK-001 Phase 2).
Implements stepwise aggregate downgrade (Layer -> Row -> Small Block -> Individual Carton),
ActivePackingFrontier continuous floor rebuild, valley anchors, and fair multi-SKU candidate quotas.
"""
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any, Set

from backend.solver_v2.domain.models import (
    BoxDim,
    Point3D,
    Orientation3D,
    CargoSKU,
    Placement,
    PlacementContext,
    ContainerSpec,
)
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.spaces.types import AnchorCategory, ClassifiedAnchor
from backend.solver_v2.patterns.models import PackedBlock, PatternType, ItemOffset
from backend.solver_v2.patterns.generator import PatternGenerator
from backend.solver_v2.candidates.generator import CandidatePlacement, CandidateGenerator, CandidateBudget
from backend.solver_v2.spaces.engine import FreeSpaceEngine
from backend.solver_v2.orientation.manager import OrientationEngine
from backend.solver_v2.zones.manager import AdaptiveZoneManager
from backend.solver_v2.quantity.manager import QuantityManager
from backend.solver_v2.world.state import WorldState
from backend.solver_v2.structure.wall_surface import WallSurfaceMap, ActivePackingFrontier


@dataclass
class AggregateCandidate:
    """
    Represents an aggregate packing action (a block, layer, row, or single item)
    to be evaluated and committed as an atomic unit.
    """
    candidate_id: str
    sku_id: str
    context: PlacementContext
    anchor: Point3D
    bounding_box: AABB
    item_candidates: List[CandidatePlacement]
    total_volume: float
    total_weight_kg: float
    item_count: int
    pattern_type: PatternType = PatternType.BLOCK
    heuristic_score: float = 0.0
    anchor_category: AnchorCategory = AnchorCategory.EXPLORATION
    candidate_family: str = "HOMOGENEOUS_WALL"
    candidate_signature: str = ""

    @property
    def is_aggregate(self) -> bool:
        return self.item_count > 1


class AggregateCandidateGenerator:
    """
    Generates structured aggregate candidates with stepwise downgrade:
    Large Block -> Horizontal Layer -> Linear Row -> Small Block -> Single Carton.
    Equipped with ActivePackingFrontier continuous floor & valley anchors.
    """

    def __init__(
        self,
        pattern_generator: Optional[PatternGenerator] = None,
        geom_epsilon: float = DEFAULT_GEOM_EPSILON,
    ):
        self.pattern_generator = pattern_generator or PatternGenerator(geom_epsilon=geom_epsilon)
        self.geom_epsilon = geom_epsilon
        self._cand_gen_helper = CandidateGenerator(geom_epsilon=geom_epsilon)

    def generate_aggregate_candidates(
        self,
        space_engine: FreeSpaceEngine,
        orientation_engine: OrientationEngine,
        zone_mgr: AdaptiveZoneManager,
        qty_mgr: QuantityManager,
        active_skus: List[CargoSKU],
        context: PlacementContext,
        max_candidates: int = 200,
        enable_patterns: bool = True,
        max_block_nx: int = 6,
        max_block_ny: int = 6,
        max_block_nz: int = 4,
        world_state: Optional[WorldState] = None,
        is_wall_stalled: bool = False,
    ) -> List[AggregateCandidate]:
        """
        Generates candidate aggregate structures with stepwise downgrade and continuous frontier anchors.
        """
        candidates: List[AggregateCandidate] = []
        if context == PlacementContext.TOP_FILL and world_state is not None:
            singles = self._cand_gen_helper.generate_candidates(
                world_state=world_state,
                space_engine=space_engine,
                orientation_engine=orientation_engine,
                zone_mgr=zone_mgr,
                qty_mgr=qty_mgr,
                active_skus=active_skus,
                context=context,
                max_candidates=max_candidates,
            )
            return [AggregateCandidate(
                candidate_id=f"topfill_{idx}_{cand.sku_id}_{cand.topfill_region_id}",
                sku_id=cand.sku_id,
                context=context,
                anchor=cand.position,
                bounding_box=cand.aabb,
                item_candidates=[cand],
                total_volume=cand.orientation.volume,
                total_weight_kg=cand.weight_kg,
                item_count=1,
                pattern_type=PatternType.LAYER,
                heuristic_score=cand.score,
                anchor_category=AnchorCategory.TOP_SURFACE,
            ) for idx, cand in enumerate(singles)]
        classified_anchors = space_engine.get_classified_anchors(world_state=world_state)
        container = zone_mgr.container
        eps = self.geom_epsilon

        # 1. Continuous Floor & Valley Frontier Extraction from WorldState
        wall_map = WallSurfaceMap(container=container, geom_epsilon=eps)
        max_allowed_x = container.Lx - (zone_mgr.door_zone_length_m if context != PlacementContext.DOOR_SEAL else 0.0)
        placements = world_state.placements if world_state else []
        frontier = wall_map.extract_active_packing_frontier(placements, max_allowed_x=max_allowed_x)

        # Supplement floor frontier anchors
        existing_floor_pts = {(round(a.x, 3), round(a.y, 3)) for a in classified_anchors.get(AnchorCategory.FLOOR_FRONTIER, [])}
        for fa in frontier.floor_frontier_anchors:
            if (round(fa.x, 3), round(fa.y, 3)) not in existing_floor_pts:
                classified_anchors[AnchorCategory.FLOOR_FRONTIER].append(fa)
                existing_floor_pts.add((round(fa.x, 3), round(fa.y, 3)))

        # Add valley anchors
        for v in frontier.valleys:
            classified_anchors[AnchorCategory.GAP_FILL].append(
                ClassifiedAnchor(
                    point=v.anchor,
                    category=AnchorCategory.GAP_FILL,
                    support_z=v.min_z,
                    priority_score=100.0 * v.depth_m,
                )
            )

        # Sort floor frontier
        classified_anchors[AnchorCategory.FLOOR_FRONTIER].sort(key=lambda a: (round(a.x, 4), round(a.y, 4)))

        # Prioritized categories order
        if is_wall_stalled:
            cat_priority = [
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
            cat_priority = [
                AnchorCategory.FLOOR_FRONTIER,
                AnchorCategory.SUPPORTED_FRONTIER,
                AnchorCategory.WALL_FRONTIER,
                AnchorCategory.GAP_FILL,
                AnchorCategory.EMS_CORNER,
                AnchorCategory.TOP_SURFACE,
                AnchorCategory.EXTREME_POINT,
                AnchorCategory.EXPLORATION,
            ]

        # Calculate per-SKU candidate quota
        num_skus = max(1, len(active_skus))
        per_sku_block_quota = max(10, max_candidates // num_skus)
        per_sku_single_quota = max(15, (max_candidates * 2) // num_skus)

        seen_keys: Set[str] = set()

        # 1. Stepwise Pattern Candidates (Blocks -> Layers -> Rows -> Small Blocks)
        if enable_patterns and context in (PlacementContext.FOUNDATION, PlacementContext.MAIN_WALL):
            for sku in active_skus:
                rem_qty = qty_mgr.get_remaining(sku.sku_id)
                if rem_qty <= 0:
                    continue

                sku_block_count = 0

                blocks = self.pattern_generator.generate_blocks_for_sku(
                    sku=sku,
                    context=context,
                    max_quantity=rem_qty,
                    max_nx=max_block_nx,
                    max_ny=max_block_ny,
                    max_nz=max_block_nz,
                )

                # Sort blocks by hierarchy: Full Layers/Rows first, then smaller blocks
                blocks.sort(key=lambda b: (b.total_cartons, b.volume), reverse=True)

                for block in blocks:
                    if block.total_cartons <= 1:
                        continue
                    if sku_block_count >= per_sku_block_quota:
                        break

                    for cat in cat_priority:
                        if sku_block_count >= per_sku_block_quota:
                            break

                        anchors = classified_anchors.get(cat, [])
                        for anch in anchors:
                            if sku_block_count >= per_sku_block_quota:
                                break

                            pos = anch.point
                            if (pos.x + block.bounding_box.x > container.Lx + eps or
                                pos.y + block.bounding_box.y > container.Ly + eps or
                                pos.z + block.bounding_box.z > container.Lz + eps):
                                continue

                            if sku.stacking_policy.must_be_on_floor and pos.z > eps:
                                continue

                            # Cheap support pre-filter
                            if pos.z > eps and world_state is not None:
                                first_ori = block.item_offsets[0].orientation
                                if not self._cand_gen_helper.has_possible_support(world_state, pos, first_ori):
                                    continue

                            is_comp, _ = zone_mgr.check_hard_zone_compliance(
                                sku=sku,
                                x=pos.x,
                                y=pos.y,
                                z=pos.z,
                                dx=block.bounding_box.x,
                                dy=block.bounding_box.y,
                                dz=block.bounding_box.z,
                            )
                            if not is_comp:
                                continue

                            block_key = f"agg_{sku.sku_id}_{pos.x:.3f}_{pos.y:.3f}_{pos.z:.3f}_{block.nx}x{block.ny}x{block.nz}"
                            if block_key in seen_keys:
                                continue
                            seen_keys.add(block_key)

                            cand_aabb = AABB(
                                min_x=pos.x,
                                min_y=pos.y,
                                min_z=pos.z,
                                max_x=pos.x + block.bounding_box.x,
                                max_y=pos.y + block.bounding_box.y,
                                max_z=pos.z + block.bounding_box.z,
                            )

                            item_cands: List[CandidatePlacement] = []
                            for off in block.item_offsets:
                                item_pos = Point3D(
                                    x=pos.x + off.relative_position.x,
                                    y=pos.y + off.relative_position.y,
                                    z=pos.z + off.relative_position.z,
                                )
                                ic = CandidatePlacement(
                                    sku_id=sku.sku_id,
                                    position=item_pos,
                                    orientation=off.orientation,
                                    context=context,
                                    weight_kg=sku.weight_kg,
                                    anchor_category=cat,
                                )
                                item_cands.append(ic)

                            agg = AggregateCandidate(
                                candidate_id=block_key,
                                sku_id=sku.sku_id,
                                context=context,
                                anchor=pos,
                                bounding_box=cand_aabb,
                                item_candidates=item_cands,
                                total_volume=block.volume,
                                total_weight_kg=sku.weight_kg * block.total_cartons,
                                item_count=block.total_cartons,
                                pattern_type=block.pattern_type,
                                anchor_category=cat,
                            )
                            candidates.append(agg)
                            sku_block_count += 1

        # 2. Single item fallback across all active SKUs and categories
        for sku in active_skus:
            rem_qty = qty_mgr.get_remaining(sku.sku_id)
            if rem_qty <= 0:
                continue

            sku_single_count = 0
            orientations = orientation_engine.get_candidate_orientations(
                sku=sku,
                context=context,
            )

            for cat in cat_priority:
                if sku_single_count >= per_sku_single_quota:
                    break

                anchors = classified_anchors.get(cat, [])
                for anch in anchors:
                    if sku_single_count >= per_sku_single_quota:
                        break

                    pos = anch.point
                    if pos.x >= container.Lx - eps or pos.y >= container.Ly - eps or pos.z >= container.Lz - eps:
                        continue

                    if sku.stacking_policy.must_be_on_floor and pos.z > eps:
                        continue

                    for cand_ori in orientations:
                        if sku_single_count >= per_sku_single_quota:
                            break

                        ori = cand_ori.orientation
                        dx, dy, dz = ori.dx, ori.dy, ori.dz

                        if (pos.x + dx > container.Lx + eps or
                            pos.y + dy > container.Ly + eps or
                            pos.z + dz > container.Lz + eps):
                            continue

                        # Cheap support pre-filter
                        if pos.z > eps and world_state is not None:
                            if not self._cand_gen_helper.has_possible_support(world_state, pos, ori):
                                continue

                        is_comp, _ = zone_mgr.check_hard_zone_compliance(
                            sku=sku,
                            x=pos.x,
                            y=pos.y,
                            z=pos.z,
                            dx=dx,
                            dy=dy,
                            dz=dz,
                        )
                        if not is_comp:
                            continue

                        single_key = f"single_{sku.sku_id}_{pos.x:.3f}_{pos.y:.3f}_{pos.z:.3f}_{dx:.3f}_{dy:.3f}_{dz:.3f}"
                        if single_key in seen_keys:
                            continue
                        seen_keys.add(single_key)

                        cand_aabb = AABB(
                            min_x=pos.x,
                            min_y=pos.y,
                            min_z=pos.z,
                            max_x=pos.x + dx,
                            max_y=pos.y + dy,
                            max_z=pos.z + dz,
                        )

                        ic = CandidatePlacement(
                            sku_id=sku.sku_id,
                            position=pos,
                            orientation=ori,
                            context=context,
                            weight_kg=sku.weight_kg,
                            orientation_penalty=cand_ori.penalty_score,
                            anchor_category=cat,
                        )
                        agg = AggregateCandidate(
                            candidate_id=single_key,
                            sku_id=sku.sku_id,
                            context=context,
                            anchor=pos,
                            bounding_box=cand_aabb,
                            item_candidates=[ic],
                            total_volume=dx * dy * dz,
                            total_weight_kg=sku.weight_kg,
                            item_count=1,
                            pattern_type=PatternType.BLOCK,
                            anchor_category=cat,
                        )
                        candidates.append(agg)
                        sku_single_count += 1

        return candidates
