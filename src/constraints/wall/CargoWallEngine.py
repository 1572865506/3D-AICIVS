from dataclasses import dataclass
from typing import Any, Dict, Iterable, Tuple

from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from .WallBuilder import CargoWallBuilder, WallBuildResult
from .WallRegionPlanner import WallRegion, WallRegionPlanner


@dataclass(frozen=True)
class CargoWallPlan:
    status:str
    regions:Tuple[WallRegion,...]
    build:WallBuildResult
    validation:Any
    void_regions:Tuple[Any,...]
    support_links:Tuple[Any,...]

    def to_dict(self)->Dict[str,Any]:
        return {"status":self.status,"regions":[r.to_dict() for r in self.regions],"walls":[w.to_dict() for w in self.build.walls],
                "placement_count":len(self.build.placements),"consumed_inventory":self.build.consumed_inventory,"wall_end_x":self.build.wall_end_x,
                "available_top_regions":list(self.build.available_top_regions),"validation":self.validation.to_dict(),
                "void_regions":[v.to_dict() for v in self.void_regions],"support_link_count":len(self.support_links)}


class CargoWallEngine:
    def __init__(self,builder=None):self.builder=builder or CargoWallBuilder();self.regions=WallRegionPlanner()
    def plan(self,container,cargo:Iterable)->CargoWallPlan:
        cargo=tuple(cargo);build=self.builder.build(container,cargo)
        validation=IndependentGlobalValidator.validate(container,list(build.placements),list(cargo))
        voids=[];links=[]
        for wall in build.walls:
            from .VoidAnalyzer import WallVoidAnalyzer
            from .WallSupportGraph import WallSupportGraph
            voids.extend(WallVoidAnalyzer().analyze(wall.placements));links.extend(WallSupportGraph().build(container,wall.placements)["supportLinks"])
        status="READY" if validation.is_valid and build.walls else "FAILED"
        return CargoWallPlan(status,self.regions.plan(container),build,validation,tuple(voids),tuple(links))
