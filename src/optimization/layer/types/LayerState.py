from dataclasses import dataclass
from typing import Any,Dict,Tuple
from .LayerGap import LayerGap
@dataclass(frozen=True)
class LayerState:
    layer_id:str
    height_range:Tuple[float,float]
    occupancy:float
    void_volume:float
    orientation_distribution:Dict[str,int]
    occupied_cells:int
    empty_cells:int
    gap_regions:Tuple[LayerGap,...]
    layer_score:float
    def to_dict(self)->Dict[str,Any]:return {"layer_id":self.layer_id,"height_range":list(self.height_range),"occupancy":self.occupancy,
        "void_volume":self.void_volume,"orientation_distribution":self.orientation_distribution,"occupied_cells":self.occupied_cells,
        "empty_cells":self.empty_cells,"gap_regions":[g.to_dict() for g in self.gap_regions],"layer_score":self.layer_score}
