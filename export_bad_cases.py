"""
Runner to execute and collect results for Synthetic Bad Cases WALL-001 through WALL-010.
Outputs: BLK003_BAD_CASE_RESULTS.json
"""
import os
import sys
import json
import unittest

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.test_wall_formation_synthetic import TestWallFormationSynthetic

def run_synthetic_bad_cases_and_export():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestWallFormationSynthetic)
    test_names = [t._testMethodName for t in suite]

    # Map test names to Bad Case IDs and descriptions
    bad_case_map = {
        "test_wall_001_hollow_wall_prevention": {
            "case_id": "WALL-001",
            "name": "Hollow Wall (Internal Cavity) Prevention",
            "description": "Checks that completely enclosed hollow voids are detected and rejected.",
        },
        "test_wall_002_misaligned_layers_prevention": {
            "case_id": "WALL-002",
            "name": "Misaligned Layers Prevention",
            "description": "Checks that step height mismatch between layers generates height penalties.",
        },
        "test_wall_003_broken_rows_prevention": {
            "case_id": "WALL-003",
            "name": "Broken Rows Prevention",
            "description": "Checks that broken transverse rows incur penalties and row continuity is rewarded.",
        },
        "test_wall_004_sawtooth_frontier_prevention": {
            "case_id": "WALL-004",
            "name": "Sawtooth Frontier Prevention",
            "description": "Checks that ragged jagged frontier profiles are detected with low flatness score.",
        },
        "test_wall_005_bridge_void_prevention": {
            "case_id": "WALL-005",
            "name": "Bridge Void / Anti-Bridge Rule",
            "description": "Checks that unsupported internal bridge spans >= 0.30m are blocked.",
        },
        "test_wall_006_small_box_random_insertion_prevention": {
            "case_id": "WALL-006",
            "name": "Small Box Random Insertion Prevention",
            "description": "Checks that small boxes isolated in large spaces are penalized.",
        },
        "test_wall_007_excessive_height_step_prevention": {
            "case_id": "WALL-007",
            "name": "Excessive Height Step Prevention",
            "description": "Checks that large adjacent height drops (> 0.65m) are penalized.",
        },
        "test_wall_008_unfillable_dead_hole_prevention": {
            "case_id": "WALL-008",
            "name": "Unfillable Dead Hole Prevention",
            "description": "Checks that narrow unfillable slivers and dead cavities are classified.",
        },
        "test_wall_009_wall_closure_gate_verification": {
            "case_id": "WALL-009",
            "name": "Wall Closure Gate Verification",
            "description": "Checks WallCloseChecker gate validation on incomplete vs complete walls.",
        },
        "test_wall_010_wall_repair_planner_local_remediation": {
            "case_id": "WALL-010",
            "name": "Wall Repair Planner Local Remediation",
            "description": "Checks WallRepairPlanner selecting matching filler items without global backtrack.",
        },
    }

    results = {}
    runner = unittest.TextTestRunner(verbosity=0)
    for test in suite:
        name = test._testMethodName
        meta = bad_case_map.get(name, {"case_id": name, "name": name, "description": ""})
        
        # Run individual test
        single_suite = unittest.TestSuite([test])
        res = runner.run(single_suite)
        is_pass = res.wasSuccessful()

        results[meta["case_id"]] = {
            "case_id": meta["case_id"],
            "name": meta["name"],
            "test_function": name,
            "description": meta["description"],
            "status": "PASS" if is_pass else "FAIL",
            "errors": [str(e) for _, e in res.errors],
            "failures": [str(f) for _, f in res.failures],
        }

    out_file = os.path.join(PROJECT_ROOT, "BLK003_BAD_CASE_RESULTS.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Exported {len(results)} bad case results to {out_file}")
    all_pass = all(r["status"] == "PASS" for r in results.values())
    print(f"Overall Synthetic Status: {'ALL PASS (10/10)' if all_pass else 'SOME FAILED'}")

if __name__ == "__main__":
    run_synthetic_bad_cases_and_export()
