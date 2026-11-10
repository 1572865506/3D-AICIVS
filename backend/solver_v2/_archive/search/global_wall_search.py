"""BLK-006A global wall-plan state, objective, and deterministic trace models."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.solver_v2.domain.models import (
    CargoSKU, ContainerSpec, OrientationMode, Placement, PlacementContext,
)
from backend.solver_v2.geometry.aabb import AABB
from backend.solver_v2.orientation.manager import OrientationEngine
from backend.solver_v2.quantity.manager import QuantityManager
from backend.solver_v2.world.state import WorldState


LEGACY_GREEDY = "LEGACY_GREEDY"
GLOBAL_SEARCH = "GLOBAL_SEARCH"


@dataclass(frozen=True)
class WallObjectiveBreakdown:
    main_body_gain: float
    topfill_estimate: float
    residual_quality: float
    compactness: float
    inventory_fit: float
    fragmentation_penalty: float
    unstable_geometry_penalty: float
    door_penalty: float
    final_score: float
    raw_component_value: Dict[str, float] = field(default_factory=dict)
    normalized_component_value: Dict[str, float] = field(default_factory=dict)
    weighted_component_value: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, float]:
        return {
            "main_body_gain": self.main_body_gain,
            "topfill_estimate": self.topfill_estimate,
            "residual_quality": self.residual_quality,
            "compactness": self.compactness,
            "inventory_fit": self.inventory_fit,
            "fragmentation_penalty": self.fragmentation_penalty,
            "unstable_geometry_penalty": self.unstable_geometry_penalty,
            "door_penalty": self.door_penalty,
            "final_score": self.final_score,
            "raw_component_value": self.raw_component_value,
            "normalized_component_value": self.normalized_component_value,
            "weighted_component_value": self.weighted_component_value,
        }


@dataclass(frozen=True)
class WallCandidate:
    candidate_id: str
    sku_id: str
    placements: Tuple[Placement, ...]
    orientation_names: Tuple[str, ...]
    wall_width: float
    layer_count: int
    item_count: int
    volume_gain: float
    source: str = "AGGREGATE_GENERATOR"

    @classmethod
    def from_placements(cls, candidate_id: str, sku_id: str, placements: List[Placement]) -> "WallCandidate":
        min_x = min((p.min_x for p in placements), default=0.0)
        max_x = max((p.max_x for p in placements), default=0.0)
        layers = len({round(p.min_z, 6) for p in placements})
        return cls(
            candidate_id=candidate_id,
            sku_id=sku_id,
            placements=tuple(placements),
            orientation_names=tuple(p.orientation.name for p in placements),
            wall_width=max(0.0, max_x - min_x),
            layer_count=layers,
            item_count=len(placements),
            volume_gain=sum(p.volume for p in placements),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "sku_id": self.sku_id,
            "orientation_names": list(self.orientation_names),
            "wall_width": self.wall_width,
            "layer_count": self.layer_count,
            "item_count": self.item_count,
            "volume_gain": self.volume_gain,
            "source": self.source,
        }


@dataclass
class SearchState:
    state_id: str
    phase: str
    current_x: float
    placed_volume: float
    remaining_inventory: Dict[str, int]
    wall_sequence: List[str]
    wall_structure_sequence: List[Dict[str, Any]]
    placements: List[Placement]
    support_state: Dict[str, Any]
    load_state: Dict[str, Any]
    stability_state: Dict[str, Any]
    residual_space: Dict[str, Any]
    top_fill_regions: List[Dict[str, Any]]
    top_fill_potential: Dict[str, Any]
    door_state: Dict[str, Any]
    hard_constraint_state: Dict[str, Any]
    score_components: Dict[str, float]
    parent_state: Optional[str]
    depth: int

    def clone(self, state_id: Optional[str] = None, parent_state: Optional[str] = None) -> "SearchState":
        """Deep branch clone: no branch shares mutable inventory, lists, or state maps."""
        cloned = copy.deepcopy(self)
        cloned.state_id = state_id or self.state_id
        cloned.parent_state = self.state_id if parent_state is None else parent_state
        return cloned

    def branch(
        self,
        candidate: WallCandidate,
        state_id: str,
        remaining_inventory: Dict[str, int],
        support_state: Dict[str, Any],
        load_state: Dict[str, Any],
        stability_state: Dict[str, Any],
        residual_space: Dict[str, Any],
        top_fill_potential: Dict[str, Any],
        door_state: Dict[str, Any],
        objective: WallObjectiveBreakdown,
    ) -> "SearchState":
        child = self.clone(state_id=state_id)
        child.current_x = max(self.current_x, max((p.max_x for p in candidate.placements), default=self.current_x))
        child.placed_volume = self.placed_volume + candidate.volume_gain
        child.remaining_inventory = copy.deepcopy(remaining_inventory)
        child.wall_sequence.append(candidate.candidate_id)
        child.wall_structure_sequence.append({
            "sku_composition": candidate.sku_id,
            "orientations": list(candidate.orientation_names),
            "wall_width": candidate.wall_width,
            "layer_count": candidate.layer_count,
            "top_surface_base_z": max((p.max_z for p in candidate.placements), default=0.0),
        })
        child.placements.extend(copy.deepcopy(list(candidate.placements)))
        child.support_state = copy.deepcopy(support_state)
        child.load_state = copy.deepcopy(load_state)
        child.stability_state = copy.deepcopy(stability_state)
        child.residual_space = copy.deepcopy(residual_space)
        child.top_fill_regions = copy.deepcopy(top_fill_potential.get("regions", []))
        child.top_fill_potential = copy.deepcopy(top_fill_potential)
        child.door_state = copy.deepcopy(door_state)
        child.hard_constraint_state = {"is_valid": True, "violations": []}
        child.score_components = objective.to_dict()
        child.depth = self.depth + 1
        return child

    def to_dict(self, include_placements: bool = False) -> Dict[str, Any]:
        data = {
            "state_id": self.state_id,
            "phase": self.phase,
            "current_x": self.current_x,
            "placed_volume": self.placed_volume,
            "remaining_inventory": self.remaining_inventory,
            "wall_sequence": self.wall_sequence,
            "wall_structure_sequence": self.wall_structure_sequence,
            "placement_count": len(self.placements),
            "support_state": self.support_state,
            "load_state": self.load_state,
            "stability_state": self.stability_state,
            "residual_space": self.residual_space,
            "top_fill_regions": self.top_fill_regions,
            "top_fill_potential": self.top_fill_potential,
            "door_state": self.door_state,
            "hard_constraint_state": self.hard_constraint_state,
            "score_components": self.score_components,
            "parent_state": self.parent_state,
            "depth": self.depth,
        }
        if include_placements:
            data["placement_ids"] = [p.placement_id for p in self.placements]
        return data

    def fingerprint(self) -> str:
        payload = json.dumps(self.to_dict(include_placements=True), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SearchStateSignature:
    quantized_current_x: int
    remaining_inventory_signature: Tuple[Tuple[str, int], ...]
    wall_frontier_fingerprint: str
    top_surface_fingerprint: str
    door_state_signature: Tuple[Any, ...]
    structural_placement_fingerprint: str

    @classmethod
    def from_state(cls, state: SearchState, quantum_m: float = 0.05) -> "SearchStateSignature":
        frontier = state.wall_structure_sequence[-2:]
        wall_fp = hashlib.sha256(json.dumps(frontier, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        top = {
            "regions": state.top_fill_regions,
            "area": round(float(state.top_fill_potential.get("usable_top_area", 0.0)), 3),
            "height": round(float(state.top_fill_potential.get("usable_top_height", 0.0)), 3),
        }
        top_fp = hashlib.sha256(json.dumps(top, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        geometry = sorted(
            (p.sku_id, p.orientation.name, round(p.min_x / quantum_m), round(p.min_y / quantum_m),
             round(p.min_z / quantum_m), round(p.orientation.dx / quantum_m),
             round(p.orientation.dy / quantum_m), round(p.orientation.dz / quantum_m))
            for p in state.placements
        )
        structural_fp = hashlib.sha256(json.dumps(geometry, separators=(",", ":")).encode("utf-8")).hexdigest()[:20]
        return cls(
            quantized_current_x=round(state.current_x / quantum_m),
            remaining_inventory_signature=tuple(sorted(state.remaining_inventory.items())),
            wall_frontier_fingerprint=wall_fp,
            top_surface_fingerprint=top_fp,
            door_state_signature=(
                round(float(state.door_state.get("safe_x", 0.0)) / quantum_m),
                bool(state.door_state.get("at_risk", False)), state.phase,
            ),
            structural_placement_fingerprint=structural_fp,
        )

    def key(self) -> Tuple[Any, ...]:
        return (
            self.quantized_current_x, self.remaining_inventory_signature,
            self.wall_frontier_fingerprint, self.top_surface_fingerprint,
            self.door_state_signature, self.structural_placement_fingerprint,
        )


def beam_diversity_key(state: SearchState, recent_walls: int = 2) -> Tuple[Any, ...]:
    recent = state.wall_structure_sequence[-recent_walls:]
    return tuple(
        (
            item.get("sku_composition"),
            round(float(item.get("wall_width", 0.0)), 1),
            int(item.get("layer_count", 0)),
            round(float(item.get("top_surface_base_z", 0.0)), 1),
        )
        for item in recent
    )


class FutureTopFillEstimator:
    """Cheap estimator based on the candidate's resulting continuous top footprint."""
    def __init__(self, container: ContainerSpec, catalog: Dict[str, CargoSKU]):
        self.container = container
        self.catalog = catalog
        self.orientation_engine = OrientationEngine()

    def estimate(
        self,
        candidate: WallCandidate,
        remaining_inventory: Dict[str, int],
    ) -> Dict[str, Any]:
        if not candidate.placements:
            return {"regions": [], "usable_top_area": 0.0, "usable_top_height": 0.0,
                    "admitted_sku_count": 0, "packable_volume_estimate": 0.0, "fragmentation": 1.0}
        x0 = min(p.min_x for p in candidate.placements)
        x1 = max(p.max_x for p in candidate.placements)
        y0 = min(p.min_y for p in candidate.placements)
        y1 = max(p.max_y for p in candidate.placements)
        top_zs = [p.max_z for p in candidate.placements]
        base_z = max(top_zs)
        footprint_area = sum(p.orientation.dx * p.orientation.dy for p in candidate.placements if abs(p.max_z - base_z) <= 0.02)
        bbox_area = max((x1 - x0) * (y1 - y0), 1e-9)
        usable_area = min(bbox_area, footprint_area)
        height = max(0.0, self.container.Lz - base_z)
        # A wall exactly at the roof can accumulate a sub-epsilon positive
        # roundoff (for example 1.2000000000000002 at Lz=1.2).  Such a surface
        # has no Top Fill headroom and must not be passed to AABB as min_z>Lz.
        if height <= 1e-6:
            return {
                "regions": [],
                "resulting_top_surface": {"base_z": min(base_z, self.container.Lz), "bbox_area": bbox_area},
                "usable_top_area": 0.0, "usable_top_height": 0.0,
                "admitted_sku_count": 0, "admitted_skus": [],
                "packable_volume_estimate": 0.0, "fragmentation": 0.0,
            }
        base_z = min(base_z, self.container.Lz)
        target = AABB(x0, y0, base_z, x1, y1, self.container.Lz)
        admitted = []
        inventory_volume = 0.0
        for sku in self.catalog.values():
            remaining = remaining_inventory.get(sku.sku_id, 0)
            if remaining <= 0 or sku.stacking_policy.must_be_on_floor:
                continue
            orientations = self.orientation_engine.get_candidate_orientations(
                sku, PlacementContext.TOP_FILL, target_space=target, base_height=base_z,
            )
            if orientations:
                admitted.append(sku.sku_id)
                inventory_volume += remaining * sku.box.volume
        fragmentation = max(0.0, 1.0 - usable_area / bbox_area) + (
            (max(top_zs) - min(top_zs)) / max(self.container.Lz, 1e-9)
        )
        packable = min(usable_area * height, inventory_volume) * max(0.0, 1.0 - min(1.0, fragmentation))
        return {
            "regions": [{"x_range": [x0, x1], "y_range": [y0, y1], "base_z": base_z}],
            "resulting_top_surface": {"base_z": base_z, "bbox_area": bbox_area},
            "usable_top_area": usable_area,
            "usable_top_height": height,
            "admitted_sku_count": len(admitted),
            "admitted_skus": admitted,
            "packable_volume_estimate": packable,
            "fragmentation": fragmentation,
        }


class GlobalWallObjective:
    """Explainable soft objective. Hard-invalid candidates never reach this class."""
    def __init__(self, container: ContainerSpec):
        self.container = container

    def evaluate(
        self,
        parent: SearchState,
        candidate: WallCandidate,
        topfill: Dict[str, Any],
        remaining_before: int,
        door_safe_x: float,
        support_margin: float,
    ) -> WallObjectiveBreakdown:
        bbox_volume = 0.0
        if candidate.placements:
            bbox_volume = (
                (max(p.max_x for p in candidate.placements) - min(p.min_x for p in candidate.placements))
                * (max(p.max_y for p in candidate.placements) - min(p.min_y for p in candidate.placements))
                * max(p.max_z for p in candidate.placements)
            )
        compactness_ratio = candidate.volume_gain / max(bbox_volume, candidate.volume_gain, 1e-9)
        main_gain = candidate.volume_gain * 1000.0
        topfill_score = topfill["packable_volume_estimate"] * 250.0
        residual_quality = topfill["usable_top_area"] * max(0.0, 1.0 - topfill["fragmentation"]) * 25.0
        compactness = compactness_ratio * 80.0
        inventory_fit = min(1.0, candidate.item_count / max(remaining_before, 1)) * 30.0
        fragmentation_penalty = topfill["fragmentation"] * 80.0
        unstable_penalty = max(0.0, 1.0 - support_margin) * 100.0
        candidate_max_x = max((p.max_x for p in candidate.placements), default=parent.current_x)
        door_penalty = max(0.0, candidate_max_x - door_safe_x) * 500.0
        final = (
            main_gain + topfill_score + residual_quality + compactness + inventory_fit
            - fragmentation_penalty - unstable_penalty - door_penalty
        )
        return WallObjectiveBreakdown(
            main_body_gain=main_gain,
            topfill_estimate=topfill_score,
            residual_quality=residual_quality,
            compactness=compactness,
            inventory_fit=inventory_fit,
            fragmentation_penalty=fragmentation_penalty,
            unstable_geometry_penalty=unstable_penalty,
            door_penalty=door_penalty,
            final_score=final,
            raw_component_value={
                "main_body_gain_m3": candidate.volume_gain,
                "topfill_packable_m3": topfill["packable_volume_estimate"],
                "residual_usable_area_m2": topfill["usable_top_area"] * max(0.0, 1.0 - topfill["fragmentation"]),
                "compactness_ratio": compactness_ratio,
                "inventory_fit_ratio": min(1.0, candidate.item_count / max(remaining_before, 1)),
                "fragmentation": topfill["fragmentation"],
                "unstable_geometry": max(0.0, 1.0 - support_margin),
                "door_risk_m": max(0.0, candidate_max_x - door_safe_x),
            },
            normalized_component_value={
                "main_body_gain": candidate.volume_gain / max(self.container.volume, 1e-9),
                "topfill_estimate": topfill["packable_volume_estimate"] / max(self.container.volume, 1e-9),
                "residual_quality": topfill["usable_top_area"] * max(0.0, 1.0 - topfill["fragmentation"]) / max(self.container.Lx * self.container.Ly, 1e-9),
                "compactness": compactness_ratio,
                "inventory_fit": min(1.0, candidate.item_count / max(remaining_before, 1)),
                "fragmentation_penalty": min(1.0, topfill["fragmentation"]),
                "unstable_geometry_penalty": max(0.0, 1.0 - support_margin),
                "door_penalty": max(0.0, candidate_max_x - door_safe_x) / max(self.container.Lx, 1e-9),
            },
            weighted_component_value={
                "main_body_gain": main_gain, "topfill_estimate": topfill_score,
                "residual_quality": residual_quality, "compactness": compactness,
                "inventory_fit": inventory_fit, "fragmentation_penalty": -fragmentation_penalty,
                "unstable_geometry_penalty": -unstable_penalty, "door_penalty": -door_penalty,
            },
        )


def root_search_state(cargo_list: List[CargoSKU]) -> SearchState:
    return SearchState(
        state_id="root", phase="MAIN", current_x=0.0, placed_volume=0.0,
        remaining_inventory={sku.sku_id: sku.quantity.required for sku in cargo_list},
        wall_sequence=[], wall_structure_sequence=[], placements=[], support_state={}, load_state={}, stability_state={},
        residual_space={}, top_fill_regions=[], top_fill_potential={}, door_state={},
        hard_constraint_state={"is_valid": True, "violations": []}, score_components={},
        parent_state=None, depth=0,
    )
