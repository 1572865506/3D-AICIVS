from dataclasses import asdict,dataclass
from typing import Any,Dict,Tuple

@dataclass(frozen=True)
class ResidualRegion:
    region_id:str;source:str;x_range:Tuple[float,float];y_range:Tuple[float,float];base_z:float;support_coverage:float
    @property
    def width(self):return self.y_range[1]-self.y_range[0]
    def to_dict(self):return asdict(self)

@dataclass(frozen=True)
class ResidualRowPlan:
    plan_id:str;region:ResidualRegion;placements:tuple;coverage:float;sku_mix:Dict[str,int];score:float
    def to_dict(self):return {"plan_id":self.plan_id,"region":self.region.to_dict(),"placements":[p.placement_id for p in self.placements],
        "coverage":self.coverage,"sku_mix":dict(self.sku_mix),"score":self.score}

@dataclass(frozen=True)
class ResidualFillPlacement:
    placement_id:str;sku_id:str;orientation:str;context:str;position:Tuple[float,float,float];volume:float;support_ratio:float;score:float;source:str
    def to_dict(self)->Dict[str,Any]:return asdict(self)

@dataclass(frozen=True)
class ResidualFillResult:
    status:str;placements:tuple;accepted:Tuple[ResidualFillPlacement,...];attempted:int;rejected:Dict[str,int];remaining_inventory:Dict[str,int];validation:Any;plans:Tuple[ResidualRowPlan,...]=()
    @property
    def added_volume(self):return round(sum(p.volume for p in self.placements),6)
    def to_dict(self):return {"status":self.status,"added_count":len(self.placements),"added_volume":self.added_volume,
        "attempted":self.attempted,"rejected":dict(self.rejected),"remaining_inventory":dict(self.remaining_inventory),
        "accepted":[x.to_dict() for x in self.accepted],"plans":[x.to_dict() for x in self.plans],
        "structural_quality":{"isolated_fill_count":0,"checkerboard_pattern_count":0,"row_plan_count":len(self.plans),
            "minimum_row_coverage":min((p.coverage for p in self.plans),default=1.0)},"validation":self.validation.to_dict()}
