"""Runtime response validator; no internal Solver objects cross the boundary."""
from .container_schema import validate_container
from .cargo_schema import validate_cargo
from .sequence_schema import validate_sequence
from .repair_schema import validate_repair
from .scene_schema import validate_scene


class ResponseValidator:
    @classmethod
    def validate_result(cls,result):
        required=("id","container","cargo","walls","sequence","repair","scene","metrics","version")
        missing=[k for k in required if k not in result]
        if missing:raise ValueError(f"LoadingResult missing fields: {missing}")
        validate_container(result["container"])
        validate_cargo({"cargo":result["cargo"]})
        ids={item["id"] for item in result["cargo"]}
        validate_sequence(result["sequence"],ids)
        validate_repair(result["repair"],ids)
        validate_scene(result["scene"],ids)
        if any(pid not in ids for wall in result["walls"] for pid in wall["placements"]):
            raise ValueError("wall references unknown placement")
        return True


__all__=["ResponseValidator","validate_container","validate_cargo","validate_sequence","validate_repair","validate_scene"]
