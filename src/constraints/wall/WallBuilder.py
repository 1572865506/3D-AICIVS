from collections import Counter
from dataclasses import dataclass
from math import floor
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.solver_v2.domain.models import CargoSKU, ContainerSpec, Orientation3D, PackingRole, Placement, PlacementContext, Point3D
from backend.solver_v2.orientation.manager import OrientationEngine
from .ThinCargoWallRule import ThinCargoWallRule
from .VoidAnalyzer import WallVoidAnalyzer
from .WallContinuityAnalyzer import WallContinuityAnalyzer
from .WallLayerBuilder import WallLayerBuilder
from .WallScore import CargoWallScore
from .WallSupportGraph import WallSupportGraph
from .types import CargoWall, WallSegment


@dataclass(frozen=True)
class WallBuildResult:
    walls: Tuple[CargoWall, ...]
    placements: Tuple[Placement, ...]
    consumed_inventory: Dict[str,int]
    wall_end_x: float
    available_top_regions: Tuple[Dict, ...]


class CargoWallBuilder:
    def __init__(self, residual_depth=0.6,mixed_depth_tolerance=.04,min_wall_surface_coverage=0.0):
        self.residual_depth=residual_depth;self.mixed_depth_tolerance=float(mixed_depth_tolerance);self.min_wall_surface_coverage=float(min_wall_surface_coverage);self.orientations=OrientationEngine()
        self.continuity=WallContinuityAnalyzer();self.support=WallSupportGraph()
        self.voids=WallVoidAnalyzer();self.scorer=CargoWallScore();self.layers=WallLayerBuilder()
        self.thin_rule=ThinCargoWallRule()

    @staticmethod
    def _max_layers(sku:CargoSKU,orientation:Orientation3D,container:ContainerSpec):
        layers=floor((container.Lz+1e-9)/orientation.dz)
        if sku.stacking_policy.must_be_on_floor or not sku.stacking_policy.stack_on_self or not sku.stacking_policy.allow_stacking_on_top:layers=min(layers,1)
        if sku.stacking_policy.max_stack_layers is not None:layers=min(layers,sku.stacking_policy.max_stack_layers)
        bearing=sku.stacking_policy.max_bearing_kg
        if bearing is not None and sku.weight_kg>0:layers=min(layers,int(bearing//sku.weight_kg)+1)
        if sku.cargo_profile and sku.cargo_profile.compression_policy.max_top_load_kg is not None and sku.weight_kg>0:
            layers=min(layers,int(sku.cargo_profile.compression_policy.max_top_load_kg//sku.weight_kg)+1)
        return max(0,layers)

    def _variant(self, sku:CargoSKU, remaining:int, container:ContainerSpec):
        variants=[]
        for candidate in self.orientations.get_candidate_orientations(sku,PlacementContext.MAIN_WALL):
            o=candidate.orientation;cols=floor((container.Ly+1e-9)/o.dy);layers=self._max_layers(sku,o,container)
            actual_layers=min(layers,remaining//max(cols,1))
            if cols<=0 or actual_layers<=0:continue
            count=cols*actual_layers;coverage=cols*o.dy*actual_layers*o.dz/(container.Ly*container.Lz)
            variants.append((coverage,count,-o.dx,o.name,o,cols,actual_layers))
        return max(variants,default=None)

    def _column_specs(self,catalog,remaining,container):
        specs=[]
        for sku in catalog:
            if remaining[sku.sku_id]<=0:continue
            for candidate in self.orientations.get_candidate_orientations(sku,PlacementContext.MAIN_WALL):
                o=candidate.orientation;layers=min(self._max_layers(sku,o,container),remaining[sku.sku_id])
                if layers>0 and o.dy<=container.Ly+1e-9:
                    specs.append({"sku":sku,"orientation":o,"max_layers":layers})
        return specs

    def _mixed_plan(self,catalog,remaining,container,cursor,max_end):
        specs=self._column_specs(catalog,remaining,container);plans=[]
        for seed in specs:
            if cursor+seed["orientation"].dx>max_end+1e-9:continue
            compatible=[s for s in specs if abs(s["orientation"].dx-seed["orientation"].dx)<=self.mixed_depth_tolerance+1e-9]
            # Keep the strongest column orientation per SKU inside this depth band.
            best_by_sku={}
            for spec in compatible:
                o=spec["orientation"];key=(spec["max_layers"]*o.dz,o.dy*spec["max_layers"]*o.dz,-abs(o.dx-seed["orientation"].dx),o.name)
                if spec["sku"].sku_id not in best_by_sku or key>best_by_sku[spec["sku"].sku_id][0]:best_by_sku[spec["sku"].sku_id]=(key,spec)
            compatible=[x[1] for x in best_by_sku.values()]
            available=dict(remaining);columns=[];used_width=0.0;target_height=None
            while True:
                choices=[];used_skus={c["sku"].sku_id for c in columns}
                for spec in compatible:
                    sku_id=spec["sku"].sku_id;o=spec["orientation"];layers=min(spec["max_layers"],available[sku_id])
                    if target_height is not None:
                        nearest=max(1,int(round(target_height/o.dz)))
                        layers=min(layers,nearest)
                    if layers<=0 or used_width+o.dy>container.Ly+1e-9:continue
                    diversity=int(bool(used_skus) and sku_id not in used_skus and len(used_skus)<2)
                    stack_height=layers*o.dz;residual=container.Ly-used_width-o.dy
                    height_fit=(stack_height/container.Lz if target_height is None else -abs(stack_height-target_height)/container.Lz)
                    choices.append((height_fit,diversity,o.dy*stack_height,-residual,-o.dx,sku_id,o.name,spec,layers))
                if not choices:break
                *_,spec,layers=max(choices,key=lambda choice:choice[:7])
                columns.append({**spec,"layers":layers,"y":used_width})
                used_width+=spec["orientation"].dy;available[spec["sku"].sku_id]-=layers
                if target_height is None:target_height=layers*spec["orientation"].dz
            if not columns:continue
            depth=max(c["orientation"].dx for c in columns);area=sum(c["orientation"].dy*c["layers"]*c["orientation"].dz for c in columns)
            coverage=area/max(container.Ly*container.Lz,1e-9);diversity=len({c["sku"].sku_id for c in columns});spread=max(c["orientation"].dx for c in columns)-min(c["orientation"].dx for c in columns)
            plans.append((coverage+(0.02 if diversity>=2 else 0.0),coverage,diversity>=2,used_width/container.Ly,-spread,-depth,tuple(columns)))
        return max(plans,key=lambda plan:plan[:6],default=None)

    def build(self,container:ContainerSpec,cargo:Iterable[CargoSKU])->WallBuildResult:
        catalog=tuple(s for s in cargo if PackingRole.MAIN_WALL in s.packing_roles)
        remaining={s.sku_id:s.quantity.required for s in catalog};walls=[];placements=[];consumed=Counter();cursor=0.0
        max_end=max(0.0,container.Lx-self.residual_depth)
        while True:
            plan=self._mixed_plan(catalog,remaining,container,cursor,max_end)
            if not plan:break
            _,coverage,_,_,_,_,columns=plan
            # Tail inventory that cannot form a meaningful wall belongs to the
            # residual solver, not a one-carton "wall" island.
            if coverage+1e-9<self.min_wall_surface_coverage:break
            depth=max(c["orientation"].dx for c in columns)
            wall_index=len(walls)+1;wall_id=f"CARGO_WALL_{wall_index:03d}";wall_ps=[]
            local_index=0;local_sku_counts=Counter()
            for col,column in enumerate(columns):
                sku=column["sku"];orientation=column["orientation"]
                for layer in range(column["layers"]):
                    idx=local_index;local_index+=1
                    sku_local_index=local_sku_counts[sku.sku_id];local_sku_counts[sku.sku_id]+=1
                    wall_ps.append(Placement(
                        placement_id=f"cargo_wall_{wall_index:03d}_{sku.sku_id}_{idx:03d}",instance_id=f"wall_{sku.sku_id}_{consumed[sku.sku_id]+sku_local_index:04d}",sku_id=sku.sku_id,
                        position=Point3D(round(cursor,6),round(column["y"],6),round(layer*orientation.dz,6)),
                        orientation=orientation,weight_kg=sku.weight_kg,context=PlacementContext.MAIN_WALL,step_index=len(placements)+idx,
                    ))
            continuity=self.continuity.analyze(wall_ps,container.Ly);support=self.support.build(container,wall_ps);voids=self.voids.analyze(wall_ps)
            thin_checks=[self.thin_rule.validate(column["sku"],container,support) for column in columns]
            thin_ok=all(x[0] for x in thin_checks);thin_reason=";".join(sorted({x[1] for x in thin_checks if x[1]}))
            void_volume=sum(v.volume for v in voids);slab_volume=depth*container.Ly*max(p.max_z for p in wall_ps)
            void_ratio=void_volume/max(slab_volume,1e-9)
            score=self.scorer.calculate(continuity["continuityScore"],support["supportScore"],100.0,100.0,void_ratio,0 if thin_ok else 50)
            segment=WallSegment(f"{wall_id}_SEG_01",(cursor,cursor+depth),(0.0,max(p.max_y for p in wall_ps)),(0.0,max(p.max_z for p in wall_ps)),tuple(p.placement_id for p in wall_ps))
            role="TRANSITION_WALL" if cursor+depth>container.Lx-1.2 else "CARGO_WALL"
            wall=CargoWall(wall_id,f"LOGICAL_WALL_{int(cursor//1.2)+1:03d}",self.layers.build(wall_ps,container.Ly),(segment,),tuple(wall_ps),
                max(p.max_y for p in wall_ps),max(p.max_z for p in wall_ps),depth,continuity,
                {"stable":thin_ok and not support["weakArea"],"supportScore":support["supportScore"],"isolatedCargo":list(support["isolatedCargo"]),"weakArea":list(support["weakArea"]),"reason":thin_reason},
                round(void_ratio,6),score["wallScore"],score["risk"],role)
            walls.append(wall);placements.extend(wall_ps)
            for sku_id,count in Counter(p.sku_id for p in wall_ps).items():remaining[sku_id]-=count;consumed[sku_id]+=count
            cursor=round(cursor+depth,6)
        tops=tuple({"region_id":f"TOP_{w.id}","wall_id":w.id,"x_range":[w.x_start,w.x_end],"y_range":[0,w.width],"base_z":w.height,
                    "available_height":round(container.Lz-w.height,6),"support_area":round(w.depth*w.width,6),"flatness":1.0}
                   for w in walls if w.height<container.Lz-1e-9)
        return WallBuildResult(tuple(walls),tuple(placements),dict(consumed),cursor,tops)
