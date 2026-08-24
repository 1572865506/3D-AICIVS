from collections import Counter
from .types import RecompositionScore

class RecompositionScoreEngine:
    WEIGHTS={"wall_continuity":.25,"direction_compliance":.20,"transport_safety":.20,"space_efficiency":.15,"door_safety":.10,"layer_balance":.10}
    def score(self,container,placements,blueprints,display,door,layer):
        categories=[b.category for b in blueprints]
        transitions=sum(a!=b for a,b in zip(categories,categories[1:]))
        continuity=max(0.0,100.0-100.0*transitions/max(len(categories)-1,1))
        direction=display["continuity"];transport=92.0 if display["valid"] else direction
        volume=100.0*sum(p.volume for p in placements)/container.volume;door_score=door.get("door_safety_score",door.get("short_edge_forward_pct",0.0))
        layer_score=layer["balance"]
        values=(continuity,direction,transport,volume,door_score,layer_score)
        total=sum(w*v for w,v in zip(self.WEIGHTS.values(),values))
        return RecompositionScore(*(round(v,4) for v in values),round(total,4))
