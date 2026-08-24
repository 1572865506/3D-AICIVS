from .types import SupportState
class TopSupportAnalyzer:
    def analyze(self,region,x,y,dx,dy,projected_load):
        ox=max(0,min(x+dx,region.x+region.depth)-max(x,region.x));oy=max(0,min(y+dy,region.y+region.width)-max(y,region.y))
        area=ox*oy;ratio=area/max(dx*dy,1e-9);load_ok=region.max_top_load is None or projected_load<=region.max_top_load+1e-9
        valid=ratio>=.8 and load_ok;risk="LOW" if ratio>=.8 and load_ok else "MEDIUM" if ratio>=.5 and load_ok else "HIGH"
        reason="" if valid else "TOP_LOAD_EXCEEDED" if not load_ok else "INSUFFICIENT_TOP_SUPPORT"
        return SupportState(round(ratio,6),round(area,6),risk,region.max_top_load,round(projected_load,6),valid,reason)
