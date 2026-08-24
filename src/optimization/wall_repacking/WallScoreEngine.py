from .types import WallScore
class WallScoreEngine:
    def score(self,wall,gap_reduction=0.0):
        coverage=sum(min(1,l.coverage) for l in wall.layers)/max(len(wall.layers),1)*100
        heights=[c.height for c in wall.columns];layer=100*(1-(max(heights)-min(heights))/max(max(heights),1e-9)) if heights else 0
        continuity=min(100,coverage+min(10,200*gap_reduction));support=100;direction=100 if wall.display_wall else 95;volume=100;void=max(0,100-coverage);fragmentation=max(0,len(wall.columns)-1-100*gap_reduction)
        final=.25*layer+.25*continuity+.20*support+.15*direction+.15*volume-.03*void-.02*fragmentation
        return WallScore(round(layer,4),round(continuity,4),support,direction,volume,round(void,4),round(fragmentation,4),round(final,4))
