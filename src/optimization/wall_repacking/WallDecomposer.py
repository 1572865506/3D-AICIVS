import re
from collections import Counter,defaultdict
from .types import WallColumn,WallLayer,WallStructure
class WallDecomposer:
    def group_id(self,p):
        m=re.search(r"(cargo_wall|transition_wall)_(\d{3})",p.placement_id,re.I)
        return f"{m.group(1).upper()}_{m.group(2)}" if m else None
    def decompose(self,placements,intelligence):
        groups=defaultdict(list)
        for p in placements:
            gid=self.group_id(p)
            if gid:groups[gid].append(p)
        result=[]
        for gid,ps in sorted(groups.items(),key=lambda x:min(p.min_x for p in x[1])):
            by_y=defaultdict(list);by_z=defaultdict(list)
            for p in ps:
                if p.context.value=="TOP_FILL":continue
                by_y[round(p.min_y,6)].append(p);by_z[round(p.min_z,6)].append(p)
            columns=tuple(WallColumn(f"{gid}_COL_{i:02d}",y,tuple(items),max(p.max_z for p in items)) for i,(y,items) in enumerate(sorted(by_y.items()),1))
            width=max((p.max_y for p in ps),default=0)-min((p.min_y for p in ps),default=0)
            layers=tuple(WallLayer(f"{gid}_LAYER_{i:02d}",z,tuple(items),sum(p.orientation.dy for p in items)/max(width,1e-9)) for i,(z,items) in enumerate(sorted(by_z.items()),1))
            mix=Counter(p.sku_id for p in ps if p.context.value!="TOP_FILL")
            display=bool(mix) and all(intelligence.profiles[s].category.value=="DISPLAY" for s in mix)
            result.append(WallStructure(gid,tuple(ps),columns,layers,len(ps),dict(mix),display,(min(p.min_x for p in ps),max(p.max_x for p in ps))))
        return tuple(result)
