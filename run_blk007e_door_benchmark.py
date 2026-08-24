"""BLK-007E-1 deterministic Door Safety pre-packing diagnostic runner."""
import json
from collections import Counter

from run_blk003_benchmark import load_dataset
from src.constraints.door import DoorSafetyConfig, DoorSafetyEngine


DATASET = "devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json"


def run():
    container, cargo = load_dataset(DATASET)
    config = DoorSafetyConfig()
    plan = DoorSafetyEngine(config).plan(container, cargo)
    target = {"SKU-02", "SKU-03", "SKU-04", "SKU-14"}
    targeted = {
        sku_id: {
            **plan.classifications[sku_id].to_dict(),
            "orientation_rule": plan.orientation_rules.get(sku_id),
        }
        for sku_id in sorted(target)
    }
    return {
        "block": "BLK-007E-1",
        "status": plan.status,
        "config": {
            "door_zone_depth": plan.zone.depth,
            "thin_ratio_threshold": config.thin_ratio_threshold,
            "max_door_unit_weight_kg": config.max_door_unit_weight_kg,
            "min_wall_coverage": config.min_wall_coverage,
            "max_wall_gap_m": config.max_wall_gap_m,
            "min_support_ratio": config.min_support_ratio,
        },
        "constraints": plan.constraints.to_dict(),
        "wall": plan.wall.to_dict() if plan.wall else None,
        "validation": plan.validation.to_dict() if plan.validation else None,
        "score": plan.safety_score.to_dict() if plan.safety_score else None,
        "targeted_skus": targeted,
        "classification_counts": dict(Counter(r.risk_level for r in plan.classifications.values())),
        "failure": {"reason": plan.reason, "detail": plan.detail},
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
