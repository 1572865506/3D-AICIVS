"""
Benchmark 14 SKU Test Runner
Runs the 14 SKU / 1845 Cartons benchmark (cleanroom case 001) against Solver baseline.
"""

import os
import sys
import json
import time
from typing import Dict, Any

# Ensure project root in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from backend.solver_v2.validation.independent_validator import IndependentSolutionValidator

BENCHMARK_PATH = os.path.join(PROJECT_ROOT, "devkit", "cleanroom_solver_v2_devkit", "benchmarks", "40hq_cleanroom_case_001.json")

def load_benchmark_case() -> Dict[str, Any]:
    with open(BENCHMARK_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def run_legacy_14sku_benchmark() -> Dict[str, Any]:
    """Execute 14 SKU Benchmark on Legacy Solver to record baseline."""
    from backend.industrial_packer import IndustrialSmartContainerPacker

    case_data = load_benchmark_case()
    container_seed = case_data["containerSeed"]["inner"]
    container_spec = {
        "usable": {
            "L": container_seed["x"],
            "W": container_seed["y"],
            "H": container_seed["z"]
        },
        "maxPayloadTons": 26.5
    }
    cargo_list = []
    for item in case_data["cargo"]:
        src = item["source"]
        cargo_list.append({
            "sku": item["sku"],
            "name": item["name"],
            "w": src["w"],
            "d": src["d"],
            "h": src["h"],
            "weight": src["weight"],
            "quantity": src["quantity"],
            "requirement": src.get("requirement", "")
        })

    packer = IndustrialSmartContainerPacker(container_spec)
    t0 = time.perf_counter()
    result = packer.pack(cargo_list)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    placements = result.get("placedBoxes", [])
    # Legacy packer coordinates: x=L, y=H, z=W
    container_dim = (container_seed["x"], container_seed["z"], container_seed["y"])
    val_report = IndependentSolutionValidator.validate(container_dim, placements)

    unplaced_count = result.get("totalUnplacedCount", 0)

    return {
        "solver": "Legacy V1.7",
        "case_id": case_data["caseId"],
        "requested_cartons": case_data["requestedCartons"],
        "placed_count": len(placements),
        "unplaced_count": unplaced_count,
        "runtime_ms": elapsed_ms,
        "volume_utilization_pct": val_report["volume_utilization_pct"],
        "is_valid": val_report["is_valid"],
        "overlap_pair_count": val_report["overlap_pair_count"],
        "penetration_volume": val_report["penetration_volume"],
        "out_of_bounds_count": val_report["out_of_bounds_count"],
        "summary": result.get("summary", {})
    }

def test_benchmark_14sku():
    report = run_legacy_14sku_benchmark()
    print("=== 14 SKU Benchmark Report (Legacy Baseline) ===")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    assert report["is_valid"] is True or report["placed_count"] > 0

if __name__ == "__main__":
    test_benchmark_14sku()
