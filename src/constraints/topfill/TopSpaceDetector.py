from typing import Iterable,Tuple
from .types import TopRegion

class TopRegionClassifier:
    def classify(self,wall,height):
        if height<.02:return "NO_FILL"
        if not wall.stability.get("stable") or wall.stability.get("supportScore",0)<80:return "WEAK_SUPPORT_TOP"
        return "AVAILABLE_TOP"

class TopSpaceDetector:
    def __init__(self):self.classifier=TopRegionClassifier()
    def detect(self,container,walls:Iterable,catalog)->Tuple[TopRegion,...]:
        catalog={s.sku_id:s for s in catalog};regions=[]
        for index,wall in enumerate(walls,1):
            if not wall.placements:continue
            x0=min(p.min_x for p in wall.placements);x1=max(p.max_x for p in wall.placements)
            y0=min(p.min_y for p in wall.placements);y1=max(p.max_y for p in wall.placements);z=max(p.max_z for p in wall.placements)
            height=container.Lz-z;base_sku=max({p.sku_id for p in wall.placements},key=lambda sid:sum(p.sku_id==sid for p in wall.placements))
            base=catalog[base_sku];limits=[]
            if base.stacking_policy.max_bearing_kg is not None:limits.append(base.stacking_policy.max_bearing_kg*len([p for p in wall.placements if abs(p.max_z-z)<=1e-6]))
            if base.cargo_profile and base.cargo_profile.compression_policy.max_top_load_kg is not None:limits.append(base.cargo_profile.compression_policy.max_top_load_kg*len([p for p in wall.placements if abs(p.max_z-z)<=1e-6]))
            area=(x1-x0)*(y1-y0);kind=self.classifier.classify(wall,height)
            regions.append(TopRegion(f"TOP_REGION_{index:03d}",wall.id,x0,y0,z,y1-y0,x1-x0,height,area*height,area,kind,base_sku,wall.stability.get("supportScore",0),min(limits) if limits else None))
        return tuple(regions)
