"""
Residual-Space-Aware Soft Scorer for Solver V2 (Agent 05 / BLK-002B).
Ranks feasible CandidatePlacement objects using a multi-objective scoring formula:
1. Immediate occupied volume gain (volume_weight)
2. Required Non-Elastic SKU Satisfaction Bonus (prevents SKU starvation / collapse)
3. Door Reserve Pool Deployment Bonus (rewards deploying reserve into door closure)
4. Residual Space Quality (FreeSpaceEngine: useful vol, reachable vol, cavity penalty, fragmentation)
5. Compactness (Floor-Rear-Left Gravity)
6. Zone Affinity Bonus (AdaptiveZoneManager)
7. Wall Flatness & Contact Continuity Bonus (continuous growth from existing wall surface)
8. Valley Filling Bonus & Wall Leveling Bonus (BLK-001 Phase 2)
9. Door Probe Feasibility Penalty (BLK-002)
10. Orientation Preference Penalty
"""
from typing import List, Optional, Dict, Any

from backend.solver_v2.domain.models import (
    CargoSKU,
    ContainerSpec,
    Placement,
    PlacementContext,
    PackingRole,
    ZoneType,
)
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.candidates.generator import CandidatePlacement
from backend.solver_v2.world.state import WorldState
from backend.solver_v2.spaces.engine import FreeSpaceEngine
from backend.solver_v2.zones.manager import AdaptiveZoneManager
from backend.solver_v2.door.elastic_frontier import ElasticDoorFrontier, ProbeStatus


class CandidateScorer:
    """
    Computes holistic scores for valid candidate placements.
    """

    def __init__(
        self,
        volume_weight: float = 150.0,
        residual_weight: float = 1.0,
        compactness_weight: float = 15.0,
        wall_flatness_weight: float = 15.0,
        valley_fill_weight: float = 25.0,
        wall_leveling_weight: float = 15.0,
        required_sku_weight: float = 40.0,
        wall_continuity_weight: float = 20.0,
        row_completion_weight: float = 25.0,
        layer_completion_weight: float = 25.0,
        cavity_creation_penalty_weight: float = 50.0,
        isolated_box_penalty_weight: float = 30.0,
    ):
        self.volume_weight = volume_weight
        self.residual_weight = residual_weight
        self.compactness_weight = compactness_weight
        self.wall_flatness_weight = wall_flatness_weight
        self.valley_fill_weight = valley_fill_weight
        self.wall_leveling_weight = wall_leveling_weight
        self.required_sku_weight = required_sku_weight
        self.wall_continuity_weight = wall_continuity_weight
        self.row_completion_weight = row_completion_weight
        self.layer_completion_weight = layer_completion_weight
        self.cavity_creation_penalty_weight = cavity_creation_penalty_weight
        self.isolated_box_penalty_weight = isolated_box_penalty_weight

    def score_candidate(
        self,
        candidate: CandidatePlacement,
        sku: CargoSKU,
        world_state: WorldState,
        space_engine: FreeSpaceEngine,
        zone_mgr: AdaptiveZoneManager,
        remaining_skus: Optional[List[CargoSKU]] = None,
        elastic_frontier: Optional[ElasticDoorFrontier] = None,
        context: Optional[PlacementContext] = None,
    ) -> float:
        """
        Computes composite scalar score with detailed Wall Formation breakdown.
        """
        container = world_state.container
        cand_vol = candidate.dx * candidate.dy * candidate.dz
        x, y, z = candidate.x, candidate.y, candidate.z
        dx, dy, dz = candidate.dx, candidate.dy, candidate.dz

        topfill_breakdown = dict(candidate.score_breakdown) if context == PlacementContext.TOP_FILL else {}
        breakdown: Dict[str, float] = {}

        # 1. Volume Gain
        vol_score = cand_vol * self.volume_weight
        breakdown["vol_score"] = round(vol_score, 3)

        # 2. Required Non-Elastic SKU Satisfaction Bonus
        required_bonus = 0.0
        if not sku.quantity.is_elastic:
            required_bonus += self.required_sku_weight
            if context in (PlacementContext.FOUNDATION, PlacementContext.MAIN_WALL):
                if PackingRole.MAIN_WALL in sku.packing_roles or PackingRole.FOUNDATION in sku.packing_roles:
                    required_bonus += 20.0

        if context == PlacementContext.DOOR_SEAL:
            if PackingRole.DOOR_SEAL in sku.packing_roles or sku.target_zone == ZoneType.DOOR:
                required_bonus += 50.0
        breakdown["required_bonus"] = round(required_bonus, 3)

        # 3. Compactness / Floor-Rear-Left Gravity
        x_ratio = x / container.Lx if container.Lx > 0 else 0.0
        y_ratio = y / container.Ly if container.Ly > 0 else 0.0
        z_ratio = z / container.Lz if container.Lz > 0 else 0.0
        compactness_score = -self.compactness_weight * (x_ratio * 1.2 + z_ratio * 1.0 + y_ratio * 0.4)
        breakdown["compactness_score"] = round(compactness_score, 3)

        # 4. Residual Space Quality
        temp_placement = candidate.to_placement(
            placement_id="temp_eval",
            instance_id="temp_inst",
        )
        res_metrics = space_engine.evaluate_candidate_residual(temp_placement, remaining_skus)
        residual_score = res_metrics.compute_quality_score() * self.residual_weight
        breakdown["residual_score"] = round(residual_score, 3)

        # 5. Zone Affinity Bonus
        zone_score = zone_mgr.compute_zone_affinity_score(sku, x, y, z, dx, dy, dz)
        breakdown["zone_score"] = round(zone_score, 3)

        # 6. Wall Continuity & Contact Bonus
        wall_continuity_bonus = 0.0
        touching_items = world_state.query_touching(candidate.aabb)
        has_lateral_neighbor = False
        if touching_items:
            touch_cnt = len(touching_items)
            wall_continuity_bonus += min(touch_cnt * 6.0, self.wall_continuity_weight)
            # Rear-contact bonus against existing front face
            if any(abs(item[0].max_x - x) <= 0.01 for item in touching_items if item[0] is not None):
                wall_continuity_bonus += 12.0
            # Lateral Y contact bonus (forming continuous full-width Row across container)
            if any(abs(item[0].max_y - y) <= 0.01 or abs(item[0].min_y - (y + dy)) <= 0.01 for item in touching_items if item[0] is not None):
                wall_continuity_bonus += 16.0
                has_lateral_neighbor = True
        breakdown["wall_continuity_bonus"] = round(wall_continuity_bonus, 3)

        # 7. Row & Layer Completion Bonus
        row_completion_bonus = 0.0
        layer_completion_bonus = 0.0

        # Completing row boundary against container wall or extending from lateral neighbor
        if abs(y) <= 0.01 or abs(y + dy - container.Ly) <= 0.01 or has_lateral_neighbor:
            row_completion_bonus += 14.0
        # Check if adjacent to neighbor at same Z level
        for it, ctype in touching_items:
            if it and abs(it.min_z - z) <= 0.02 and abs(it.orientation.dz - dz) <= 0.02:
                row_completion_bonus += 12.0
                break

        # Transverse Full-Width Wall Priority:
        # Heavily penalize advancing forward in X when the current rear cross-section still has empty lateral width!
        transverse_priority = 0.0
        if world_state.placement_count > 0:
            rear_boxes = [p for p in world_state.placements if p.min_x < x - 0.05]
            if rear_boxes:
                rear_max_y = max(p.max_y for p in rear_boxes)
                if rear_max_y + dy <= container.Ly + 0.01:
                    # Advancing in X while rear width is incomplete
                    transverse_priority -= 45.0
            min_existing_x = min(p.min_x for p in world_state.placements)
            if x <= min_existing_x + 0.08:
                # Completing the deepest transverse wall across width
                transverse_priority += 25.0

        # Layer completion bonus: floor contact or resting flush on lower layer
        if abs(z) <= 0.01:
            layer_completion_bonus += 15.0
        elif any(it and abs(it.max_z - z) <= 0.01 for it, _ in touching_items):
            layer_completion_bonus += 8.0

        breakdown["row_completion_bonus"] = round(row_completion_bonus, 3)
        breakdown["layer_completion_bonus"] = round(layer_completion_bonus, 3)
        breakdown["transverse_priority"] = round(transverse_priority, 3)

        # 8. Valley Filling Bonus & Surface Flatness Bonus
        valley_fill_bonus = 0.0
        surface_flatness_bonus = 0.0
        height_step_penalty = 0.0
        isolated_box_penalty = 0.0

        if world_state.placement_count > 0:
            peak_x = world_state.max_x
            if x + dx <= peak_x + 0.05 and x < peak_x - 0.08:
                # Fills a recessed valley without overshooting
                valley_fill_bonus = min(self.valley_fill_weight, (peak_x - x) * 20.0)
            elif x + dx > peak_x + 0.40:
                # Creates an abrupt longitudinal step (protruding peak)
                height_step_penalty = min(25.0, (x + dx - peak_x) * 15.0)

            # Isolated box penalty: floating forward without lateral/rear contact
            if not touching_items and z > 0.01:
                isolated_box_penalty = self.isolated_box_penalty_weight
            elif len(touching_items) == 1 and touching_items[0][0] is not None and touching_items[0][0].min_z < z and abs(y) > 0.05 and abs(y + dy - container.Ly) > 0.05:
                # Isolated pillar on top of another without side brace
                isolated_box_penalty = 10.0

        breakdown["valley_fill_bonus"] = round(valley_fill_bonus, 3)
        breakdown["surface_flatness_bonus"] = round(surface_flatness_bonus, 3)
        breakdown["height_step_penalty"] = round(height_step_penalty, 3)
        breakdown["isolated_box_penalty"] = round(isolated_box_penalty, 3)

        # 9. Cavity Creation & Anti-Bridge Penalty
        cavity_creation_penalty = 0.0
        # If candidate spans above a gap without solid continuous base support
        if z > 0.01:
            # Query support contact
            support_aabb = AABB(x, y, z - 0.05, x + dx, y + dy, z + 0.001)
            lower_touch = world_state.spatial_index.query_intersect(support_aabb, eps=0.001)
            if len(lower_touch) >= 2:
                # Check for hollow void beneath candidate center
                mid_x = x + dx * 0.5
                mid_y = y + dy * 0.5
                probe_aabb = AABB(mid_x - 0.05, mid_y - 0.05, z - 0.15, mid_x + 0.05, mid_y + 0.05, z - 0.01)
                under_mid = world_state.spatial_index.query_intersect(probe_aabb, eps=0.001)
                if not under_mid:
                    # Bridge over hollow cavity!
                    cavity_creation_penalty = self.cavity_creation_penalty_weight
        breakdown["cavity_creation_penalty"] = round(cavity_creation_penalty, 3)

        # 10. Door Probe Feasibility Penalty (BLK-002)
        probe_penalty = 0.0
        if elastic_frontier:
            is_door = (PackingRole.DOOR_SEAL in sku.packing_roles or sku.target_zone == ZoneType.DOOR)
            probe = elastic_frontier.evaluate_probe(
                candidate_max_x=x + dx,
                current_max_x=world_state.max_x,
                is_door_sku=is_door,
                context=context,
            )
            probe_penalty = probe.penalty
        breakdown["probe_penalty"] = round(probe_penalty, 3)

        # 11. Orientation Preference Penalty
        ori_penalty = candidate.orientation_penalty
        breakdown["ori_penalty"] = round(ori_penalty, 3)

        total_score = (
            vol_score
            + required_bonus
            + compactness_score
            + residual_score
            + zone_score
            + wall_continuity_bonus
            + row_completion_bonus
            + layer_completion_bonus
            + valley_fill_bonus
            + surface_flatness_bonus
            + transverse_priority
            - height_step_penalty
            - isolated_box_penalty
            - cavity_creation_penalty
            - probe_penalty
            - ori_penalty
            + sum(topfill_breakdown.values())
        )

        if topfill_breakdown:
            breakdown.update(topfill_breakdown)

        candidate.score = total_score
        setattr(candidate, "score_breakdown", breakdown)
        return total_score
