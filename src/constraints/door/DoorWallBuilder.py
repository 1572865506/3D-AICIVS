from collections import Counter
from math import floor
from typing import Dict, Iterable, List, Optional, Tuple

from backend.solver_v2.domain.models import CargoSKU, ContainerSpec
from .CargoRiskClassifier import CargoRisk
from .DoorOrientationRules import DoorOrientation, DoorOrientationRules, SHORT_EDGE_FORWARD
from .types import DoorWall, DoorWallContinuity, DoorWallPlacement, DoorWallStability, DoorZone


class DoorWallBuilder:
    """Deterministic bounded wall planning; it does not call or modify packing search."""

    def __init__(self, min_coverage: float = 0.75, min_support_ratio: float = 0.70,
                 min_width_coverage: float = 0.0, min_height_coverage: float = 0.0,
                 door_plane_clearance_m: float = None, max_patterns: int = 500000,
                 max_depth_spread_m: float = None, preferred_sku_diversity: int = 1):
        self.min_coverage = float(min_coverage)
        self.min_support_ratio = float(min_support_ratio)
        self.min_width_coverage = float(min_width_coverage)
        self.min_height_coverage = float(min_height_coverage)
        self.door_plane_clearance_m = door_plane_clearance_m
        self.max_patterns = int(max_patterns)
        self.max_depth_spread_m=max_depth_spread_m
        self.preferred_sku_diversity=max(1,int(preferred_sku_diversity))
        self.orientation_rules = DoorOrientationRules()

    def _homogeneous_capacity(self, sku: CargoSKU, orientation: DoorOrientation, container: ContainerSpec) -> Tuple[int, int, int, float]:
        columns = floor((container.Ly + 1e-9) / orientation.wall_width)
        layers = floor((container.Lz + 1e-9) / orientation.height)
        capacity = min(sku.quantity.required, columns * layers)
        full_layers, partial = divmod(capacity, max(columns, 1))
        projected_area = full_layers * columns * orientation.wall_width * orientation.height
        projected_area += partial * orientation.wall_width * orientation.height
        coverage = projected_area / max(container.Ly * container.Lz, 1e-9)
        return columns, layers, capacity, coverage

    def build(self, container: ContainerSpec, zone: DoorZone, cargo: Iterable[CargoSKU], risks: Dict[str, CargoRisk]) -> Optional[DoorWall]:
        variants = []
        for sku in cargo:
            risk = risks[sku.sku_id]
            if not risk.door_candidate:
                continue
            for orientation in self.orientation_rules.orientation_candidates(sku,risk):
                columns,layers,capacity,coverage=self._homogeneous_capacity(sku,orientation,container)
                if self.door_plane_clearance_m is not None:
                    # Opening the doors removes the +X restraint. Limit stack
                    # height so its base-depth / perturbation moment remains >=1.
                    open_safe_layers=floor(orientation.forward_depth/(.15*orientation.height)+1e-9)
                    layers=min(layers,max(0,open_safe_layers))
                if columns<=0 or layers<=0 or capacity<=0 or orientation.forward_depth>zone.depth+1e-9:continue
                variants.append((sku.sku_id,sku,orientation,layers))
        if not variants:
            return None
        if self.door_plane_clearance_m is not None:
            # A short-depth single layer can have good local area but creates the
            # horizontal-looking, door-open-unstable profile observed in the UI.
            # Retain each SKU's tallest self-stable column orientation.
            by_sku={}
            for variant in variants:
                current=by_sku.get(variant[0]);orientation=variant[2];layers=variant[3]
                key=(layers*orientation.height,orientation.forward_depth,-orientation.wall_width,orientation.policy_name)
                if current is None or key>current[0]:by_sku[variant[0]]=(key,variant)
            variants=[value[1] for value in by_sku.values()]

        # Bounded, deterministic column composition.  Each selected column is a
        # self-supported vertical stack; this permits a continuous mixed-SKU wall
        # without any SKU-specific rule or benchmark-specific score.
        variants.sort(key=lambda item:item[0])
        patterns=[];visited=0
        def enumerate_columns(index,remaining_width,counts):
            nonlocal visited
            if visited>=self.max_patterns:return
            visited+=1
            if index==len(variants):
                if not any(counts):return
                used=Counter()
                for i,count in enumerate(counts):
                    if count:used[variants[i][0]]+=count*variants[i][3]
                if any(used[sku_id]>next(v[1].quantity.required for v in variants if v[0]==sku_id) for sku_id in used):return
                depths=[variants[i][2].forward_depth for i,count in enumerate(counts) if count]
                if self.max_depth_spread_m is not None and max(depths)-min(depths)>self.max_depth_spread_m+1e-9:return
                width=sum(count*variants[i][2].wall_width for i,count in enumerate(counts))
                area=sum(count*variants[i][2].wall_width*variants[i][3]*variants[i][2].height for i,count in enumerate(counts))
                height=max((variants[i][3]*variants[i][2].height for i,count in enumerate(counts) if count),default=0.0)
                item_count=sum(count*variants[i][3] for i,count in enumerate(counts))
                diversity=len(used)
                patterns.append((area/max(container.Ly*container.Lz,1e-9),width/container.Ly,height/container.Lz,
                                 container.Ly-width,item_count,diversity,tuple(counts)))
                return
            _,sku,orientation,layers=variants[index]
            inventory_columns=sku.quantity.required//max(layers,1)
            cap=min(floor((remaining_width+1e-9)/orientation.wall_width),inventory_columns)
            for count in range(cap+1):
                enumerate_columns(index+1,remaining_width-count*orientation.wall_width,counts+[count])
        enumerate_columns(0,container.Ly,[])
        if not patterns:return None
        patterns.sort(key=lambda p:(-min(p[5],self.preferred_sku_diversity),-p[0],-p[1],-p[2],p[3],p[4],p[6]))
        _,_,_,_,_,_,selected_counts=patterns[0]
        selected=[(variants[i],count) for i,count in enumerate(selected_counts) if count]
        max_forward=max(v[2].forward_depth for v,count in selected)
        if self.door_plane_clearance_m is None:
            anchor_x=zone.solver_start_x
        else:
            anchor_x=container.Lx-float(self.door_plane_clearance_m)-max_forward
        if anchor_x<zone.solver_start_x-1e-9:return None

        placements: List[DoorWallPlacement] = []
        y_cursor=0.0;column_index=0;sku_indices=Counter()
        for (sku_id,sku,orientation,layers),column_count in selected:
            for _ in range(column_count):
                column_index+=1
                for layer in range(layers):
                    index=sku_indices[sku_id];sku_indices[sku_id]+=1
                    placements.append(DoorWallPlacement(
                        placement_id=f"door_pre_{sku_id}_{index:03d}",sku_id=sku_id,
                        x=round(anchor_x,6),
                        y=round(y_cursor,6),z=round(layer*orientation.height,6),
                        dx=round(orientation.forward_depth,6),dy=round(orientation.wall_width,6),dz=round(orientation.height,6),
                        orientation=orientation.policy_name,layer=layer+1,column=column_index,weight_kg=sku.weight_kg,
                        concrete_orientation=orientation.concrete_orientation,
                    ))
                y_cursor+=orientation.wall_width

        occupied_area = sum(p.dy * p.dz for p in placements)
        coverage = min(1.0, occupied_area / max(container.Ly * container.Lz, 1e-9))
        width_coverage=min(1.0,max((p.max_y for p in placements),default=0.0)/max(container.Ly,1e-9))
        height_coverage=min(1.0,max((p.max_z for p in placements),default=0.0)/max(container.Lz,1e-9))
        gaps=[max(0.0,container.Ly-max((p.max_y for p in placements),default=0.0))]
        distinct_gaps = sorted({round(gap, 6) for gap in gaps if gap > 1e-9})
        max_gap = max(distinct_gaps, default=0.0)
        continuity_score = max(0.0, 100.0 * (1.0 - max_gap / max(container.Ly, 1e-9)))

        upper = [p for p in placements if p.layer > 1]
        supported = 0
        for placement in upper:
            below = [p for p in placements if p.layer == placement.layer - 1 and abs(p.y - placement.y) < 1e-9 and abs(p.dy - placement.dy) < 1e-9]
            supported += int(bool(below))
        support_ratio = supported / len(upper) if upper else 1.0
        neighbor = 0
        for placement in placements:
            peers = [p for p in placements if p.placement_id != placement.placement_id]
            neighbor += int(any((abs(p.max_y-placement.y)<1e-9 or abs(placement.max_y-p.y)<1e-9)
                and min(p.max_z,placement.max_z)-max(p.z,placement.z)>1e-9 for p in peers))
        neighbor_ratio = neighbor / len(placements) if placements else 0.0
        individual_stable = sum(1 for p in placements if p.dz / max(p.dx, 1e-9) <= 3.0)
        individual_ratio = individual_stable / len(placements) if placements else 0.0
        aggregate_stable = (coverage >= self.min_coverage and width_coverage>=self.min_width_coverage
            and height_coverage>=self.min_height_coverage and support_ratio >= self.min_support_ratio and neighbor_ratio >= 0.50)
        stability = DoorWallStability(
            stable=aggregate_stable, risk="LOW" if aggregate_stable else "HIGH",
            individual_stable_ratio=round(individual_ratio, 6), supported_ratio=round(support_ratio, 6),
            neighbor_contact_ratio=round(neighbor_ratio, 6), stack_alignment_ratio=round(support_ratio, 6),
            anchor_required=True,
            issues=(("INDIVIDUAL_THIN_CARGO_REQUIRES_WALL_ANCHOR",) if individual_ratio < 1.0 else ()),
        )
        orientation_set={p.orientation for p in placements}
        return DoorWall(
            wall_id="DOOR_WALL_001", zone="DOOR", placements=tuple(placements),
            orientation=next(iter(orientation_set)) if len(orientation_set)==1 else "MIXED_DOOR_ORIENTATION",
            height=round(max((p.max_z for p in placements), default=0.0), 6),
            coverage=round(coverage, 6),
            continuity=DoorWallContinuity(round(coverage, 6), len(distinct_gaps), round(max_gap, 6), round(continuity_score, 4)),
            stability=stability, sku_mix=dict(Counter(p.sku_id for p in placements)),
            anchor_x=round(anchor_x,6),width_coverage=round(width_coverage,6),height_coverage=round(height_coverage,6),
            door_plane_clearance=round(max((container.Lx-p.max_x for p in placements),default=container.Lx-anchor_x),6),
        )
