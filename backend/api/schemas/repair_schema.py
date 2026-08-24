"""Sequence-repair product-schema validation."""

def validate_repair(data,placement_ids):
    if not isinstance(data.get("enabled"),bool):raise ValueError("repair enabled must be boolean")
    for group in data.get("groups",[]):
        if not all(k in group for k in ("id","type","objects","reason")):raise ValueError("repair group invalid")
        if not group["objects"]:raise ValueError("repair group must contain objects")
        if any(pid not in placement_ids for pid in group["objects"]):raise ValueError("repair group references unknown object")
    return True
