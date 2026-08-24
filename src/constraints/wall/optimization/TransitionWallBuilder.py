from .types import TransitionWall

class TransitionWallBuilder:
    def build(self,expansion):
        result=[]
        for spec in expansion.wall_specs:
            continuity=max(0.0,100.0*spec["coverage"]-30.0*(1-spec["coverage"])/2)
            result.append(TransitionWall(spec["id"],spec["placements"],spec["x_range"],spec["sku"],spec["orientation"],round(spec["coverage"],6),round(continuity,4),spec["weight"]))
        return tuple(result)
