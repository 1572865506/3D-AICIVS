from collections import Counter

from backend.solver_v2.domain.models import Placement, PlacementContext, Point3D
from backend.solver_v2.geometry.aabb import AABB
from .OrientationOptimizer import OrientationOptimizer


class LayerCompletionEngine:
    """Bounded floor-gap completion; it never moves or rotates frozen structural cargo."""

    def __init__(self, max_added=32):
        self.max_added = max_added
        self.orientations = OrientationOptimizer()

    @staticmethod
    def _free_side_regions(container, walls):
        regions = []
        for wall in walls:
            if not wall.placements:
                continue
            y0 = min(p.min_y for p in wall.placements)
            y1 = max(p.max_y for p in wall.placements)
            height = min(container.Lz, max(p.max_z for p in wall.placements))
            if y0 > 1e-6:
                regions.append((f"{wall.id}_LEFT", AABB(wall.x_start, 0.0, 0.0, wall.x_end, y0, height)))
            if container.Ly - y1 > 1e-6:
                regions.append((f"{wall.id}_RIGHT", AABB(wall.x_start, y1, 0.0, wall.x_end, container.Ly, height)))
        return tuple(sorted(regions, key=lambda item: (item[1].min_x, item[1].min_y, item[0])))

    @staticmethod
    def _collides(placement, existing):
        box = AABB.from_placement(placement)
        return any(box.penetration_volume(AABB.from_placement(other)) > 1e-12 for other in existing)

    def complete(self, container, cargo, existing, walls, intelligence_adapter=None, intelligence=None):
        catalog = {sku.sku_id: sku for sku in cargo}
        used = Counter(p.sku_id for p in existing)
        placements = []
        decisions = []
        for wall_id, region in self._free_side_regions(container, walls):
            if len(placements) >= self.max_added:
                break
            choices = []
            for sku in cargo:
                remaining = sku.quantity.required - used[sku.sku_id]
                if remaining <= 0:
                    continue
                decision = self.orientations.optimize(
                    sku, PlacementContext.MAIN_WALL, region,
                    intelligence_adapter, intelligence, 1.0, 1.0,
                )
                if decision:
                    capacity = int((region.dx + 1e-9) // decision.orientation.dx) * int((region.dy + 1e-9) // decision.orientation.dy)
                    profile = intelligence.profiles[sku.sku_id] if intelligence else None
                    if profile and "NEIGHBOR_SUPPORT_REQUIRED" in profile.specialRules and capacity < 2:
                        continue
                    choices.append((decision, remaining))
            choices.sort(key=lambda pair: (-pair[0].score, -pair[0].volume_gain, pair[0].sku_id, pair[0].orientation.name))
            if not choices:
                continue
            decision, remaining = choices[0]
            sku = catalog[decision.sku_id]
            ori = decision.orientation
            nx = int((region.dx + 1e-9) // ori.dx)
            ny = int((region.dy + 1e-9) // ori.dy)
            if nx <= 0 or ny <= 0:
                continue
            added_here = 0
            for ix in range(nx):
                for iy in range(ny):
                    if added_here >= remaining or len(placements) >= self.max_added:
                        break
                    placement = Placement(
                        f"layer_complete_{wall_id}_{sku.sku_id}_{ix}_{iy}",
                        f"layer_complete_{sku.sku_id}_{used[sku.sku_id] + added_here:04d}",
                        sku.sku_id,
                        Point3D(round(region.min_x + ix * ori.dx, 6), round(region.min_y + iy * ori.dy, 6), 0.0),
                        ori, sku.weight_kg, PlacementContext.MAIN_WALL,
                        len(existing) + len(placements),
                    )
                    if self._collides(placement, tuple(existing) + tuple(placements)):
                        continue
                    placements.append(placement)
                    added_here += 1
                if added_here >= remaining or len(placements) >= self.max_added:
                    break
            if added_here:
                used[sku.sku_id] += added_here
                decisions.append(decision)
        return tuple(placements), tuple(decisions)
