#!/usr/bin/env python3
"""
Standalone Local Test Runner for 3D-AICIVS Solver V2.

Allows running solver and validation benchmarks locally without consuming agent tokens.
Accepts SKU datasets from:
1. System clipboard (--clipboard / -c) [Default if copied from UI button]
2. File path (--file / -f <path>)
3. Standard Input (--stdin)
4. Built-in presets (--preset production|standard|heavy)
"""

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure project root in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.domain.models import (
    BoxDim,
    CargoSKU,
    ContainerSpec,
    QuantityPlan,
    ZoneType,
    PackingRole,
    OrientationSpec,
    OrientationMode,
)
from backend.solver_v2.solver.unified_solver import UnifiedSolver
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator


def get_clipboard_text() -> str:
    """Read text from system clipboard using platform utilities."""
    if sys.platform == "win32":
        try:
            import win32clipboard  # type: ignore
            win32clipboard.OpenClipboard()
            data = win32clipboard.GetClipboardData()
            win32clipboard.CloseClipboard()
            return data
        except Exception:
            pass
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            data = root.clipboard_get()
            root.destroy()
            return data
        except Exception:
            pass
        try:
            import subprocess
            res = subprocess.run(["powershell", "-command", "Get-Clipboard"], capture_output=True, text=True, check=True)
            return res.stdout
        except Exception as e:
            raise RuntimeError(f"Unable to read clipboard on Windows: {e}")
    elif sys.platform == "darwin":
        import subprocess
        res = subprocess.run(["pbpaste"], capture_output=True, text=True, check=True)
        return res.stdout
    else:
        import subprocess
        res = subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True, check=True)
        return res.stdout


def parse_manifest_data(raw_data: Any) -> Tuple[ContainerSpec, List[CargoSKU]]:
    """Parse JSON data copied from UI or benchmark file into ContainerSpec and List[CargoSKU]."""
    if isinstance(raw_data, str):
        raw_data = json.loads(raw_data)

    # 1. Parse Container
    seed = raw_data.get("containerSeed", {})
    inner = seed.get("inner", {}) if isinstance(seed, dict) else {}
    lx = float(inner.get("x", inner.get("L", 12.024)))
    ly = float(inner.get("y", inner.get("W", 2.350)))
    lz = float(inner.get("z", inner.get("H", 2.690)))
    c_spec = ContainerSpec(
        code=str(seed.get("type", "40HQ")),
        inner_dim=BoxDim(lx, ly, lz),
        max_payload_kg=float(seed.get("maxPayloadKg", 26000.0)),
    )

    # 2. Parse Cargo
    cargo_raw = raw_data.get("cargo", raw_data.get("skus", []))
    if not cargo_raw and isinstance(raw_data, list):
        cargo_raw = raw_data

    skus: List[CargoSKU] = []
    for item in cargo_raw:
        sku_id = item.get("sku", item.get("id", "UNKNOWN"))
        name = item.get("name", sku_id)
        src = item.get("source", item)

        w = float(src.get("w", src.get("dx", 0.5)))
        d = float(src.get("d", src.get("dy", 0.5)))
        h = float(src.get("h", src.get("dz", 0.5)))
        weight = float(src.get("weight", src.get("weight_kg", 10.0)))
        qty = int(src.get("quantity", src.get("qty", 1)))
        req = src.get("requirement", "")

        zone = ZoneType.MIDDLE
        roles = []
        if "最里面" in req or "里面" in req or "内" in req:
            zone = ZoneType.REAR
            roles.append(PackingRole.FOUNDATION)
        elif "封柜门" in req or "封门" in req or "门" in req:
            zone = ZoneType.DOOR
            roles.append(PackingRole.DOOR_SEAL)

        from backend.solver_v2.domain.models import OrientationPolicy, StackingPolicy

        ori = item.get("allowedOrientation", "default")
        allow_flat = ori in ("allow_flat", "any") or bool(item.get("allowFlat"))
        allow_side = ori in ("allow_side", "any")

        max_layers = item.get("maxStackLayers")
        if max_layers is not None:
            try:
                max_layers = int(max_layers)
            except Exception:
                max_layers = None

        is_elastic = bool(
            item.get("isElastic")
            or src.get("isElastic")
            or "可以减少" in req
            or "可减少" in req
            or "少放" in req
        )

        cargo_sku = CargoSKU(
            sku_id=sku_id,
            name=name,
            box=BoxDim(w, d, h),
            weight_kg=weight,
            quantity=QuantityPlan(required=qty, is_elastic=is_elastic),
            target_zone=zone,
            packing_roles=tuple(roles) if roles else (PackingRole.MAIN_WALL,),
            source_requirement_text=req,
            orientation_policy=OrientationPolicy(
                allow_upright=True,
                allow_flat=allow_flat,
                allow_side=allow_side,
            ),
            stacking_policy=StackingPolicy(max_stack_layers=max_layers),
        )
        skus.append(cargo_sku)

    return c_spec, skus


def run_benchmark(container: ContainerSpec, cargo: List[CargoSKU]) -> Dict[str, Any]:
    """Execute UnifiedSolver and run IndependentGlobalValidator."""
    solver = UnifiedSolver(container)

    t0 = time.perf_counter()
    solution = solver.solve(cargo)
    duration_ms = (time.perf_counter() - t0) * 1000.0

    # Validator accepts container dimensions and placements dict
    validator = IndependentGlobalValidator()
    c_dim = (container.Lx, container.Ly, container.Lz)
    placements_dict = []
    for p in solution.placements:
        placements_dict.append({
            "placement_id": p.placement_id,
            "sku_id": p.sku_id,
            "x": p.position.x,
            "y": p.position.y,
            "z": p.position.z,
            "dx": p.orientation.dx,
            "dy": p.orientation.dy,
            "dz": p.orientation.dz,
            "weight_kg": p.weight_kg,
            "orientation": p.orientation.name,
            "step": p.step_index,
        })

    val_res = validator.validate(c_dim, placements_dict)

    total_cargo_volume = sum(
        s.box.x * s.box.y * s.box.z * s.quantity.required for s in cargo
    )
    placed_volume = sum(
        p.get("dx", 0.0) * p.get("dy", 0.0) * p.get("dz", 0.0) for p in placements_dict
    )
    container_volume = container.Lx * container.Ly * container.Lz

    total_req_boxes = sum(s.quantity.required for s in cargo)
    placed_count = len(placements_dict)

    # Per-SKU breakdown
    sku_stats: Dict[str, Dict[str, Any]] = {}
    for s in cargo:
        ori_modes = ["UPRIGHT"]
        if s.orientation_policy.allow_flat:
            ori_modes.append("FLAT")
        if s.orientation_policy.allow_side:
            ori_modes.append("SIDE")
        ori_str = "/".join(ori_modes)

        sku_stats[s.sku_id] = {
            "sku_id": s.sku_id,
            "name": s.name,
            "req": s.quantity.required,
            "placed": 0,
            "unplaced": s.quantity.required,
            "w": s.box.x,
            "d": s.box.y,
            "h": s.box.z,
            "dims": f"{s.box.x:.3f}x{s.box.y:.3f}x{s.box.z:.3f}",
            "weight_kg": s.weight_kg,
            "unit_vol": round(s.box.x * s.box.y * s.box.z, 4),
            "zone": s.target_zone.value if s.target_zone else "GENERAL",
            "requirement_text": s.source_requirement_text or "放中间",
            "orientation_policy": ori_str,
            "max_layers": s.stacking_policy.max_stack_layers if s.stacking_policy and s.stacking_policy.max_stack_layers else "无限制",
            "is_elastic": getattr(s.quantity, "is_elastic", False),
            "packing_roles": [r.value for r in s.packing_roles],
            "used_orientations": {},
        }

    for p in placements_dict:
        sid = p.get("sku_id")
        if sid in sku_stats:
            sku_stats[sid]["placed"] += 1
            sku_stats[sid]["unplaced"] = max(0, sku_stats[sid]["req"] - sku_stats[sid]["placed"])
            o_name = p.get("orientation", "DEFAULT")
            sku_stats[sid]["used_orientations"][o_name] = sku_stats[sid]["used_orientations"].get(o_name, 0) + 1

    # Geometry utilization & Bounds
    max_x = max((p.get("x", 0.0) + p.get("dx", 0.0) for p in placements_dict), default=0.0)
    max_z = max((p.get("z", 0.0) + p.get("dz", 0.0) for p in placements_dict), default=0.0)

    return {
        "duration_ms": duration_ms,
        "container": {
            "code": container.code,
            "Lx": container.Lx,
            "Ly": container.Ly,
            "Lz": container.Lz,
            "volume_m3": round(container_volume, 3),
        },
        "summary": {
            "total_req_boxes": total_req_boxes,
            "placed_boxes": placed_count,
            "unplaced_boxes": total_req_boxes - placed_count,
            "fill_rate_boxes": round(placed_count / total_req_boxes * 100, 2) if total_req_boxes else 0.0,
            "container_vol_util": round(placed_volume / container_volume * 100, 2),
            "cargo_vol_packed": round(placed_volume / total_cargo_volume * 100, 2) if total_cargo_volume else 0.0,
            "placed_volume_m3": round(placed_volume, 3),
            "max_x_m": round(max_x, 3),
            "door_gap_m": round(container.Lx - max_x, 3),
            "max_z_m": round(max_z, 3),
            "roof_gap_m": round(container.Lz - max_z, 3),
        },
        "validation": {
            "is_valid": val_res.is_valid,
            "violations_count": len(val_res.violations),
            "violations": [v.to_dict() if hasattr(v, "to_dict") else str(v) for v in val_res.violations],
        },
        "sku_stats": sku_stats,
    }


def print_report(res: Dict[str, Any]):
    """Format and print a professional scorecard to terminal with complete SKU parameter identification."""
    s = res["summary"]
    c = res["container"]
    v = res["validation"]

    print("\n" + "=" * 110)
    print(" 🚀 3D-AICIVS SOLVER V2 BENCHMARK & SKU AUDIT REPORT ")
    print("=" * 110)
    print(f" Container: {c['code']} ({c['Lx']:.3f}m x {c['Ly']:.3f}m x {c['Lz']:.3f}m) | Usable Vol: {c['volume_m3']} m³")
    print(f" Compute Time: {res['duration_ms']:.1f} ms")
    print("-" * 110)
    print(f" 📦 Total Required Boxes: {s['total_req_boxes']:<6} | Placed: {s['placed_boxes']:<6} | Unplaced: {s['unplaced_boxes']:<6}")
    print(f" 📊 Box Fulfillment Rate: {s['fill_rate_boxes']:.1f}%")
    print(f" 📐 Container Vol Util:   {s['container_vol_util']:.1f}% ({s['placed_volume_m3']} m³)")
    print(f" 🚪 Door Space Remaining: {s['door_gap_m']:.3f} m (Max X: {s['max_x_m']:.3f} m / {c['Lx']:.3f} m)")
    print(f" ☁️  Top Space Remaining:  {s['roof_gap_m']:.3f} m (Max Z: {s['max_z_m']:.3f} m / {c['Lz']:.3f} m)")
    print("-" * 110)

    val_status = "✅ PASSED (0 Violations)" if v["is_valid"] else f"❌ FAILED ({v['violations_count']} Violations)"
    print(f" 🛡️  Independent Validation: {val_status}")
    if not v["is_valid"]:
        for idx, vio in enumerate(v["violations"][:10], 1):
            print(f"    - Violation #{idx}: {vio}")

    print("-" * 110)
    print(" 📋 [TABLE 1] SKU PARAMETER SPECIFICATIONS & PACKING RESULT SCORECARD")
    print("-" * 110)
    header = (
        f" {'SKU':<8} | {'Dims (LxWxH m)':<17} | {'Wt(kg)':<6} | {'Req':<5} | {'Placed':<6} | {'Unp':<5} | "
        f"{'Zone/Req':<10} | {'Orientations':<12} | {'MaxLay':<7} | {'Elastic':<7} | {'Status':<6}"
    )
    print(header)
    print("-" * 110)

    for sku_id, st in res["sku_stats"].items():
        status = "100%" if st["unplaced"] == 0 else f"-{st['unplaced']}"
        zone_short = st["requirement_text"][:8] if st["requirement_text"] else st["zone"]
        max_l_str = str(st["max_layers"])
        elastic_str = "YES" if st["is_elastic"] else "NO"

        row = (
            f" {sku_id:<8} | {st['dims']:<17} | {st['weight_kg']:<6.1f} | {st['req']:<5} | {st['placed']:<6} | {st['unplaced']:<5} | "
            f"{zone_short:<10} | {st['orientation_policy']:<12} | {max_l_str:<7} | {elastic_str:<7} | {status:<6}"
        )
        print(row)

    print("-" * 110)
    print(" 🔍 [TABLE 2] UNPLACED SKU BOTTLENECK & CONSTRAINT AUDIT (给Agent针对性调优提供的事实数据)")
    print("-" * 110)

    unplaced_skus = [st for st in res["sku_stats"].values() if st["unplaced"] > 0]
    if not unplaced_skus:
        print("  🎉 恭喜！所有 SKU 均已 100% 成功装载，无任何未装入货箱！")
    else:
        for st in unplaced_skus:
            used_ori_summary = ", ".join(f"{k}:{v}" for k, v in st["used_orientations"].items()) if st["used_orientations"] else "无装入"
            print(f"  • [{st['name']}] (SKU: {st['sku_id']}):")
            print(f"    - 参数配置: 单箱尺寸={st['dims']}m, 单箱重量={st['weight_kg']}kg, 单箱体积={st['unit_vol']}m³")
            print(f"    - 规划约束: 摆放要求='{st['requirement_text']}', 允许朝向={st['orientation_policy']}, 堆叠上限={st['max_layers']}, 弹性数量={st['is_elastic']}")
            print(f"    - 实装状态: 计划={st['req']}箱, 实装={st['placed']}箱, 滞留未装={st['unplaced']}箱 (未装体积={(st['unplaced']*st['unit_vol']):.3f}m³)")
            print(f"    - 已装朝向分布: {used_ori_summary}")
            # Diagnostic hint
            if "门" in st["requirement_text"] or st["zone"] == "DOOR":
                print(f"    - ⚠️ 算法诊断: 门区货箱。当前柜门剩余纵深为 {s['door_gap_m']:.3f}m。检查该SKU是否有更小朝向dx (如旋转后宽度) 可塞入该缝隙。")
            else:
                print(f"    - ⚠️ 算法诊断: 中间/顶部货箱。顶部剩余空间为 {s['roof_gap_m']:.3f}m。检查Pass 4腔体多层扩展是否因局部碰撞或台阶高度差被阻断。")
            print()

        fully_placed_skus = [st for st in res["sku_stats"].values() if st["unplaced"] == 0]
        if fully_placed_skus:
            print("-" * 110)
            print(" ✅ [TABLE 3] FULLY PLACED SKUs (100% 全部装载完成的 SKU 列表)")
            print("-" * 110)
            for st in fully_placed_skus:
                used_ori_summary = ", ".join(f"{k}:{v}" for k, v in st["used_orientations"].items()) if st["used_orientations"] else "无记录"
                print(f"  • [{st['name']}] ({st['sku_id']}): 计划={st['req']}箱 | 实装={st['placed']}箱 (100%) | 朝向={used_ori_summary}")
            print()

    print("=" * 110 + "\n")


def main():
    parser = argparse.ArgumentParser(description="3D-AICIVS Local Benchmark & Test Runner")
    parser.add_argument("-c", "--clipboard", action="store_true", help="Read SKU JSON data directly from clipboard")
    parser.add_argument("-f", "--file", type=str, help="Path to SKU JSON benchmark file")
    parser.add_argument("-p", "--preset", type=str, choices=["production", "standard", "heavy"], help="Run built-in benchmark preset")
    parser.add_argument("--json-output", action="store_true", help="Output result as pure JSON")

    args = parser.parse_args()

    raw_json = None
    if args.clipboard:
        print("📋 Reading SKU data from clipboard...")
        raw_json = get_clipboard_text()
    elif args.file:
        print(f"📂 Reading SKU data from file: {args.file}...")
        with open(args.file, "r", encoding="utf-8") as f:
            raw_json = f.read()
    elif args.preset or (not args.clipboard and not args.file):
        # Default fallback to cleanroom 40hq benchmark
        preset_path = os.path.join(PROJECT_ROOT, "devkit", "cleanroom_solver_v2_devkit", "benchmarks", "40hq_cleanroom_case_001.json")
        print(f"⚡ No input specified, running standard benchmark case: {os.path.basename(preset_path)}...")
        with open(preset_path, "r", encoding="utf-8") as f:
            raw_json = f.read()

    try:
        data = json.loads(raw_json)
    except Exception as e:
        print(f"❌ Error parsing JSON input: {e}")
        sys.exit(1)

    container, cargo = parse_manifest_data(data)
    result = run_benchmark(container, cargo)

    if args.json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_report(result)


if __name__ == "__main__":
    main()
