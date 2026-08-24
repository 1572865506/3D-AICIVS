from dataclasses import replace
from .WallOptimizationScore import WallOptimizationScore
from ..WallContinuityAnalyzer import WallContinuityAnalyzer
from ..WallLayerBuilder import WallLayerBuilder
from ..WallSupportGraph import WallSupportGraph

class WallContinuityOptimizer:
    """Side-aligns walls, preserving one contiguous residual filler region."""
    def optimize(self,walls,container):
        result=[]
        for wall in walls:
            used=max((p.max_y for p in wall.placements),default=0)-min((p.min_y for p in wall.placements),default=0)
            current_min=min((p.min_y for p in wall.placements),default=0);target=0.0;shift=target-current_min
            ps=tuple(replace(p,position=replace(p.position,y=round(p.position.y+shift,6))) for p in wall.placements)
            continuity=WallContinuityAnalyzer().analyze(ps,container.Ly);support=WallSupportGraph().build(container,ps)
            segments=tuple(replace(s,y_range=(min(p.min_y for p in ps),max(p.max_y for p in ps))) for s in wall.segments)
            result.append(replace(wall,placements=ps,layers=WallLayerBuilder().build(ps,container.Ly),segments=segments,
                continuity=continuity,stability={**wall.stability,"supportScore":support["supportScore"],"isolatedCargo":list(support["isolatedCargo"])},
                wall_score=min(100.0,wall.wall_score+(continuity["continuityScore"]-wall.continuity["continuityScore"])*.35)))
        return tuple(result)
