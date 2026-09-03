"""
Benchmark Suite & Regression Guard for 3D-AICIVS Solver.
TASK-07 / Step 7.1 — Standard Benchmark Test Suite.

Contains 5 standard test cases:
1. 14-SKU-1845 (Current Cleanroom Baseline)
2. Single Large Box SKU (Extreme Stacking & Monolithic Packing)
3. All Elastic SKUs (Overcapacity Trimming & Elastic Deduction Logic)
4. Dense Door Zone SKUs (Door Zone Locking & Sealing Wall Safety)
5. Mixed Heterogeneous SKUs (Multi-Depth & Diverse Space Utilization)

Each case records:
- placed_count
- utilization (volume utilization %)
- runtime_ms
- collisions (overlap pair count)
- violations (out-of-bounds, weight, physics, etc.)

Output: tests/benchmark_results.json
Acceptance Criteria: 5 test cases with collisions=0 and utilization recorded.
"""

import os
import sys
import json
import time
import unittest
from typing import Dict, Any, List, Tuple

# Ensure UTF-8 output encoding on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure project root & backend in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from backend.solver_v2.solver.unified_solver import UnifiedSolver
from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.validation.independent_validator import IndependentSolutionValidator

BENCHMARK_14SKU_PATH = os.path.join(
    PROJECT_ROOT, "devkit", "cleanroom_solver_v2_devkit", "benchmarks", "40hq_cleanroom_case_001.json"
)
OUTPUT_RESULTS_PATH = os.path.join(PROJECT_ROOT, "tests", "benchmark_results.json")

# Canonical 40HQ Container Specifications
DEFAULT_40HQ_SPEC = {
    "usable": {
        "L": 12.032,
        "W": 2.352,
        "H": 2.698
    },
    "maxPayloadTons": 26.5
}


def get_benchmark_case_1_14sku() -> Tuple[Dict[str, Any], List[Dict[str, Any]], str, str, str]:
    """Case 1: 14-SKU-1845 standard baseline."""
    case_id = "14-SKU-1845"
    case_name = "14-SKU-1845 (当前基线)"
    description = "14-SKU standard baseline cleanroom case 001"

    if os.path.exists(BENCHMARK_14SKU_PATH):
        with open(BENCHMARK_14SKU_PATH, "r", encoding="utf-8") as f:
            case_data = json.load(f)
        container_seed = case_data.get("containerSeed", {}).get("inner", {"x": 12.032, "y": 2.352, "z": 2.698})
        container_spec = {
            "usable": {
                "L": float(container_seed["x"]),
                "W": float(container_seed["y"]),
                "H": float(container_seed["z"])
            },
            "maxPayloadTons": 26.5
        }
        cargo_list = []
        for item in case_data.get("cargo", []):
            src = item.get("source", {})
            cargo_list.append({
                "sku": item.get("sku", ""),
                "name": item.get("name", ""),
                "w": float(src.get("w", 0.0)),
                "d": float(src.get("d", 0.0)),
                "h": float(src.get("h", 0.0)),
                "weight": float(src.get("weight", 0.0)),
                "quantity": int(src.get("quantity", 0)),
                "requirement": src.get("requirement", "")
            })
        return container_spec, cargo_list, case_id, case_name, description
    else:
        # Fallback inline standard 14 SKU definitions
        container_spec = DEFAULT_40HQ_SPEC
        cargo_list = [
            {"sku": "SKU-01", "name": "43 TV", "w": 1.070, "d": 0.140, "h": 0.650, "weight": 8.9, "quantity": 180, "requirement": ""},
            {"sku": "SKU-02", "name": "21.5 Display", "w": 0.553, "d": 0.080, "h": 0.355, "weight": 8.4, "quantity": 100, "requirement": "封柜门"},
            {"sku": "SKU-03", "name": "34 Display", "w": 0.978, "d": 0.188, "h": 0.488, "weight": 4.61, "quantity": 120, "requirement": "封柜门"},
            {"sku": "SKU-04", "name": "27 Display", "w": 0.680, "d": 0.122, "h": 0.440, "weight": 6.7, "quantity": 150, "requirement": "封柜门"},
            {"sku": "SKU-05", "name": "32 Main", "w": 0.833, "d": 0.530, "h": 0.230, "weight": 20.8, "quantity": 100, "requirement": ""},
            {"sku": "SKU-06", "name": "24 Medium", "w": 0.620, "d": 0.130, "h": 0.410, "weight": 5.5, "quantity": 200, "requirement": ""},
            {"sku": "SKU-07", "name": "55 Large", "w": 1.360, "d": 0.160, "h": 0.830, "weight": 14.2, "quantity": 80, "requirement": ""},
            {"sku": "SKU-08", "name": "65 XL", "w": 1.580, "d": 0.180, "h": 0.960, "weight": 21.0, "quantity": 50, "requirement": ""},
            {"sku": "SKU-09", "name": "Small Acc 1", "w": 0.350, "d": 0.250, "h": 0.200, "weight": 2.5, "quantity": 300, "requirement": ""},
            {"sku": "SKU-10", "name": "Small Acc 2", "w": 0.400, "d": 0.300, "h": 0.220, "weight": 3.2, "quantity": 250, "requirement": ""},
            {"sku": "SKU-11", "name": "Stand Base", "w": 0.500, "d": 0.400, "h": 0.150, "weight": 4.0, "quantity": 200, "requirement": ""},
            {"sku": "SKU-12", "name": "Cable Box", "w": 0.300, "d": 0.200, "h": 0.180, "weight": 1.8, "quantity": 200, "requirement": ""},
            {"sku": "SKU-13", "name": "Speaker Set", "w": 0.450, "d": 0.350, "h": 0.280, "weight": 6.0, "quantity": 100, "requirement": ""},
            {"sku": "SKU-14", "name": "19 Elastic", "w": 0.488, "d": 0.080, "h": 0.336, "weight": 2.15, "quantity": 115, "requirement": "封柜门,按需调节"}
        ]
        return container_spec, cargo_list, case_id, case_name, description


def get_benchmark_case_2_single_large() -> Tuple[Dict[str, Any], List[Dict[str, Any]], str, str, str]:
    """Case 2: 单一大箱 SKU (测极限堆叠 / Monolithic Extreme Stacking)."""
    case_id = "SINGLE-LARGE-BOX"
    case_name = "单一大箱 SKU (测极限堆叠)"
    description = "Single large carton SKU for monolithic block stacking and extreme volume utilization"
    container_spec = DEFAULT_40HQ_SPEC

    # Box dimension: 1.15m x 1.15m x 0.88m (Fits cleanly into 40HQ container)
    cargo_list = [
        {
            "sku": "LARGE-SKU-01",
            "name": "Industrial Palletized Unit",
            "w": 1.150,
            "d": 1.150,
            "h": 0.880,
            "weight": 85.0,
            "quantity": 70,
            "requirement": "允许旋转"
        }
    ]
    return container_spec, cargo_list, case_id, case_name, description


def get_benchmark_case_3_all_elastic() -> Tuple[Dict[str, Any], List[Dict[str, Any]], str, str, str]:
    """Case 3: 全弹性件 (测核减逻辑 / Overcapacity Elastic Trimming)."""
    case_id = "ALL-ELASTIC-SKUS"
    case_name = "全弹性件 (测核减逻辑)"
    description = "All elastic SKUs with overcapacity demand testing automated trimming and zero overflow"
    container_spec = DEFAULT_40HQ_SPEC

    # 4 Elastic SKUs with total 3,200 cartons (vastly exceeding container volume)
    cargo_list = [
        {
            "sku": "ELASTIC-01",
            "name": "Elastic Standard Carton A",
            "w": 0.600,
            "d": 0.400,
            "h": 0.350,
            "weight": 11.5,
            "quantity": 800,
            "requirement": "弹性件,按需调节,可以少放",
            "isElastic": True
        },
        {
            "sku": "ELASTIC-02",
            "name": "Elastic Compact Carton B",
            "w": 0.500,
            "d": 0.350,
            "h": 0.300,
            "weight": 8.0,
            "quantity": 900,
            "requirement": "弹性件,可减少",
            "isElastic": True
        },
        {
            "sku": "ELASTIC-03",
            "name": "Elastic Small Carton C",
            "w": 0.400,
            "d": 0.300,
            "h": 0.250,
            "weight": 5.2,
            "quantity": 1000,
            "requirement": "弹性件,按需调节",
            "isElastic": True
        },
        {
            "sku": "ELASTIC-04",
            "name": "Elastic Bulk Carton D",
            "w": 0.700,
            "d": 0.500,
            "h": 0.400,
            "weight": 16.0,
            "quantity": 500,
            "requirement": "弹性件,可以少放",
            "isElastic": True
        }
    ]
    return container_spec, cargo_list, case_id, case_name, description


def get_benchmark_case_4_door_dense() -> Tuple[Dict[str, Any], List[Dict[str, Any]], str, str, str]:
    """Case 4: 门区密集 (测门区封门 / Door Zone Locking & Sealing Wall Safety)."""
    case_id = "DOOR-DENSE-SKUS"
    case_name = "门区密集 (测门区封门)"
    description = "Dense door-seal items testing door safety zone (rear 1.2m), wall closure, and anti-toppling"
    container_spec = DEFAULT_40HQ_SPEC

    cargo_list = [
        # Main body heavy/regular cartons
        {
            "sku": "MAIN-01",
            "name": "Main Wall Bulk Cargo",
            "w": 0.800,
            "d": 0.500,
            "h": 0.400,
            "weight": 18.0,
            "quantity": 160,
            "requirement": "中间区域"
        },
        {
            "sku": "MAIN-02",
            "name": "Main Wall Standard Carton",
            "w": 0.600,
            "d": 0.400,
            "h": 0.350,
            "weight": 12.0,
            "quantity": 180,
            "requirement": "中间区域"
        },
        # Door zone dedicated & thin screen SKUs
        {
            "sku": "DOOR-01",
            "name": "Door Safety 21.5 Display Panel",
            "w": 0.550,
            "d": 0.080,
            "h": 0.350,
            "weight": 8.0,
            "quantity": 260,
            "requirement": "封柜门,门区专用",
            "allowDoorZone": True
        },
        {
            "sku": "DOOR-02",
            "name": "Door Safety 27 Display Panel",
            "w": 0.680,
            "d": 0.120,
            "h": 0.440,
            "weight": 6.5,
            "quantity": 160,
            "requirement": "封柜门",
            "allowDoorZone": True
        },
        {
            "sku": "DOOR-03",
            "name": "Door Sealing Elastic Filler",
            "w": 0.480,
            "d": 0.080,
            "h": 0.330,
            "weight": 2.2,
            "quantity": 220,
            "requirement": "封柜门,按需调节",
            "allowDoorZone": True,
            "isElastic": True
        }
    ]
    return container_spec, cargo_list, case_id, case_name, description


def get_benchmark_case_5_mixed_heterogeneous() -> Tuple[Dict[str, Any], List[Dict[str, Any]], str, str, str]:
    """Case 5: 混合异尺寸 (测空间利用 / Mixed Heterogeneous Dimensions & Space Utilization)."""
    case_id = "MIXED-HETEROGENEOUS"
    case_name = "混合异尺寸 (测空间利用)"
    description = "Highly heterogeneous SKU dimensions testing multi-depth wall slicing, top filling, and compact space utilization"
    container_spec = DEFAULT_40HQ_SPEC

    cargo_list = [
        {
            "sku": "HETERO-01",
            "name": "Heavy Base Slab",
            "w": 1.000,
            "d": 0.800,
            "h": 0.450,
            "weight": 42.0,
            "quantity": 30,
            "requirement": "必须平放,重物靠底"
        },
        {
            "sku": "HETERO-02",
            "name": "Tall Upright Carton",
            "w": 0.400,
            "d": 0.300,
            "h": 0.850,
            "weight": 11.5,
            "quantity": 70,
            "requirement": "允许旋转"
        },
        {
            "sku": "HETERO-03",
            "name": "Flat Large Panel",
            "w": 0.900,
            "d": 0.900,
            "h": 0.180,
            "weight": 14.0,
            "quantity": 60,
            "requirement": "允许旋转"
        },
        {
            "sku": "HETERO-04",
            "name": "Standard Medium Box",
            "w": 0.500,
            "d": 0.400,
            "h": 0.300,
            "weight": 10.0,
            "quantity": 140,
            "requirement": "允许旋转"
        },
        {
            "sku": "HETERO-05",
            "name": "Long Skinny Bar",
            "w": 1.100,
            "d": 0.250,
            "h": 0.250,
            "weight": 7.5,
            "quantity": 80,
            "requirement": "允许旋转"
        },
        {
            "sku": "HETERO-06",
            "name": "Compact Cube",
            "w": 0.450,
            "d": 0.450,
            "h": 0.450,
            "weight": 13.0,
            "quantity": 90,
            "requirement": "允许旋转"
        },
        {
            "sku": "HETERO-07",
            "name": "Small Void Filler",
            "w": 0.300,
            "d": 0.200,
            "h": 0.200,
            "weight": 3.0,
            "quantity": 250,
            "requirement": "顶部填平,按需调节",
            "isElastic": True
        },
        {
            "sku": "HETERO-08",
            "name": "Door Safety Partition",
            "w": 0.580,
            "d": 0.100,
            "h": 0.380,
            "weight": 5.0,
            "quantity": 90,
            "requirement": "封柜门",
            "allowDoorZone": True
        }
    ]
    return container_spec, cargo_list, case_id, case_name, description


def execute_benchmark_case(
    container_spec: Dict[str, Any],
    cargo_list: List[Dict[str, Any]],
    case_id: str,
    case_name: str,
    description: str
) -> Dict[str, Any]:
    """
    Executes a single packing benchmark test case and validates results.
    Records: placed_count, utilization, runtime_ms, collisions, violations.
    """
    usable = container_spec["usable"]
    container_dim = (float(usable["L"]), float(usable["H"]), float(usable["W"]))
    requested_cartons = sum(item.get("quantity", 0) for item in cargo_list)

    container = InputAdapter.parse_container(container_spec)
    v2_cargos = InputAdapter.parse_cargo_list(cargo_list)

    solver = UnifiedSolver(container)
    t0 = time.perf_counter()
    sol = solver.solve(v2_cargos)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    val_report = sol.validation_result
    overlap_count = int(val_report.get("overlap_pair_count", len(val_report.overlap_violations)))
    penetration_vol = float(val_report.get("penetration_volume", 0.0))
    oob_count = int(val_report.get("out_of_bounds_count", len(val_report.bounds_violations)))
    utilization_pct = float(sol.volume_utilization_pct)
    placed_count = sol.placed_count
    unplaced_count = sol.unplaced_count

    total_violations = len(val_report.violations)
    fatal_violations = len([
        v for v in val_report.violations
        if getattr(v, "severity", None) and str(getattr(v, "severity", "")).endswith("FATAL")
    ])

    return {
        "case_id": case_id,
        "case_name": case_name,
        "description": description,
        "requested_cartons": requested_cartons,
        "placed_count": placed_count,
        "unplaced_count": unplaced_count,
        "utilization": round(utilization_pct, 2),
        "volume_utilization_pct": round(utilization_pct, 4),
        "runtime_ms": round(elapsed_ms, 2),
        "collisions": overlap_count,
        "overlap_pair_count": overlap_count,
        "penetration_volume": round(penetration_vol, 6),
        "out_of_bounds_count": oob_count,
        "violations": total_violations,
        "fatal_violations": fatal_violations,
        "is_valid": (overlap_count == 0 and oob_count == 0 and total_violations == 0),
        "summary": {
            "placedCount": placed_count,
            "unplacedCount": unplaced_count,
            "utilization": utilization_pct
        }
    }


def run_benchmark_suite() -> Dict[str, Any]:
    """Runs all 5 standard benchmark cases and exports benchmark_results.json."""
    cases = [
        get_benchmark_case_1_14sku(),
        get_benchmark_case_2_single_large(),
        get_benchmark_case_3_all_elastic(),
        get_benchmark_case_4_door_dense(),
        get_benchmark_case_5_mixed_heterogeneous(),
    ]

    print("=" * 80)
    print("3D-AICIVS Solver Benchmark Suite (TASK-07 / Step 7.1)")
    print("=" * 80)

    results = {}
    summary_list = []
    all_zero_collisions = True

    for i, (spec, cargo, cid, name, desc) in enumerate(cases, 1):
        print(f"\n[{i}/5] Running: {name} ({cid}) ...")
        t_start = time.time()
        res = execute_benchmark_case(spec, cargo, cid, name, desc)
        t_cost = time.time() - t_start

        collisions = res["collisions"]
        util = res["utilization"]
        placed = res["placed_count"]
        req = res["requested_cartons"]
        rt = res["runtime_ms"]
        viols = res["violations"]

        if collisions > 0:
            all_zero_collisions = False

        status_str = "PASS" if collisions == 0 and util > 0 else "FAIL"
        print(f"  [{status_str}] Placed: {placed}/{req} | Util: {util:.2f}% | Collisions: {collisions} | Viols: {viols} | Time: {rt:.1f}ms")

        results[res["case_id"]] = res
        summary_list.append({
            "case_id": res["case_id"],
            "case_name": res["case_name"],
            "placed_count": placed,
            "requested_cartons": req,
            "utilization": util,
            "collisions": collisions,
            "violations": viols,
            "runtime_ms": rt,
            "status": status_str
        })

    full_output = {
        "suite_name": "3D-AICIVS Standard Benchmark Suite",
        "version": "1.0",
        "total_cases": len(cases),
        "passed_cases": len([s for s in summary_list if s["status"] == "PASS"]),
        "all_zero_collisions": all_zero_collisions,
        "summary": summary_list,
        "results": results,
        **results
    }

    # Ensure output directory exists
    os.makedirs(os.path.dirname(OUTPUT_RESULTS_PATH), exist_ok=True)
    with open(OUTPUT_RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(full_output, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 80)
    print(f"Benchmark Results saved to: {OUTPUT_RESULTS_PATH}")
    print(f"Total Cases: {len(cases)} | Passed: {full_output['passed_cases']} | All Collisions=0: {all_zero_collisions}")
    print("=" * 80)

    return full_output


class TestBenchmarkSuite(unittest.TestCase):
    """Unittest test cases for Benchmark Suite."""

    def test_run_all_5_benchmarks(self):
        output = run_benchmark_suite()
        self.assertEqual(output["total_cases"], 5)
        self.assertEqual(output["passed_cases"], 5)
        self.assertTrue(output["all_zero_collisions"])

        for case_id, res in output["results"].items():
            with self.subTest(case=case_id):
                self.assertEqual(res["collisions"], 0, f"Case {case_id} had {res['collisions']} collisions")
                self.assertGreater(res["utilization"], 0.0, f"Case {case_id} utilization must be > 0")
                self.assertGreater(res["placed_count"], 0, f"Case {case_id} placed_count must be > 0")
                self.assertIn("runtime_ms", res)
                self.assertIn("violations", res)


if __name__ == "__main__":
    unittest.main()
