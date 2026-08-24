class FragilityPolicyEngine:
    def infer(self,classification,sku,config):
        if "fragility" in config:return config["fragility"]
        if classification.category.value in {"DISPLAY","FRAGILE"}:return "HIGH"
        if sku.weight_kg>20:return "MEDIUM"
        return "LOW"
    def validate_support_role(self,profile,top_load_kg,lateral_pressure=False):
        if profile.fragility in {"HIGH","CRITICAL"}:
            if lateral_pressure:return False,"FRAGILE_LATERAL_PRESSURE"
            limit=profile.compressionPolicy.max_load_kg
            if limit is not None and top_load_kg>limit:return False,"FRAGILE_COMPRESSION_EXCEEDED"
        return True,None
