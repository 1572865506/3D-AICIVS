import re
from collections import Counter
from dataclasses import replace
from backend.solver_v2.domain.models import Point3D
from .types import PlacementPlan,WallPlan


class WallReconstructionEngine:
    def _group_id(self,p):
        transition=re.search(r"transition_wall_(\d{3})",p.placement_id,re.I)
        if transition:return f"TRANSITION_WALL_{transition.group(1)}"
        cargo=re.search(r"(?:cargo_wall_|TOP_CARGO_WALL_|TOP_REGION_|CARGO_WALL_)(\d{3})",p.placement_id,re.I)
        return f"CARGO_WALL_{cargo.group(1)}" if cargo else None
    def reconstruct(self,placements,strategy,intelligence):
        groups={};fixed=[]
        for p in placements:
            gid=self._group_id(p)
            (groups.setdefault(gid,[]) if gid else fixed).append(p)
        meta={}
        for gid,ps in groups.items():
            skus=Counter(p.sku_id for p in ps if p.context.value!="TOP_FILL");sku=skus.most_common(1)[0][0]
            profile=intelligence.profiles[sku];height=max(p.max_z for p in ps);start=min(p.min_x for p in ps);end=max(p.max_x for p in ps)
            meta[gid]={"sku":sku,"category":profile.category.value,"fragility":profile.fragility,"height":height,"start":start,"width":end-start}
        cargo_order=sorted((g for g in groups if g.startswith("CARGO_")),key=lambda g:meta[g]["start"])
        transition_order=sorted((g for g in groups if g.startswith("TRANSITION_")),key=lambda g:meta[g]["start"])
        family=strategy.family
        def arrange(order):
            if family=="DISPLAY_FIRST":return sorted(order,key=lambda g:(meta[g]["category"]!="DISPLAY",meta[g]["start"]))
            if family=="HEAVY_FIRST":return sorted(order,key=lambda g:(meta[g]["category"]!="HEAVY",meta[g]["start"]))
            if family=="LAYER_BALANCED":return sorted(order,key=lambda g:(-meta[g]["height"],meta[g]["start"]))
            if family=="DOOR_SAFE":return sorted(order,key=lambda g:(meta[g]["category"]=="DISPLAY" or meta[g]["fragility"]=="HIGH",meta[g]["start"]))
            return order
        cargo_order=arrange(cargo_order);transition_order=arrange(transition_order);order=cargo_order+transition_order;rebuilt=[]
        for segment in (cargo_order,transition_order):
            cursor=min((meta[g]["start"] for g in segment),default=0)
            for gid in segment:
                delta=cursor-meta[gid]["start"]
                for p in groups[gid]:rebuilt.append(replace(p,position=Point3D(round(p.position.x+delta,6),p.position.y,p.position.z)))
                cursor+=meta[gid]["width"]
        # Re-instantiate the safe Door Wall as part of every complete candidate;
        # geometry remains governed by the frozen Door Safety Engine.
        rebuilt.extend(replace(p) if p.placement_id.startswith("door_pre_") else p for p in fixed)
        rebuilt.sort(key=lambda p:p.step_index)
        return WallPlan(tuple(order),len(order),family!="INCUMBENT"),PlacementPlan(tuple(rebuilt),tuple(order))
