from collections import Counter
from backend.solver_v2.domain.models import OrientationMode,PlacementContext
from .TopFillScore import TopFillScore
from .TopOrientationOptimizer import TopOrientationOptimizer
from .types import TopCandidate

class TopCandidateGenerator:
    def __init__(self):self.orientation=TopOrientationOptimizer();self.scorer=TopFillScore()
    def generate(self,regions,cargo,existing):
        used=Counter(p.sku_id for p in existing);result=[]
        for region in regions:
            if region.classification!="AVAILABLE_TOP":continue
            for sku in cargo:
                remaining=sku.quantity.required-used[sku.sku_id]
                if remaining<=0:continue
                profile=sku.cargo_profile.top_fill_policy if sku.cargo_profile else None
                for orientation,label,permission in self.orientation.orientations(sku,region):
                    rule=sku.orientation_policy.rule_for(OrientationMode.FLAT if orientation.is_flat else OrientationMode.UPRIGHT,PlacementContext.TOP_FILL)
                    limits=[3,int(region.height//orientation.dz)]
                    if profile and profile.max_layers>0:limits.append(profile.max_layers)
                    if rule and rule.max_top_fill_layers is not None:limits.append(rule.max_top_fill_layers)
                    max_layers=max(0,min(limits));fit=100*(1-(region.height-max_layers*orientation.dz)/max(region.height,1e-9))
                    score=self.scorer.calculate(min(100,100*orientation.volume*remaining/max(region.volume,1e-9)),fit,100,100,100 if orientation.is_flat else 85,0)
                    result.append(TopCandidate(sku.sku_id,region.id,orientation,label,remaining,max_layers,sku.weight_kg,orientation.volume,max(.8,profile.min_support_ratio if profile else .8),permission.__dict__,score))
        return tuple(result)
