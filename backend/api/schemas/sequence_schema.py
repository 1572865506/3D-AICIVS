"""Loading-sequence product-schema validation."""

def validate_sequence(data,placement_ids):
    steps=data.get("steps")
    if not isinstance(steps,list):raise ValueError("sequence steps must be a list")
    expected=1;seen=[]
    for step in steps:
        if step.get("step")!=expected:raise ValueError("sequence steps must be contiguous")
        expected+=1
        for pid in step.get("placements",[]):
            if pid not in placement_ids:raise ValueError(f"sequence references unknown placement: {pid}")
            seen.append(pid)
    if len(seen)!=len(set(seen)):raise ValueError("sequence places an object more than once")
    return True
