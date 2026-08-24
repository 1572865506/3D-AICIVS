from .types import LoadingPolicy
class LoadingPriorityEngine:
    def build(self,classification,config,source):
        raw=config.get("priority",{});display=classification.category.value=="DISPLAY"
        return LoadingPolicy(int(raw.get("door",10 if display else 3)),int(raw.get("main",8 if display else 5)),int(raw.get("top",5 if display else 3)),raw.get("reason","CARGO_INTELLIGENCE_POLICY"),source)
