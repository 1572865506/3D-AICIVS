from .types import WallBalanceReport

class WallBalanceAnalyzer:
    def analyze(self,placements,container):
        placements=tuple(placements);left=right=moment_x=total=0.0
        for p in placements:
            weight=p.weight_kg;cy=(p.min_y+p.max_y)/2;cx=(p.min_x+p.max_x)/2
            if cy<=container.Ly/2:left+=weight
            else:right+=weight
            moment_x+=weight*cx;total+=weight
        diff=abs(left-right);score=max(0.0,100.0*(1-diff/max(total,1e-9)));comx=moment_x/max(total,1e-9)
        return WallBalanceReport(round(left,3),round(right,3),round(diff,3),round(score,4),round(comx,6),round(comx/container.Lx,6))
