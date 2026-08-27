"""Structured residual-region packing.

Every commit is a contiguous row plan over a continuous floor or exposed
support region. Opportunistic single-carton insertion is intentionally
forbidden.
"""
from collections import Counter, defaultdict
from dataclasses import replace

from backend.solver_v2.domain.models import Placement, PlacementContext, Point3D
from backend.solver_v2.geometry.aabb import AABB
from backend.solver_v2.orientation.manager import OrientationEngine
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from .types import ResidualFillPlacement, ResidualFillResult, ResidualRegion, ResidualRowPlan


class _SpatialIndex:
    def __init__(self, placements=(), cell=.5):
        self.cell=cell;self.cells=defaultdict(set);self.items={}
        for placement in placements:self.add(placement)
    def _keys(self,aabb):
        from math import floor
        for ix in range(floor(aabb.min_x/self.cell),floor((aabb.max_x-1e-9)/self.cell)+1):
            for iy in range(floor(aabb.min_y/self.cell),floor((aabb.max_y-1e-9)/self.cell)+1):
                for iz in range(floor(aabb.min_z/self.cell),floor((aabb.max_z-1e-9)/self.cell)+1):yield ix,iy,iz
    def add(self,placement):
        self.items[placement.placement_id]=placement
        for key in self._keys(AABB.from_placement(placement)):self.cells[key].add(placement.placement_id)
    def nearby(self,aabb):
        ids=set()
        for key in self._keys(aabb):ids.update(self.cells.get(key,()))
        return tuple(self.items[item_id] for item_id in ids)
    def clone(self):return _SpatialIndex(tuple(self.items.values()),self.cell)


class ResidualSpaceFillingEngine:
    """Pack complete mixed-SKU rows; never commit an isolated filler carton."""
    def __init__(self,max_added=320,max_waves=8,min_row_coverage=.65,min_row_items=1,depth_tolerance=.04,height_tolerance=.04,
                 supported_row_context=PlacementContext.TOP_FILL):
        self.max_added=int(max_added);self.max_waves=int(max_waves);self.min_row_coverage=float(min_row_coverage)
        self.min_row_items=int(min_row_items);self.depth_tolerance=float(depth_tolerance);self.height_tolerance=float(height_tolerance)
        self.supported_row_context=supported_row_context
        self.orientations=OrientationEngine()

    @staticmethod
    def _door_start(container,placements):
        return min((p.min_x for p in placements if p.placement_id.startswith("door_pre_")),default=container.Lx)

    @staticmethod
    def _collides(candidate,index):
        box=AABB.from_placement(candidate)
        return any(box.penetration_volume(AABB.from_placement(other))>1e-12 for other in index.nearby(box))

    @staticmethod
    def _support(candidate,index,catalog):
        if candidate.min_z<=1e-6:return 1.0,()
        box=AABB.from_placement(candidate);area=0.0;lowers=[]
        probe=AABB(box.min_x,box.min_y,max(0,box.min_z-.001),box.max_x,box.max_y,box.min_z+.001)
        for lower in index.nearby(probe):
            if abs(lower.max_z-candidate.min_z)>1e-4:continue
            ox=max(0,min(candidate.max_x,lower.max_x)-max(candidate.min_x,lower.min_x))
            oy=max(0,min(candidate.max_y,lower.max_y)-max(candidate.min_y,lower.min_y))
            if ox>1e-6 and oy>1e-6:area+=ox*oy;lowers.append(lower)
        ratio=min(1.0,area/max(candidate.orientation.dx*candidate.orientation.dy,1e-9))
        for lower in lowers:
            policy=catalog[lower.sku_id].stacking_policy;upper=catalog[candidate.sku_id]
            if not policy.allow_stacking_on_top:return 0.0,tuple(lowers)
            if not policy.stack_on_self and lower.sku_id==candidate.sku_id:return 0.0,tuple(lowers)
            if upper.cargo_class in policy.forbidden_above_categories:return 0.0,tuple(lowers)
            if policy.allowed_above_categories and upper.cargo_class not in policy.allowed_above_categories:return 0.0,tuple(lowers)
        return ratio,tuple(lowers)

    @staticmethod
    def _merge_intervals(intervals):
        merged=[]
        for start,end in sorted(intervals):
            if end-start<=1e-6:continue
            if merged and start<=merged[-1][1]+1e-5:merged[-1]=(merged[-1][0],max(merged[-1][1],end))
            else:merged.append((start,end))
        return tuple(merged)

    @classmethod
    def _subtract_intervals(cls,start,end,blocked):
        free=[];cursor=start
        for left,right in cls._merge_intervals(
            (max(start,left),min(end,right)) for left,right in blocked
        ):
            if left>cursor+1e-6:free.append((cursor,left))
            cursor=max(cursor,right)
        if cursor<end-1e-6:free.append((cursor,end))
        return tuple(free)

    @classmethod
    def _covered_x(cls,intervals):
        return sum(right-left for left,right in cls._merge_intervals(intervals))

    def _top_regions(self,placed,x,orientation,container,door_start,index=None):
        regions=[];dx=orientation.dx
        candidates = index.nearby(AABB(x - 1e-4, 0.0, 0.0, x + dx + 1e-4, container.Ly, container.Lz)) if index is not None else placed
        planes=sorted({round(p.max_z,6) for p in candidates if p.max_z+orientation.dz<=container.Lz+1e-9})
        for z in planes:
            lowers=[p for p in candidates if abs(p.max_z-z)<=1e-5 and p.max_x>x+1e-6 and p.min_x<x+dx-1e-6]
            if not lowers:continue
            y_edges=sorted({0.0,container.Ly}|{max(0.0,min(container.Ly,v)) for p in lowers for v in (p.min_y,p.max_y)})
            supported=[]
            for y1,y2 in zip(y_edges,y_edges[1:]):
                if y2-y1<=1e-6:continue
                mid=(y1+y2)/2
                x_support=[(max(x,p.min_x),min(x+dx,p.max_x)) for p in lowers if p.min_y<mid+1e-9 and p.max_y>mid-1e-9]
                if self._covered_x(x_support)+1e-9>=.98*dx:supported.append((y1,y2))
            blockers=[]
            for p in candidates:
                if p.max_x<=x+1e-6 or p.min_x>=x+dx-1e-6:continue
                if p.max_z<=z+1e-6 or p.min_z>=z+orientation.dz-1e-6:continue
                blockers.append((max(0.0,p.min_y),min(container.Ly,p.max_y)))
            available=[]
            for y1,y2 in self._merge_intervals(supported):
                available.extend(self._subtract_intervals(y1,y2,blockers))
            for number,(y1,y2) in enumerate(self._merge_intervals(available),1):
                if y2-y1+1e-9<orientation.dy*self.min_row_items:continue
                regions.append(ResidualRegion(f"TOP_{x:.3f}_{z:.3f}_{number}","STRUCTURED_TOP_ROW",(x,x+dx),(y1,y2),z,1.0))
        return tuple(regions)

    def _floor_regions(self,placed,x,orientation,container,door_start,index=None):
        if x<0 or x+orientation.dx>door_start+1e-9:return ()
        blocked=[]
        candidates = index.nearby(AABB(x - 1e-4, 0.0, 0.0, x + orientation.dx + 1e-4, container.Ly, orientation.dz + 1e-4)) if index is not None else placed
        for p in candidates:
            if p.max_x<=x+1e-6 or p.min_x>=x+orientation.dx-1e-6:continue
            if p.max_z<=1e-6 or p.min_z>=orientation.dz-1e-6:continue
            blocked.append((max(0.0,p.min_y),min(container.Ly,p.max_y)))
        regions=[]
        for number,(y1,y2) in enumerate(self._subtract_intervals(0.0,container.Ly,blocked),1):
            if y2-y1+1e-9<orientation.dy*self.min_row_items:continue
            regions.append(ResidualRegion(f"FLOOR_{x:.3f}_{number}","STRUCTURED_FLOOR_ROW",(x,x+orientation.dx),(y1,y2),0.0,1.0))
        return tuple(regions)

    def _orientation_specs(self,cargo,context,base_z,intelligence,seed=None):
        specs=[]
        for sku in cargo:
            candidates=self.orientations.get_candidate_orientations(sku,context,base_height=base_z,min_support_ratio=sku.stacking_policy.min_support_ratio)
            for raw in candidates:
                orientation=raw.orientation
                if intelligence and intelligence.profiles[sku.sku_id].category.value=="DISPLAY" and context==PlacementContext.MAIN_WALL and orientation.dx>orientation.dy+1e-9:continue
                if seed and (abs(orientation.dx-seed.dx)>self.depth_tolerance+1e-9 or abs(orientation.dz-seed.dz)>self.height_tolerance+1e-9):continue
                specs.append((sku,orientation))
        return tuple(specs)

    def _build_row(self,region,seed,cargo,catalog,remaining,index,intelligence,serial):
        context=self.supported_row_context if region.source=="STRUCTURED_TOP_ROW" else PlacementContext.MAIN_WALL
        specs=self._orientation_specs(cargo,context,region.base_z,intelligence,seed)
        if not specs:return None,serial
        local_index=index.clone();local_used=Counter();placements=[];support_values=[];y=region.y_range[0]
        while True:
            residual=region.y_range[1]-y;choices=[]
            for sku,orientation in specs:
                if local_used[sku.sku_id]>=remaining[sku.sku_id] or orientation.dy>residual+1e-9:continue
                serial+=1
                placement=Placement(f"structured_residual_{serial:05d}",f"structured_{sku.sku_id}_{serial:05d}",sku.sku_id,
                    Point3D(round(region.x_range[0],6),round(y,6),round(region.base_z,6)),orientation,sku.weight_kg,context,0)
                if placement.max_x>region.x_range[1]+self.depth_tolerance+1e-9 or placement.max_y>region.y_range[1]+1e-9:continue
                if self._collides(placement,local_index):continue
                ratio,_=self._support(placement,local_index,catalog);required=max(.70,sku.stacking_policy.min_support_ratio)
                if ratio+1e-9<required:continue
                leftover=residual-orientation.dy
                choices.append((-leftover,placement.volume,ratio,sku.sku_id,orientation.name,placement))
            if not choices:break
            *_,placement=max(choices,key=lambda row:row[:-1])
            placements.append(placement);local_index.add(placement);local_used[placement.sku_id]+=1
            ratio,_=self._support(placement,index,catalog);support_values.append(ratio);y=round(placement.max_y,6)
        coverage=(y-region.y_range[0])/max(region.width,1e-9)
        if len(placements)<self.min_row_items or coverage+1e-9<self.min_row_coverage:return None,serial
        score=sum(p.volume for p in placements)*(2+min(support_values,default=1))+coverage+.05*len(local_used)
        return ResidualRowPlan("ROW_"+region.region_id,region,tuple(placements),round(coverage,6),dict(local_used),round(score,6)),serial

    def _generate_plans(self,container,cargo,catalog,placed,remaining,index,intelligence,door_start,serial,rejected):
        plans=[];seen=set();attempted=0
        x_anchors=sorted({0.0}|{round(v,6) for p in placed for v in (p.min_x,p.max_x) if v<door_start-1e-6})
        for sku,seed in self._orientation_specs(cargo,PlacementContext.MAIN_WALL,0.0,intelligence):
            if remaining[sku.sku_id]<=0:continue
            for x in x_anchors:
                for region in self._floor_regions(placed,x,seed,container,door_start,index=index):
                    key=(region.source,round(x,4),round(region.y_range[0],4),round(region.y_range[1],4),round(seed.dx,4),round(seed.dz,4))
                    if key in seen:continue
                    seen.add(key);attempted+=1
                    plan,serial=self._build_row(region,seed,cargo,catalog,remaining,index,intelligence,serial)
                    if plan:plans.append(plan)
                    else:rejected["INCOMPLETE_FLOOR_ROW"]+=1
        for sku,seed in self._orientation_specs(cargo,self.supported_row_context,0.0,intelligence):
            if remaining[sku.sku_id]<=0:continue
            top_x=sorted({round(v,6) for p in placed for v in (p.min_x,p.max_x-seed.dx) if v>=-1e-9 and v+seed.dx<=door_start+1e-9})
            for x in top_x:
                for region in self._top_regions(placed,x,seed,container,door_start,index=index):
                    key=(region.source,round(x,4),round(region.base_z,4),round(region.y_range[0],4),round(region.y_range[1],4),round(seed.dx,4),round(seed.dz,4))
                    if key in seen:continue
                    seen.add(key);attempted+=1
                    plan,serial=self._build_row(region,seed,cargo,catalog,remaining,index,intelligence,serial)
                    if plan:plans.append(plan)
                    else:rejected["INCOMPLETE_TOP_ROW"]+=1
        plans.sort(key=lambda plan:(-plan.score,-plan.coverage,plan.plan_id))
        return plans,serial,attempted

    def fill(self,container,cargo,existing,intelligence=None,allowed_x_ranges=None):
        cargo=tuple(cargo);catalog={sku.sku_id:sku for sku in cargo};placed=list(existing);index=_SpatialIndex(placed)
        used=Counter(p.sku_id for p in placed);door_start=self._door_start(container,placed);accepted=[];selected=[];rejected=Counter();serial=0;attempted=0
        for _wave in range(self.max_waves):
            remaining={sku.sku_id:max(0,sku.quantity.required-used[sku.sku_id]) for sku in cargo}
            plans,serial,generated=self._generate_plans(container,cargo,catalog,placed,remaining,index,intelligence,door_start,serial,rejected);attempted+=generated
            if allowed_x_ranges:
                plans=[plan for plan in plans if any(
                    plan.region.x_range[0]>=left-1e-6 and plan.region.x_range[1]<=right+1e-6
                    for left,right in allowed_x_ranges)]
            committed=False;batch=[];batch_plans=[];wave_used=Counter();wave_index=index.clone()
            for plan in plans:
                if len(accepted)+len(batch)+len(plan.placements)>self.max_added:rejected["PLAN_BUDGET"]+=1;continue
                if any(used[sku_id]+wave_used[sku_id]+count>catalog[sku_id].quantity.required for sku_id,count in plan.sku_mix.items()):rejected["INVENTORY"]+=1;continue
                trial=[]
                for p in plan.placements:
                    offset=sum(x.sku_id==p.sku_id for x in trial)
                    trial.append(replace(p,instance_id=f"structured_{p.sku_id}_{used[p.sku_id]+wave_used[p.sku_id]+offset:04d}",step_index=len(placed)+len(batch)+len(trial)))
                # Plans in one wave are generated against the same immutable
                # snapshot.  Commit every mutually compatible complete row,
                # but cheaply discard alternatives that overlap a row selected
                # in this wave before invoking the full validator once.
                if any(self._collides(p,wave_index) for p in trial):
                    rejected["PLAN_CONFLICT"]+=1;continue
                batch.extend(trial);batch_plans.append(replace(plan,placements=tuple(trial)))
                for p in trial:wave_index.add(p);wave_used[p.sku_id]+=1
                if len(accepted)+len(batch)>=self.max_added:break
            if batch:
                validation=IndependentGlobalValidator.validate(container,placed+batch,list(cargo))
                if validation.is_valid:
                    committed=True
                    for committed_plan in batch_plans:
                        selected.append(committed_plan)
                        for p in committed_plan.placements:
                            ratio,_=self._support(p,index,catalog);placed.append(p);index.add(p);used[p.sku_id]+=1
                            accepted.append(ResidualFillPlacement(p.placement_id,p.sku_id,p.orientation.name,p.context.value,(p.min_x,p.min_y,p.min_z),p.volume,round(ratio,6),committed_plan.score,committed_plan.region.source))
                else:
                    # Conservative fallback isolates the offending plan.  Every
                    # surviving row still receives a full global validation.
                    rejected["ATOMIC_BATCH_VALIDATION"]+=1
                    for committed_plan in batch_plans:
                        trial=list(committed_plan.placements)
                        if any(self._collides(p,index) for p in trial):
                            rejected["PLAN_CONFLICT"]+=1;continue
                        validation=IndependentGlobalValidator.validate(container,placed+trial,list(cargo))
                        if not validation.is_valid:
                            rejected["ATOMIC_GLOBAL_VALIDATION"]+=1;continue
                        committed=True;selected.append(committed_plan)
                        for p in trial:
                            ratio,_=self._support(p,index,catalog);placed.append(p);index.add(p);used[p.sku_id]+=1
                            accepted.append(ResidualFillPlacement(p.placement_id,p.sku_id,p.orientation.name,p.context.value,(p.min_x,p.min_y,p.min_z),p.volume,round(ratio,6),committed_plan.score,committed_plan.region.source))
            if not committed or len(accepted)>=self.max_added:break
        validation=IndependentGlobalValidator.validate(container,placed,list(cargo))
        if not validation.is_valid:
            validation=IndependentGlobalValidator.validate(container,list(existing),list(cargo));rejected["FINAL_ATOMIC_ROLLBACK"]+=1
            placed=list(existing);accepted=[];selected=[]
        added_ids={item.placement_id for item in accepted};added=tuple(p for p in placed if p.placement_id in added_ids)
        remaining={sku.sku_id:max(0,sku.quantity.required-Counter(p.sku_id for p in placed)[sku.sku_id]) for sku in cargo}
        return ResidualFillResult("SUCCESS" if validation.is_valid else "FAILED",added,tuple(accepted),attempted,dict(rejected),remaining,validation,tuple(selected))
