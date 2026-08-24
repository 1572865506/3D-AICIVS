from .types import CompressionRule
class CompressionPolicyEngine:
    DEFAULT_LIMITS={"LOW":25.0,"MEDIUM":100.0,"HIGH":None}
    def build(self,classification,fragility,config,source):
        raw=config.get("compression",{});klass=raw.get("class","LOW" if fragility in {"HIGH","CRITICAL"} else "MEDIUM")
        return CompressionRule(raw.get("maxLoadKg",self.DEFAULT_LIMITS[klass]),klass,bool(raw.get("allowAsSupport",fragility not in {"CRITICAL"})),source)
    def validate(self,profile,top_load_kg):
        limit=profile.compressionPolicy.max_load_kg
        if not profile.compressionPolicy.allow_as_support and top_load_kg>0:return False,"SUPPORT_ROLE_FORBIDDEN"
        if limit is not None and top_load_kg>limit:return False,"COMPRESSION_LIMIT_EXCEEDED"
        return True,None
