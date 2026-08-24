from collections import Counter
from .LayerOccupancyMap import LayerOccupancyMap
from .LayerScoreEngine import LayerScoreEngine
from .types import LayerState
class LayerAnalyzer:
    def __init__(self,layer_height=.5,resolution=.2):self.layer_height=layer_height;self.maps=LayerOccupancyMap(resolution);self.scores=LayerScoreEngine()
    def analyze(self,container,placements):
        result=[];index=0;z=0.0
        while z<container.Lz-1e-9:
            z1=min(container.Lz,z+self.layer_height);m=self.maps.build(container,placements,z,z1,f"LAYER_{index:02d}")
            occupancy=len(m["occupied"])/max(m["nx"]*m["ny"],1);dist=Counter()
            for p in placements:
                if min(p.max_z,z1)-max(p.min_z,z)>1e-9:dist["FLAT_HORIZONTAL" if p.orientation.is_flat else "SIDE" if p.orientation.is_side else "VERTICAL"]+=1
            void=(container.Lx*container.Ly*(z1-z))*(1-occupancy);score=self.scores.score(occupancy)
            result.append(LayerState(f"LAYER_{index:02d}",(z,z1),round(occupancy,6),round(void,6),dict(dist),len(m["occupied"]),len(m["empty"]),m["gaps"],score["layer_score"]))
            z=z1;index+=1
        return tuple(result)
