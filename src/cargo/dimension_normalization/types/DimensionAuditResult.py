from dataclasses import dataclass

@dataclass(frozen=True)
class DimensionAuditResult:
    sku:str;original:tuple;normalized:object;issues:tuple;status:str;source_fields:tuple
    def to_dict(self):return {"sku":self.sku,"original":{"first":self.original[0],"second":self.original[1],"height":self.original[2]},
        **self.normalized.to_dict(),"issues":[x.to_dict() for x in self.issues],"status":self.status,"source_fields":list(self.source_fields)}
