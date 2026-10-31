from .DimensionNormalizer import DimensionNormalizer

class DimensionAudit:
    def __init__(self):self.normalizer=DimensionNormalizer()
    def audit_manifest(self,items):
        results=[]
        for item in items:
            src=item.get("source",item);name=str(item.get("name",src.get("name",""))).lower();display=any(x in name for x in ("显示器","monitor","display","屏"))
            results.append(self.normalizer.normalize_source(src,str(item.get("sku",src.get("sku","UNKNOWN"))),display))
        return tuple(results)
