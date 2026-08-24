from dataclasses import dataclass
from backend.solver_v2.domain.models import OrientationMode,PlacementContext
from backend.solver_v2.orientation.manager import OrientationEngine

@dataclass(frozen=True)
class OrientationPermission:
    baseAllowed:bool
    topAllowed:bool
    compressionAllowed:bool

class TopOrientationOptimizer:
    def __init__(self):self.engine=OrientationEngine()
    def orientations(self,sku,region):
        profile=sku.cargo_profile.top_fill_policy if sku.cargo_profile else None
        if not profile or not profile.enabled or region.z<profile.min_base_height:return ()
        result=[]
        for item in self.engine.get_candidate_orientations(sku,PlacementContext.TOP_FILL,base_height=region.z,min_support_ratio=1.0):
            o=item.orientation;mode=OrientationMode.FLAT if o.is_flat else OrientationMode.SIDE if o.is_side else OrientationMode.UPRIGHT
            declared=mode in profile.allowed_orientations or mode in profile.conditional_orientations
            if not declared:continue
            if o.dx>region.depth+1e-9 or o.dy>region.width+1e-9 or o.dz>region.height+1e-9:continue
            main_rule=sku.orientation_policy.rule_for(mode,PlacementContext.MAIN_WALL)
            permission=OrientationPermission(bool(main_rule),True,True)
            result.append((o,"TOP_HORIZONTAL" if o.is_flat else o.name,permission))
        return tuple(result)
