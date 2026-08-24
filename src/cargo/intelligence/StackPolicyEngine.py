from .types import StackRule
class StackPolicyEngine:
    def build(self,classification,config,source):
        raw=config.get("stack",{});top=int(raw.get("topMaxLayers",3 if classification.category.value=="DISPLAY" else 1))
        return StackRule(raw.get("baseMaxLayers"),top,bool(raw.get("topAllowed",classification.category.value=="DISPLAY")),bool(raw.get("stackOnSelf",True)),source)
    def validate(self,profile,current_layers,additional_layers=1,context="TOP_FILL"):
        limit=profile.stackPolicy.top_max_layers if context=="TOP_FILL" else profile.stackPolicy.base_max_layers
        if context=="TOP_FILL" and not profile.stackPolicy.top_allowed:return False,0,"TOP_STACK_FORBIDDEN"
        if limit is not None and current_layers+additional_layers>limit:return False,max(0,limit-current_layers),"MAX_STACK_LAYERS"
        return True,None if limit is None else max(0,limit-current_layers-additional_layers),None
