"""Cargo visualization product-schema validation."""

def validate_cargo(data):
    cargo=data.get("cargo")
    if not isinstance(cargo,list):raise ValueError("cargo must be a list")
    ids=set()
    for item in cargo:
        missing=[k for k in ("id","sku","position","size","productDimensions","occupiedDimensions","axisDefinition","rotation","material","loading","stability") if k not in item]
        if missing:raise ValueError(f"cargo item missing fields: {missing}")
        if item["id"] in ids:raise ValueError(f"duplicate cargo id: {item['id']}")
        ids.add(item["id"])
        if not all(k in item["position"] for k in ("x","y","z")):raise ValueError("cargo position invalid")
        if not all(float(item["size"][k])>0 for k in ("w","d","h")):raise ValueError("cargo size invalid")
        if not all(float(item["productDimensions"][k])>0 for k in ("length","width","height")):raise ValueError("cargo productDimensions invalid")
        if not all(float(item["occupiedDimensions"][k])>0 for k in ("width","depth","height")):raise ValueError("cargo occupiedDimensions invalid")
        if not all(item["axisDefinition"].get(k) in {"X","Y","Z"} for k in ("lengthAxis","widthAxis","heightAxis")):raise ValueError("cargo axisDefinition invalid")
    return True
