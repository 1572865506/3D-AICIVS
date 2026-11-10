"""BLK-006B deterministic diverse wall proposal generation and canonicalization."""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import replace
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from backend.solver_v2.domain.models import OrientationMode, PlacementContext, Point3D
from backend.solver_v2.candidates.generator import CandidatePlacement
from backend.solver_v2.geometry.aabb import AABB, DEFAULT_GEOM_EPSILON
from backend.solver_v2.patterns.models import PatternType
from backend.solver_v2.quantity.manager import QuantityManager
from backend.solver_v2.search.aggregate import AggregateCandidate
from backend.solver_v2.spaces.types import AnchorCategory
from backend.solver_v2.world.state import WorldState


FAMILIES = (
    "HOMOGENEOUS_WALL", "ALTERNATE_ORIENTATION_WALL", "ALTERNATE_WIDTH_WALL",
    "ALTERNATE_HEIGHT_WALL", "MIXED_SKU_WALL", "RESIDUAL_AWARE_WALL",
)


@dataclass(frozen=True)
class CandidateSignature:
    sku_composition: Tuple[Tuple[str, int], ...]
    orientation_composition: Tuple[Tuple[str, int], ...]
    dimensions: Tuple[float, float, float]
    wall_width: float
    layer_structure: Tuple[float, ...]
    placement_geometry_fingerprint: str

    @classmethod
    def from_candidate(cls, candidate: AggregateCandidate) -> "CandidateSignature":
        items = candidate.item_candidates
        sku_comp = tuple(sorted(Counter(item.sku_id for item in items).items()))
        ori_comp = tuple(sorted(Counter(item.orientation.name for item in items).items()))
        min_x = min((item.x for item in items), default=0.0)
        min_y = min((item.y for item in items), default=0.0)
        min_z = min((item.z for item in items), default=0.0)
        max_x = max((item.x + item.dx for item in items), default=min_x)
        max_y = max((item.y + item.dy for item in items), default=min_y)
        max_z = max((item.z + item.dz for item in items), default=min_z)
        layers = tuple(sorted({round(item.z - min_z, 6) for item in items}))
        geometry = sorted(
            (item.sku_id, item.orientation.name, round(item.x - min_x, 6),
             round(item.y - min_y, 6), round(item.z - min_z, 6))
            for item in items
        )
        fingerprint = hashlib.sha256(
            json.dumps(geometry, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:20]
        return cls(
            sku_composition=sku_comp,
            orientation_composition=ori_comp,
            dimensions=(round(max_x - min_x, 6), round(max_y - min_y, 6), round(max_z - min_z, 6)),
            wall_width=round(max_x - min_x, 6),
            layer_structure=layers,
            placement_geometry_fingerprint=fingerprint,
        )

    def canonical_key(self) -> str:
        return json.dumps({
            "sku": self.sku_composition, "orientation": self.orientation_composition,
            "dimensions": self.dimensions, "wall_width": self.wall_width,
            "layers": self.layer_structure, "geometry": self.placement_geometry_fingerprint,
        }, sort_keys=True, separators=(",", ":"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sku_composition": [list(item) for item in self.sku_composition],
            "orientation_composition": [list(item) for item in self.orientation_composition],
            "dimensions": list(self.dimensions), "wall_width": self.wall_width,
            "layer_structure": list(self.layer_structure),
            "placement_geometry_fingerprint": self.placement_geometry_fingerprint,
        }


@dataclass
class DiversePoolResult:
    proposals: List[AggregateCandidate] = field(default_factory=list)
    raw_generated: int = 0
    duplicates_removed: int = 0
    cheap_rejected: int = 0
    cheap_rejection_reasons: Dict[str, int] = field(default_factory=dict)
    proposed_by_family: Dict[str, int] = field(default_factory=dict)


class DiverseWallCandidateGenerator:
    """Family-aware bounded enumeration over existing general aggregate proposals."""
    def __init__(self, geom_epsilon: float = DEFAULT_GEOM_EPSILON):
        self.geom_epsilon = geom_epsilon
        self._signature_cache: Dict[Tuple[Any, ...], CandidateSignature] = {}
        self.cache_hits = 0
        self.cache_misses = 0
        self.cache_saved_estimated_ms = 0.0
        self._signature_miss_total_ms = 0.0

    def signature_for(self, candidate: AggregateCandidate) -> CandidateSignature:
        items = candidate.item_candidates
        min_x = min((item.x for item in items), default=0.0)
        min_y = min((item.y for item in items), default=0.0)
        min_z = min((item.z for item in items), default=0.0)
        key = tuple(sorted(
            (item.sku_id, item.orientation.name, round(item.x - min_x, 6),
             round(item.y - min_y, 6), round(item.z - min_z, 6),
             round(item.dx, 6), round(item.dy, 6), round(item.dz, 6))
            for item in items
        ))
        cached = self._signature_cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            self.cache_saved_estimated_ms += self._signature_miss_total_ms / max(1, self.cache_misses)
            return cached
        started = time.perf_counter()
        signature = CandidateSignature.from_candidate(candidate)
        self._signature_miss_total_ms += (time.perf_counter() - started) * 1000.0
        self.cache_misses += 1
        self._signature_cache[key] = signature
        return signature

    def build_pool(
        self,
        raw: List[AggregateCandidate],
        world_state: WorldState,
        qty_mgr: QuantityManager,
        max_proposals: int = 12,
        phase: str = "MAIN",
    ) -> DiversePoolResult:
        result = DiversePoolResult(raw_generated=len(raw))
        rejection = Counter()
        canonical: Dict[str, AggregateCandidate] = {}
        for original in raw:
            candidate = self._align_to_frontier(original, world_state)
            reason = self._cheap_rejection(candidate, world_state, qty_mgr)
            if reason:
                result.cheap_rejected += 1
                rejection[reason] += 1
                continue
            signature = self.signature_for(candidate)
            key = signature.canonical_key()
            if key in canonical:
                result.duplicates_removed += 1
                continue
            candidate.candidate_signature = key
            canonical[key] = candidate

        candidates = list(canonical.values())
        mixed = self._mixed_candidates(candidates, world_state, qty_mgr, limit=3)
        for candidate in mixed:
            signature = self.signature_for(candidate)
            key = signature.canonical_key()
            if key in canonical:
                result.duplicates_removed += 1
                continue
            candidate.candidate_signature = key
            canonical[key] = candidate
            candidates.append(candidate)

        # Determine structural maxima used to distinguish bounded partial variants.
        by_sku_ori: Dict[Tuple[str, str], List[AggregateCandidate]] = defaultdict(list)
        for candidate in candidates:
            if candidate.item_candidates:
                key = (candidate.item_candidates[0].sku_id, candidate.item_candidates[0].orientation.name)
                by_sku_ori[key].append(candidate)
        max_width = {key: max(c.bounding_box.dx for c in values) for key, values in by_sku_ori.items()}
        max_layers = {key: max(self._layer_count(c) for c in values) for key, values in by_sku_ori.items()}
        primary_orientation: Dict[str, str] = {}
        for candidate in candidates:
            if candidate.item_candidates:
                primary_orientation.setdefault(candidate.item_candidates[0].sku_id, candidate.item_candidates[0].orientation.name)

        buckets: Dict[str, List[AggregateCandidate]] = {family: [] for family in FAMILIES}
        for candidate in candidates:
            family = self._family(candidate, max_width, max_layers, primary_orientation, world_state)
            candidate.candidate_family = family
            buckets[family].append(candidate)
        for family in FAMILIES:
            buckets[family].sort(key=self._deterministic_rank)

        selected: List[AggregateCandidate] = []
        seen: Set[str] = set()
        # One per family first, then round-robin to avoid max-fill collapse.
        # Near the door, use the same general proposals but visit surface- and
        # residual-aware families first; no door geometry or SKU is hard-coded.
        family_order = FAMILIES if phase != "TRANSITION" else (
            "RESIDUAL_AWARE_WALL", "MIXED_SKU_WALL", "ALTERNATE_WIDTH_WALL",
            "ALTERNATE_HEIGHT_WALL", "ALTERNATE_ORIENTATION_WALL", "HOMOGENEOUS_WALL",
        )
        for family in family_order:
            self._take(buckets[family], selected, seen, 1, max_proposals)
        round_index = 1
        while len(selected) < max_proposals:
            progressed = False
            for family in family_order:
                if round_index < len(buckets[family]):
                    candidate = buckets[family][round_index]
                    if candidate.candidate_signature not in seen:
                        selected.append(candidate)
                        seen.add(candidate.candidate_signature)
                        progressed = True
                        if len(selected) >= max_proposals:
                            break
            if not progressed:
                leftovers = sorted(candidates, key=self._deterministic_rank)
                for candidate in leftovers:
                    if candidate.candidate_signature not in seen:
                        selected.append(candidate)
                        seen.add(candidate.candidate_signature)
                        progressed = True
                        if len(selected) >= max_proposals:
                            break
            if not progressed:
                break
            round_index += 1
        result.proposals = selected
        result.cheap_rejection_reasons = dict(rejection)
        result.proposed_by_family = dict(Counter(c.candidate_family for c in selected))
        return result

    def _align_to_frontier(
        self,
        candidate: AggregateCandidate,
        world_state: WorldState,
    ) -> AggregateCandidate:
        """Translate a reusable legal pattern template to the active MAIN frontier."""
        target_x = world_state.max_x
        if candidate.bounding_box.max_x > target_x + 0.05:
            return candidate
        shift = target_x - candidate.bounding_box.min_x
        if shift <= self.geom_epsilon:
            return candidate
        translated_items = [
            replace(item, position=Point3D(item.x + shift, item.y, item.z))
            for item in candidate.item_candidates
        ]
        box = candidate.bounding_box
        return replace(
            candidate,
            candidate_id=f"{candidate.candidate_id}_FX{target_x:.3f}",
            anchor=Point3D(candidate.anchor.x + shift, candidate.anchor.y, candidate.anchor.z),
            bounding_box=AABB(
                box.min_x + shift, box.min_y, box.min_z,
                box.max_x + shift, box.max_y, box.max_z,
            ),
            item_candidates=translated_items,
            candidate_signature="",
        )

    def _cheap_rejection(self, candidate, world_state, qty_mgr) -> Optional[str]:
        if not candidate.item_candidates:
            return "EMPTY"
        counts = Counter(item.sku_id for item in candidate.item_candidates)
        for sku_id, count in counts.items():
            if count > qty_mgr.get_remaining(sku_id, PlacementContext.MAIN_WALL):
                return "INVENTORY_IMPOSSIBLE"
        for item in candidate.item_candidates:
            if not item.aabb.is_within_bounds(
                world_state.container.Lx, world_state.container.Ly, world_state.container.Lz,
                eps=self.geom_epsilon,
            ):
                return "OBVIOUS_BOUNDS"
            sku = world_state._cargo_catalog.get(item.sku_id)
            if sku is None:
                return "UNKNOWN_SKU"
            mode = OrientationMode.FLAT if item.orientation.is_flat else (
                OrientationMode.SIDE if item.orientation.is_side else OrientationMode.UPRIGHT
            )
            if sku.orientation_policy.rule_for(mode, PlacementContext.MAIN_WALL) is None:
                return "ORIENTATION_INADMISSIBLE"
        if candidate.bounding_box.max_x <= world_state.max_x + 0.05:
            return "NO_FRONTIER_ADVANCEMENT"
        min_z = min(item.z for item in candidate.item_candidates)
        if min_z > self.geom_epsilon:
            bottom = [item for item in candidate.item_candidates if abs(item.z - min_z) <= self.geom_epsilon]
            if not any(self._has_world_support(item, world_state) for item in bottom):
                return "ZERO_SUPPORT_GEOMETRY"
        return None

    def _has_world_support(self, item, world_state) -> bool:
        if item.z <= self.geom_epsilon:
            return True
        for placement in world_state.placements:
            if abs(placement.max_z - item.z) > self.geom_epsilon:
                continue
            ox = min(placement.max_x, item.x + item.dx) - max(placement.min_x, item.x)
            oy = min(placement.max_y, item.y + item.dy) - max(placement.min_y, item.y)
            if ox > self.geom_epsilon and oy > self.geom_epsilon:
                return True
        return False

    def _mixed_candidates(self, candidates, world_state, qty_mgr, limit):
        small = sorted(
            [c for c in candidates if c.item_count <= 30],
            key=lambda c: (c.item_count, c.candidate_id),
        )
        mixed = []
        for i, left in enumerate(small):
            left_skus = {item.sku_id for item in left.item_candidates}
            for right in small[i + 1:]:
                right_skus = {item.sku_id for item in right.item_candidates}
                if left_skus == right_skus or self._aabb_penetrates(left.bounding_box, right.bounding_box):
                    continue
                items = list(left.item_candidates) + list(right.item_candidates)
                x0 = min(item.x for item in items); y0 = min(item.y for item in items); z0 = min(item.z for item in items)
                x1 = max(item.x + item.dx for item in items); y1 = max(item.y + item.dy for item in items); z1 = max(item.z + item.dz for item in items)
                candidate = AggregateCandidate(
                    candidate_id=f"mixed_{left.candidate_id}__{right.candidate_id}",
                    sku_id="MIXED",
                    context=PlacementContext.MAIN_WALL,
                    anchor=Point3D(x0, y0, z0),
                    bounding_box=AABB(x0, y0, z0, x1, y1, z1),
                    item_candidates=items,
                    total_volume=sum(item.orientation.volume for item in items),
                    total_weight_kg=sum(item.weight_kg for item in items),
                    item_count=len(items), pattern_type=PatternType.COMPOSITE,
                    anchor_category=AnchorCategory.WALL_FRONTIER,
                    candidate_family="MIXED_SKU_WALL",
                )
                if self._cheap_rejection(candidate, world_state, qty_mgr) is None:
                    mixed.append(candidate)
                    if len(mixed) >= limit:
                        return mixed
        # Raw homogeneous aggregates commonly share a frontier anchor, so direct
        # union overlaps. Deterministically build an alternating transverse row
        # from two legal templates at the same floor frontier instead.
        templates: Dict[Tuple[str, str], Any] = {}
        for candidate in candidates:
            for item in candidate.item_candidates:
                if item.z <= self.geom_epsilon:
                    templates.setdefault((item.sku_id, item.orientation.name), item)
                    break
        ordered = [templates[key] for key in sorted(templates)]
        for i, left in enumerate(ordered):
            for right in ordered[i + 1:]:
                if left.sku_id == right.sku_id:
                    continue
                x0 = max(left.x, right.x)
                y0 = min(left.y, right.y)
                if x0 + max(left.dx, right.dx) > world_state.container.Lx + self.geom_epsilon:
                    continue
                items = []
                y = y0
                index = 0
                while index < 8:
                    template = left if index % 2 == 0 else right
                    if y + template.dy > world_state.container.Ly + self.geom_epsilon:
                        break
                    items.append(CandidatePlacement(
                        sku_id=template.sku_id,
                        position=Point3D(x0, y, 0.0),
                        orientation=template.orientation,
                        context=PlacementContext.MAIN_WALL,
                        weight_kg=template.weight_kg,
                        anchor_category=AnchorCategory.FLOOR_FRONTIER,
                        action_type="MIXED_SKU_WALL",
                    ))
                    y += template.dy
                    index += 1
                if len(items) < 2:
                    continue
                x1 = max(item.x + item.dx for item in items)
                z1 = max(item.z + item.dz for item in items)
                candidate = AggregateCandidate(
                    candidate_id=f"mixed_row_{left.sku_id}_{left.orientation.name}__{right.sku_id}_{right.orientation.name}_{x0:.3f}",
                    sku_id="MIXED", context=PlacementContext.MAIN_WALL,
                    anchor=Point3D(x0, y0, 0.0), bounding_box=AABB(x0, y0, 0.0, x1, y, z1),
                    item_candidates=items,
                    total_volume=sum(item.orientation.volume for item in items),
                    total_weight_kg=sum(item.weight_kg for item in items), item_count=len(items),
                    pattern_type=PatternType.COMPOSITE, anchor_category=AnchorCategory.FLOOR_FRONTIER,
                    candidate_family="MIXED_SKU_WALL",
                )
                if self._cheap_rejection(candidate, world_state, qty_mgr) is None:
                    mixed.append(candidate)
                    if len(mixed) >= limit:
                        return mixed
        return mixed

    def _family(self, candidate, max_width, max_layers, primary_orientation, world_state):
        skus = {item.sku_id for item in candidate.item_candidates}
        orientations = {item.orientation.name for item in candidate.item_candidates}
        if len(skus) > 1:
            return "MIXED_SKU_WALL"
        sku_id = next(iter(skus)); orientation = next(iter(orientations))
        key = (sku_id, orientation)
        if orientation != primary_orientation.get(sku_id):
            return "ALTERNATE_ORIENTATION_WALL"
        if self._layer_count(candidate) < max_layers.get(key, self._layer_count(candidate)):
            return "ALTERNATE_HEIGHT_WALL"
        if candidate.bounding_box.dx < max_width.get(key, candidate.bounding_box.dx) - self.geom_epsilon:
            return "ALTERNATE_WIDTH_WALL"
        residual_height = world_state.container.Lz - candidate.bounding_box.max_z
        if residual_height > 0.05 and candidate.bounding_box.dy >= world_state.container.Ly * 0.7:
            return "RESIDUAL_AWARE_WALL"
        return "HOMOGENEOUS_WALL"

    @staticmethod
    def _layer_count(candidate):
        return len({round(item.z, 6) for item in candidate.item_candidates})

    @staticmethod
    def _aabb_penetrates(a, b, eps=DEFAULT_GEOM_EPSILON):
        return not (
            a.max_x <= b.min_x + eps or b.max_x <= a.min_x + eps
            or a.max_y <= b.min_y + eps or b.max_y <= a.min_y + eps
            or a.max_z <= b.min_z + eps or b.max_z <= a.min_z + eps
        )

    @staticmethod
    def _deterministic_rank(candidate):
        return (-candidate.total_volume, candidate.candidate_signature, candidate.candidate_id)

    @staticmethod
    def _take(bucket, selected, seen, count, limit):
        taken = 0
        for candidate in bucket:
            if candidate.candidate_signature in seen:
                continue
            selected.append(candidate); seen.add(candidate.candidate_signature); taken += 1
            if taken >= count or len(selected) >= limit:
                return
