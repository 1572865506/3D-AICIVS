import re
from collections import Counter
from dataclasses import replace
from backend.solver_v2.domain.models import Point3D
from .types import WallBlueprint

class WallRecompositionSolver:
    @staticmethod
    def wall_id(p):
        m=re.search(r"(transition_wall_|cargo_wall_|top_cargo_wall_|top_region_)(\d{3})",p.placement_id,re.I)
        return (("TRANSITION_WALL_" if m and m.group(1).lower().startswith("transition") else "CARGO_WALL_")+m.group(2)) if m else None
    def rebuild(self,placements,intelligence,strategy):
        groups={};fixed=[]
        for p in placements:
            gid=self.wall_id(p)
            (groups.setdefault(gid,[]) if gid else fixed).append(p)
        meta={}
        for gid,ps in groups.items():
            sku=Counter(p.sku_id for p in ps if p.context.value!="TOP_FILL").most_common(1)[0][0]
            profile=intelligence.profiles[sku];start=min(p.min_x for p in ps);end=max(p.max_x for p in ps)
            meta[gid]={"category":profile.category.value,"weight":sum(p.weight_kg for p in ps),"height":max(p.max_z for p in ps),"start":start,"width":end-start}
        def key(gid):
            m=meta[gid]
            if "DISPLAY" in strategy:return (m["category"]!="DISPLAY",-m["height"],m["start"])
            if "HEAVY" in strategy:return (m["category"]!="HEAVY",-m["weight"],m["start"])
            if "LAYER" in strategy:return (-m["height"],m["category"],m["start"])
            if "HUMAN" in strategy:return ({"HEAVY":0,"STANDARD":1,"DISPLAY":2}.get(m["category"],3),-m["height"],m["start"])
            return (m["start"],)
        rebuilt=[];blueprints=[];wall_map={}
        for prefix in ("CARGO_WALL_","TRANSITION_WALL_"):
            order=sorted((g for g in groups if g.startswith(prefix)),key=key)
            cursor=min((meta[g]["start"] for g in order),default=0.0)
            for index,gid in enumerate(order,1):
                delta=cursor-meta[gid]["start"];new_id=f"RECOMPOSED_{prefix}{index:03d}";wall_map[gid]=new_id
                moved=[]
                for p in groups[gid]:
                    q=replace(p,position=Point3D(round(p.position.x+delta,6),p.position.y,p.position.z));rebuilt.append(q);moved.append(q.placement_id)
                blueprints.append(WallBlueprint(new_id,gid,meta[gid]["category"],tuple(moved),cursor,cursor+meta[gid]["width"]))
                cursor+=meta[gid]["width"]
        rebuilt.extend(fixed);rebuilt.sort(key=lambda p:p.step_index)
        return tuple(rebuilt),tuple(blueprints),wall_map
