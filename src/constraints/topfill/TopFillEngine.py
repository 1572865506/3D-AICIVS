from collections import Counter
from backend.solver_v2.domain.models import Placement,PlacementContext,Point3D
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from .TopCandidateGenerator import TopCandidateGenerator
from .TopFillScore import TopFillScore
from .TopLayerBuilder import TopLayerBuilder
from .TopPlacementValidator import TopPlacementValidator
from .TopSpaceDetector import TopSpaceDetector
from .TopSupportAnalyzer import TopSupportAnalyzer
from .types import TopFillResult

class TopFillEngine:
    def __init__(self):
        self.detector=TopSpaceDetector();self.generator=TopCandidateGenerator();self.support=TopSupportAnalyzer();self.validator=TopPlacementValidator();self.layers=TopLayerBuilder();self.score=TopFillScore()
    def fill(self,container,cargo,existing,walls):
        existing=tuple(existing);regions=self.detector.detect(container,walls,cargo);candidates=self.generator.generate(regions,cargo,existing)
        catalog={s.sku_id:s for s in cargo};used=Counter(p.sku_id for p in existing);placed=[];states=[];rejected=[];scores=[]
        structural_fingerprint=tuple((p.placement_id,p.aabb()) for p in existing)
        by_region={r.id:[] for r in regions}
        for c in candidates:by_region[c.region_id].append(c)
        for region in sorted(regions,key=lambda r:(-r.volume,r.id)):
            choices=sorted(by_region[region.id],key=lambda c:(c.sku_id==region.base_sku,c.orientation.is_flat,c.score,-c.unit_weight,c.sku_id,c.orientation.name),reverse=True)
            committed=False
            for candidate in choices:
                remaining=catalog[candidate.sku_id].quantity.required-used[candidate.sku_id]
                nx=int((region.depth+1e-9)//candidate.orientation.dx);ny=int((region.width+1e-9)//candidate.orientation.dy)
                per_layer=nx*ny
                if per_layer<=0:rejected.append({"region_id":region.id,"sku":candidate.sku_id,"reason":"GEOMETRY_NO_GRID"});continue
                layer_count=min(candidate.max_layers,remaining//per_layer)
                while layer_count>0 and region.max_top_load is not None and per_layer*layer_count*candidate.unit_weight>region.max_top_load+1e-9:layer_count-=1
                if layer_count<=0:rejected.append({"region_id":region.id,"sku":candidate.sku_id,"reason":"INVENTORY_OR_TOP_LOAD"});continue
                offset_x=region.x+(region.depth-nx*candidate.orientation.dx)/2;offset_y=region.y+(region.width-ny*candidate.orientation.dy)/2
                trial=[];trial_states=[];projected=per_layer*layer_count*candidate.unit_weight;valid=True;reason=None
                for layer in range(layer_count):
                    for ix in range(nx):
                        for iy in range(ny):
                            p=Placement(f"top_opt_{region.id}_{candidate.sku_id}_{layer+1}_{ix}_{iy}",f"top_opt_{candidate.sku_id}_{used[candidate.sku_id]+len(trial):04d}",candidate.sku_id,
                                Point3D(round(offset_x+ix*candidate.orientation.dx,6),round(offset_y+iy*candidate.orientation.dy,6),round(region.z+layer*candidate.orientation.dz,6)),
                                candidate.orientation,candidate.unit_weight,PlacementContext.TOP_FILL,len(existing)+len(placed)+len(trial))
                            state=self.support.analyze(region,p.min_x,p.min_y,p.orientation.dx,p.orientation.dy,projected) if layer==0 else self.support.analyze(region,p.min_x,p.min_y,p.orientation.dx,p.orientation.dy,0)
                            ok,reason=self.validator.validate(p,container,existing+tuple(placed)+tuple(trial),state)
                            if not ok:valid=False;break
                            trial.append(p);trial_states.append(state)
                        if not valid:break
                    if not valid:break
                if not valid:rejected.append({"region_id":region.id,"sku":candidate.sku_id,"reason":reason});continue
                placed.extend(trial);states.extend(trial_states);used[candidate.sku_id]+=len(trial);scores.append(candidate.score);committed=True;break
            if not committed and region.classification=="AVAILABLE_TOP":rejected.append({"region_id":region.id,"reason":"NO_LEGAL_TOP_CANDIDATE"})
        validation=IndependentGlobalValidator.validate(container,list(existing)+placed,list(cargo))
        preserved=structural_fingerprint==tuple((p.placement_id,p.aabb()) for p in existing)
        added=sum(p.volume for p in placed);total_region=sum(r.volume for r in regions if r.classification=="AVAILABLE_TOP")
        status="SUCCESS" if validation.is_valid and preserved else "FAILED"
        return TopFillResult(status,regions,candidates,tuple(placed),self.layers.build(placed),tuple(states),tuple(rejected),round(added,6),round(sum(scores)/max(len(scores),1),4),round(max(0,total_region-added),6),preserved,validation)
