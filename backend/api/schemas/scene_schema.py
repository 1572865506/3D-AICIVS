"""Three.js-ready scene product-schema validation."""

def validate_scene(data,placement_ids):
    objects=data.get("objects")
    if not isinstance(objects,list):raise ValueError("scene objects must be a list")
    for obj in objects:
        if not all(k in obj for k in ("uuid","type","position","scale","rotation","style")):raise ValueError("scene object invalid")
        if obj["type"]=="CARGO" and obj["uuid"] not in placement_ids:raise ValueError("scene references unknown cargo")
        if len(obj["position"])!=3 or len(obj["scale"])!=3 or len(obj["rotation"])!=3:raise ValueError("scene vectors must be length 3")
    return True
