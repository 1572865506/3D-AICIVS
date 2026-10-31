from .types import OrientationRule
class OrientationPolicyEngine:
    def build(self,classification,config,source):
        raw=config.get("orientation",{})
        if raw:
            base=tuple(raw.get("base",["VERTICAL"]));top=tuple(raw.get("top",base));door=tuple(raw.get("door",base));forbidden=tuple(raw.get("forbidden",["SIDE"]))
        elif classification.category.value=="DISPLAY":base=("VERTICAL",);top=("VERTICAL",);door=("VERTICAL",);forbidden=("SIDE","HORIZONTAL","FLAT")
        else:base=("VERTICAL",);top=("VERTICAL",);door=("VERTICAL",);forbidden=("SIDE",)
        return OrientationRule(base,top,door,forbidden,source)
    def is_allowed(self,profile,orientation,context):
        allowed=profile.orientationPolicy.top if context=="TOP_FILL" else profile.orientationPolicy.door if context=="DOOR_ZONE" else profile.orientationPolicy.base
        normalized="FLAT_HORIZONTAL" if orientation in {"FLAT","HORIZONTAL","TOP_HORIZONTAL","FLAT_XZ","FLAT_ZX"} else "SIDE" if orientation.startswith("SIDE") else "VERTICAL"
        return normalized in allowed and normalized not in profile.orientationPolicy.forbidden
