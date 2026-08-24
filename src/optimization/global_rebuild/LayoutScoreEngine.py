from collections import Counter
from .types import LayoutScore


class LayoutScoreEngine:
    def score(self,container,placements,cargo,direction_plan,wall_plan,door_coverage):
        catalog={s.sku_id:s for s in cargo};volume=100*sum(p.volume for p in placements)/container.volume
        displays=[p for p in placements if direction_plan and next(r for r in direction_plan.orientation_matrix if r["sku"]==p.sku_id)["category"]=="DISPLAY" and p.context.value!="TOP_FILL"]
        compliant=sum(p.orientation.dx<=p.orientation.dy+1e-9 for p in displays)/max(len(displays),1)*100
        walls=[]
        for gid in wall_plan.wall_order:
            token=gid.lower()
            ps=[p for p in placements if token in p.placement_id.lower()]
            if ps:walls.append(max(p.max_z for p in ps))
        variation=sum(abs(a-b) for a,b in zip(walls,walls[1:]))/max(len(walls)-1,1)
        balance=max(0,100-40*variation/max(container.Lz,1e-9))
        continuity=100.0;transport=92.0 if compliant>=99.9 else compliant
        total=.20*volume+.25*continuity+.20*compliant+.15*door_coverage+.10*transport+.10*balance
        return LayoutScore(round(volume,4),continuity,round(compliant,4),round(door_coverage,4),transport,round(balance,4),round(total,4))
