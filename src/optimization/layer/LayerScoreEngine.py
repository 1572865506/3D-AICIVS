class LayerScoreEngine:
    def score(self,occupancy,continuity=None,orientation_efficiency=100,void_ratio=None):
        continuity=100*occupancy if continuity is None else continuity;void_ratio=1-occupancy if void_ratio is None else void_ratio
        score=.4*100*occupancy+.3*continuity+.2*orientation_efficiency+.1*100*(1-void_ratio)
        return {"layer_score":round(score,4),"continuity":round(continuity,4),"orientation_efficiency":round(orientation_efficiency,4),"void_ratio":round(void_ratio,6)}
