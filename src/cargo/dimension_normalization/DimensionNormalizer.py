from .AxisMapper import AxisMapper
from .DimensionInference import DimensionInference
from .DimensionValidator import DimensionValidator
from .types import DimensionAuditResult,NormalizedDimension

class DimensionNormalizer:
    def __init__(self):self.mapper=AxisMapper();self.inference=DimensionInference();self.validator=DimensionValidator()
    def normalize_values(self,first,second,height,is_display=False,sku="",source_fields=("length","width","height")):
        length,width,height,axes=self.mapper.map(first,second,height);thickness=self.inference.thickness_axis(length,width,height)
        normalized=NormalizedDimension(length,width,height,axes,thickness);issues=self.validator.validate((float(first),float(second),float(height)),normalized,is_display)
        status="FIXED_AXIS_MAPPING" if any(x.code=="AXIS_SWAP_WARNING" for x in issues) else "NORMALIZED"
        return DimensionAuditResult(sku,(float(first),float(second),float(height)),normalized,issues,status,tuple(source_fields))
    def normalize_source(self,source,sku="",is_display=False):
        if "dimensions" in source:
            d=source["dimensions"];return self.normalize_values(d["length"],d["width"],d["height"],is_display,sku,("length","width","height"))
        first=source.get("w",source.get("x",.1));second=source.get("d",source.get("y",.1));height=source.get("h",source.get("z",.1))
        return self.normalize_values(first,second,height,is_display,sku,("w" if "w" in source else "x","d" if "d" in source else "y","h" if "h" in source else "z"))
    def normalize_sku(self,sku,is_display=None):
        display=is_display if is_display is not None else any(token in sku.name.lower() for token in ("显示器","monitor","display","屏"))
        return self.normalize_values(sku.box.x,sku.box.y,sku.box.z,display,sku.sku_id,("box.x","box.y","box.z")).normalized
