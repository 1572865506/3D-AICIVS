"""Reproduce the persisted frontend production manifest through the backend chain."""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.search.config import SearchConfig, SearchProfile
from backend.solver_v2.search.engine import HierarchicalSearchSolver
from src.optimization.residual_filling import ResidualSpaceFillingEngine
from src.solver.integration.door import DoorIntegratedSolver


LINE = re.compile(
    r"\{ sku: '([^']+)', name: '([^']+)', w: ([\d.]+), d: ([\d.]+), "
    r"h: ([\d.]+), weight: ([\d.]+), quantity: (\d+), requirement: '([^']*)'"
)


def load_manifest():
    source = Path("index.html").read_text(encoding="utf-8")
    block = source.split("const PRODUCTION_CLEANED_MANIFEST = [", 1)[1].split("];", 1)[0]
    manifest = []
    for sku, name, w, d, h, weight, quantity, requirement in LINE.findall(block):
        item = {
            "sku": sku, "name": name, "w": float(w), "d": float(d), "h": float(h),
            "weight": float(weight), "quantity": int(quantity), "requirement": requirement,
        }
        if sku == "SKU-10":
            item["maxStackLayers"] = 3
        manifest.append(item)
    return manifest


def main():
    container = InputAdapter.parse_container({
        "code": "40HQ", "usable": {"L": 12.032, "W": 2.352, "H": 2.698},
        "maxPayloadKg": 26500, "doorZoneLengthM": 1.2, "rearZoneLengthM": 1.0,
    })
    cargo = InputAdapter.parse_cargo_list(load_manifest())
    solver = (DoorIntegratedSolver(
        HierarchicalSearchSolver(SearchConfig.for_profile(SearchProfile.BALANCED, 20, 42)),
        enable_cargo_walls=True, enable_wall_optimization=True,
    ).with_direction_strategy().with_layer_optimization().with_topfill_optimization()
     .with_global_rebuild("REBUILD").with_cargo_recomposition().with_wall_interface_repair()
     .with_dimension_corrected_rebuild().with_wall_internal_repack().with_residual_filling())
    solver.residual_adapter.engine = ResidualSpaceFillingEngine()
    solution = solver.solve(container, cargo)
    residual = solver.last_residual_prepared.result
    print({
        "placements": len(solution.placements), "utilization": solution.volume_utilization_pct,
        "valid": solution.validation_result.is_valid, "residual_added": len(residual.placements),
        "residual_volume": residual.added_volume, "rows": len(residual.plans),
        "attempted": residual.attempted, "rejected": residual.rejected,
        "remaining": residual.remaining_inventory,
        "residual_skus": dict(Counter(p.sku_id for p in residual.placements)),
    })
    for plan in residual.plans:
        print(plan.region.source, plan.region.x_range, plan.region.y_range,
              plan.region.base_z, plan.coverage, plan.sku_mix)


if __name__ == "__main__":
    main()
