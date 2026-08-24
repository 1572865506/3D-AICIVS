"""Container product-schema validation."""

REQUIRED=("type","dimension","internal","door","coordinate_system")

def validate_container(data):
    missing=[key for key in REQUIRED if key not in data]
    if missing:raise ValueError(f"container missing fields: {missing}")
    for section in ("dimension","internal"):
        if not all(float(data[section][k])>0 for k in ("length","width","height")):
            raise ValueError(f"container {section} dimensions must be positive")
    return True
