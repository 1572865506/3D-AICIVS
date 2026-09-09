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
CASES_DIR = os.path.join(PROJECT_ROOT, "tests", "cases")

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

    # --- SKU 履行度与刚性/弹性合规审计 ---
    sku_counts: Dict[str, int] = {}
    for p in sol.placements:
        sid = getattr(p, "sku_id", "") or (p.get("sku_id") if isinstance(p, dict) else "")
        if sid:
            sku_counts[sid] = sku_counts.get(sid, 0) + 1

    rigid_req = 0
    rigid_placed = 0
    elastic_req = 0
    elastic_placed = 0
    starved_skus = []
    sku_fulfillment_details = {}

    for c in v2_cargos:
        sid = c.sku_id
        is_elastic = getattr(c, "is_elastic", False)
        req_q = c.quantity.required
        p_count = sku_counts.get(sid, 0)
        c_rate = round(p_count / max(1, req_q) * 100.0, 1)

        sku_fulfillment_details[sid] = {
            "name": c.name,
            "is_elastic": is_elastic,
            "required": req_q,
            "placed": p_count,
            "completion_pct": c_rate
        }

        if is_elastic:
            elastic_req += req_q
            elastic_placed += p_count
        else:
            rigid_req += req_q
            rigid_placed += p_count
            if p_count == 0 and req_q > 0:
                starved_skus.append(sid)

    rigid_comp_pct = round(rigid_placed / max(1, rigid_req) * 100.0, 2)
    elastic_comp_pct = round(elastic_placed / max(1, elastic_req) * 100.0, 2) if elastic_req > 0 else 0.0
    
    # 异常判断：当存在刚性SKU未装完（<99%），却塞入了大量弹性件（>0件）
    priority_inversion = bool(rigid_comp_pct < 99.0 and elastic_placed > 0)

    # --- 细分约束审计分类 ---
    audit_breakdown = {
        "orientation_violations": 0,
        "floor_only_violations": 0,
        "top_stack_violations": 0,
        "bearing_violations": 0,
        "stack_layer_violations": 0,
        "support_floating_violations": 0,
        "zone_violations": 0,
        "door_lockout_violations": 0,
        "payload_violations": 0,
    }

    for v in val_report.violations:
        v_type = str(getattr(v, "violation_type", ""))
        msg = str(getattr(v, "message", "")).lower()
        if "ORIENTATION" in v_type:
            audit_breakdown["orientation_violations"] += 1
        elif "FLOOR" in v_type:
            audit_breakdown["floor_only_violations"] += 1
        elif "TOP_STACK" in v_type or "no_top" in msg:
            audit_breakdown["top_stack_violations"] += 1
        elif "BEARING" in v_type or "pressure" in msg:
            audit_breakdown["bearing_violations"] += 1
        elif "STACK_LIMIT" in v_type or "layer" in msg:
            audit_breakdown["stack_layer_violations"] += 1
        elif "SUPPORT" in v_type or "floating" in msg or "unsupported" in msg:
            audit_breakdown["support_floating_violations"] += 1
        elif "DOOR_LOCKOUT" in v_type or "door" in msg:
            audit_breakdown["door_lockout_violations"] += 1
        elif "ZONE" in v_type:
            audit_breakdown["zone_violations"] += 1
        elif "PAYLOAD" in v_type or "weight" in msg:
            audit_breakdown["payload_violations"] += 1

    # 综合健康状态评估
    health_status = "HEALTHY"
    health_issues = []
    if total_violations > 0:
        health_status = "VIOLATED"
        health_issues.append(f"VIOLATIONS({total_violations})")
    if overlap_count > 0:
        health_status = "COLLISION"
        health_issues.append(f"COLLISIONS({overlap_count})")
    if priority_inversion:
        health_issues.append("PRIORITY_INVERSION(弹性侵蚀刚性)")
        if health_status == "HEALTHY":
            health_status = "UNHEALTHY_PRIORITY"
    if starved_skus:
        health_issues.append(f"STARVATION({len(starved_skus)}SKU未放)")
        if health_status == "HEALTHY":
            health_status = "SKU_STARVATION"

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
        "health_status": health_status,
        "health_issues": health_issues,
        "sku_fulfillment": {
            "rigid_required": rigid_req,
            "rigid_placed": rigid_placed,
            "rigid_completion_pct": rigid_comp_pct,
            "elastic_required": elastic_req,
            "elastic_placed": elastic_placed,
            "elastic_completion_pct": elastic_comp_pct,
            "priority_inversion": priority_inversion,
            "starved_skus": starved_skus,
            "sku_details": sku_fulfillment_details,
        },
        "constraint_audit": audit_breakdown,
        "summary": {
            "placedCount": placed_count,
            "unplacedCount": unplaced_count,
            "utilization": utilization_pct,
            "rigidCompletion": rigid_comp_pct,
            "healthStatus": health_status
        }
    }


def load_json_cases() -> List[Tuple[Dict[str, Any], List[Dict[str, Any]], str, str, str]]:
    """
    从 tests/cases/ 目录动态加载 JSON 格式的测试用例。
    每个 JSON 文件必须包含: case_id, case_name, description, container, cargo。
    按文件名排序加载，确保用例顺序稳定。
    """
    if not os.path.isdir(CASES_DIR):
        return []

    loaded = []
    json_files = sorted(f for f in os.listdir(CASES_DIR) if f.endswith(".json"))

    for fname in json_files:
        fpath = os.path.join(CASES_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)

            case_id = data["case_id"]
            case_name = data.get("case_name", case_id)
            description = data.get("description", "")

            # 解析容器规格
            container_raw = data.get("container", {})
            if isinstance(container_raw, str) and container_raw.upper() in ("40HQ", "40HC"):
                container_spec = DEFAULT_40HQ_SPEC
            else:
                container_spec = {
                    "usable": {
                        "L": float(container_raw.get("usable", container_raw).get("L", 12.032)),
                        "W": float(container_raw.get("usable", container_raw).get("W", 2.352)),
                        "H": float(container_raw.get("usable", container_raw).get("H", 2.698)),
                    },
                    "maxPayloadTons": float(container_raw.get("maxPayloadTons", 26.5))
                }

            # 解析货物列表
            cargo_list = []
            for item in data.get("cargo", []):
                cargo_entry = {
                    "sku": item.get("sku", ""),
                    "name": item.get("name", ""),
                    "w": float(item.get("w", 0.0)),
                    "d": float(item.get("d", 0.0)),
                    "h": float(item.get("h", 0.0)),
                    "weight": float(item.get("weight", 0.0)),
                    "quantity": int(item.get("quantity", 0)),
                    "requirement": item.get("requirement", ""),
                }
                # 传递约束字段（如果存在）
                for key in ("isElastic", "allowDoorZone", "mustBeOnFloor",
                            "allowStackingOnTop", "allowFlat", "allowSide",
                            "max_stack_layers", "maxBearingKg", "maxFlatLayers"):
                    if key in item:
                        cargo_entry[key] = item[key]
                cargo_list.append(cargo_entry)

            loaded.append((container_spec, cargo_list, case_id, case_name, description))
        except Exception as e:
            print(f"  [WARN] 跳过无效用例文件 {fname}: {e}")

    return loaded


def run_benchmark_suite() -> Dict[str, Any]:
    """Runs all benchmark cases (5 hardcoded + dynamic JSON) and exports benchmark_results.json."""
    # 原有 5 个硬编码用例
    cases = [
        get_benchmark_case_1_14sku(),
        get_benchmark_case_2_single_large(),
        get_benchmark_case_3_all_elastic(),
        get_benchmark_case_4_door_dense(),
        get_benchmark_case_5_mixed_heterogeneous(),
    ]

    # 动态加载 tests/cases/ 目录下的 JSON 用例
    json_cases = load_json_cases()
    if json_cases:
        cases.extend(json_cases)

    total_cases = len(cases)

    print("=" * 80)
    print("3D-AICIVS Solver Benchmark Suite (TASK-07 / Step 7.1)")
    print("=" * 80)

    results = {}
    summary_list = []
    all_zero_collisions = True

    for i, (spec, cargo, cid, name, desc) in enumerate(cases, 1):
        print(f"\n[{i}/{total_cases}] Running: {name} ({cid}) ...")
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

        status_str = "PASS" if (collisions == 0 and util > 0 and viols == 0) else ("WARN" if collisions == 0 and util > 0 else "FAIL")
        
        # 提取关键履行与审计指标
        ful = res.get("sku_fulfillment", {})
        r_comp = ful.get("rigid_completion_pct", 0.0)
        e_comp = ful.get("elastic_completion_pct", 0.0)
        h_status = res.get("health_status", "UNKNOWN")
        h_issues = res.get("health_issues", [])
        
        print(f"  [{status_str}] Placed: {placed}/{req} | Util: {util:.2f}% | 刚性SKU履行: {r_comp}% | 弹性完成: {e_comp}% | 违规: {viols} | 耗时: {rt:.1f}ms")
        if h_issues:
            print(f"         ⚠️ 审计告警: {', '.join(h_issues)}")

        results[res["case_id"]] = res
        summary_list.append({
            "case_id": res["case_id"],
            "case_name": res["case_name"],
            "placed_count": placed,
            "requested_cartons": req,
            "utilization": util,
            "rigid_completion_pct": r_comp,
            "elastic_completion_pct": e_comp,
            "collisions": collisions,
            "violations": viols,
            "health_status": h_status,
            "health_issues": h_issues,
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

    print("\n" + "=" * 110)
    print("3D-AICIVS 基准测试多维合规审计总结表")
    print("=" * 110)
    print(f"{'Case ID':<30} | {'利用率':<8} | {'刚性履行':<8} | {'弹性履行':<8} | {'违规':<5} | {'碰撞':<5} | {'健康状态':<20}")
    print("-" * 110)
    for s in summary_list:
        print(f"{s['case_id']:<30} | {s['utilization']:<7.2f}% | {s['rigid_completion_pct']:<7.1f}% | {s['elastic_completion_pct']:<7.1f}% | {s['violations']:<5} | {s['collisions']:<5} | {s['health_status']:<20}")
    print("=" * 110)
    print(f"测试结果已写入: {OUTPUT_RESULTS_PATH}")
    print(f"总用例: {len(cases)} | 全合规PASS: {full_output['passed_cases']} | 无碰撞: {all_zero_collisions}")
    print("=" * 110)

    return full_output


class TestBenchmarkSuite(unittest.TestCase):
    """Unittest test cases for Benchmark Suite."""

    def test_run_all_benchmarks(self):
        output = run_benchmark_suite()
        self.assertGreaterEqual(output["total_cases"], 5, "至少包含 5 个硬编码基准用例")
        self.assertEqual(output["passed_cases"], output["total_cases"], "所有用例必须 PASS")
        self.assertTrue(output["all_zero_collisions"])

        for case_id, res in output["results"].items():
            with self.subTest(case=case_id):
                self.assertEqual(res["collisions"], 0, f"Case {case_id} had {res['collisions']} collisions")
                self.assertGreater(res["utilization"], 0.0, f"Case {case_id} utilization must be > 0")
                self.assertGreater(res["placed_count"], 0, f"Case {case_id} placed_count must be > 0")
                self.assertIn("runtime_ms", res)
                self.assertIn("violations", res)


if __name__ == "__main__":
    # 支持直接运行（跳过 unittest 框架，直接输出结果表格）
    if len(sys.argv) > 1 and sys.argv[1] == "--run":
        run_benchmark_suite()
    else:
        unittest.main()
