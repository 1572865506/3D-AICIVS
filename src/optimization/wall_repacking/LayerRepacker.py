from dataclasses import replace
from backend.solver_v2.domain.models import Point3D
class LayerRepacker:
    def repack(self,wall,pattern):
        ps=list(wall.placements);reduction=0.0
        if pattern.family not in {"CONTACT_ALIGNED","LAYER_CONTINUOUS"}:return tuple(ps),reduction
        base=[p for p in ps if p.placement_id.startswith("cargo_wall_") and p.min_z==0]
        if not base:return tuple(ps),reduction
        main_min=min(p.min_y for p in base);main_max=max(p.max_y for p in base);new=[]
        for p in ps:
            y=p.position.y
            if "layer_complete_" in p.placement_id and "_LEFT_" in p.placement_id:
                target=max(0.0,main_min-p.orientation.dy);reduction+=max(0.0,target-y);y=target
            elif "layer_complete_" in p.placement_id and "_RIGHT_" in p.placement_id:
                target=main_max;reduction+=max(0.0,y-target);y=target
            new.append(replace(p,position=Point3D(p.position.x,round(y,6),p.position.z)))
        return tuple(new),round(reduction,6)
