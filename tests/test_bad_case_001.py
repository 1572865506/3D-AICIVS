"""
BAD_CASE_001 Regression Entry
Evaluates wall hollows, fragmentation, and geometric overlap on BAD_CASE_001.
"""

import os
import sys
import json
from typing import Dict, Any

# Ensure project root in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.validation.independent_validator import IndependentSolutionValidator

def run_bad_case_001_legacy_audit() -> Dict[str, Any]:
    """Audit legacy solver output against BAD_CASE_001 failure modes."""
    from tests.test_benchmark_14sku import run_legacy_14sku_benchmark

    baseline = run_legacy_14sku_benchmark()
    
    # Audit for BAD_CASE_001 criteria
    audit_result = {
        "case_name": "BAD_CASE_001",
        "description": "Wall Hollow + Collision / Dead Space Fragmentation",
        "tested_solver": baseline["solver"],
        "placed_count": baseline["placed_count"],
        "unplaced_count": baseline["unplaced_count"],
        "overlap_pair_count": baseline["overlap_pair_count"],
        "penetration_volume": baseline["penetration_volume"],
        "out_of_bounds_count": baseline["out_of_bounds_count"],
        "notes": [
            "Legacy solver leaves 496 cartons of SKU-14 unplaced due to rigid column slicing and tail-assembly fragmentation.",
            "Visual artifacts show dead space and wall hollows in tail sections.",
            "V2 Acceptance requires overlap_pair_count == 0, penetration_volume == 0, and enclosed cavity detection/mitigation."
        ]
    }
    return audit_result

def test_bad_case_001():
    report = run_bad_case_001_legacy_audit()
    print("=== BAD_CASE_001 Regression Audit Report ===")
    print(json.dumps(report, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    test_bad_case_001()
