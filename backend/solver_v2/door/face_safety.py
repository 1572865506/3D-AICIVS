"""门面（最前货面）列安全系数与封门件容量估算。

背景：
- 原求解器只检查“柜门平面外 N 米”的固定台阶带；实际门面可能停在更深处
  （例如 0.56m 厚封门墙的 front face 在 11.50m），固定带完全覆盖不到。
- 本模块用“实际最前货面”的列口径（与 geometry_qa.door_open / score.py 一致）
  提供门面列 SF，并估算在门面 SF≥1.5 约束下封门件需要多少门区纵深。

被谁调用：unified_solver（门面动态检查）、config_precheck（容量 422）、tests。
"""

import collections
import math
from typing import Any, Dict, Iterable, List, Optional

from backend.solver_v2.domain.models import PackingRole, ZoneType


def _box(item: Any):
    if isinstance(item, dict):
        return (float(item.get("x", 0.0)), float(item.get("y", 0.0)),
                float(item.get("z", 0.0)), float(item.get("dx", 0.0)),
                float(item.get("dy", 0.0)), float(item.get("dz", 0.0)))
    return (float(item.position.x), float(item.position.y), float(item.position.z),
            float(item.orientation.dx), float(item.orientation.dy),
            float(item.orientation.dz))


def is_door_seal_sku(sku: Any) -> bool:
    """是否封柜门件（区域=DOOR 或角色含 DOOR_SEAL，且非弹性）。"""
    is_elastic = bool(
        getattr(getattr(sku, "quantity", None), "is_elastic", False)
        or getattr(sku, "is_elastic", False)
    )
    roles = tuple(getattr(sku, "packing_roles", ()) or ())
    return (not is_elastic) and (
        getattr(sku, "target_zone", None) == ZoneType.DOOR
        or PackingRole.DOOR_SEAL in roles
    )


def column_sf_at(cand: Any, placements: Iterable[Any]) -> Dict[str, Any]:
    """候选加入后其所在列的 SF，以及它是否成为新的最前货面。

    与 face_columns / geometry_qa.door_open 同口径：同 (x0,y0) 列、D=max(dx)、
    H=Σdz、SF=2D/H。用于求解器放置前的门面动态检查。
    """
    cx, cy, cz, cdx, cdy, cdz = _box(cand)
    boxes = [_box(p) for p in (placements or [])]
    current_face = max((x + dx for (x, _, _, dx, _, _) in boxes), default=0.0)
    cand_face = cx + cdx
    is_face = cand_face >= current_face - 1e-4
    D = cdx
    H = cdz
    for (x, y, _, dx, _, dz) in boxes:
        if abs(x - cx) < 1e-3 and abs(y - cy) < 1e-3:
            D = max(D, dx)
            H += dz
    sf = (2.0 * D) / max(H, 1e-6)
    return {
        "cand_face": round(cand_face, 4),
        "current_face": round(current_face, 4),
        "is_face": bool(is_face),
        "D": round(D, 4),
        "H": round(H, 4),
        "sf": round(sf, 4),
    }


def face_columns(placements: Iterable[Any], container_length: float) -> Dict[str, Any]:
    """返回最前货面与门面列（同 x0/y0 列 D=max(dx), H=Σdz, SF=2D/H）。"""
    boxes = [_box(p) for p in (placements or [])]
    if not boxes:
        return {"face": None, "columns": [], "min_sf": None, "unsafe_columns": 0}
    face = max(x + dx for (x, _, _, dx, _, _) in boxes)
    cols: Dict[tuple, Dict[str, float]] = collections.defaultdict(
        lambda: {"D": 0.0, "H": 0.0})
    for (x, y, _, dx, _, dz) in boxes:
        if face - (x + dx) > 1e-3:
            continue
        key = (round(x, 3), round(y, 3))
        cols[key]["D"] = max(cols[key]["D"], dx)
        cols[key]["H"] += dz
    columns = []
    for (x0, y0), e in cols.items():
        sf = (2.0 * e["D"]) / max(e["H"], 1e-6)
        columns.append({"x0": x0, "y0": y0, "D": round(e["D"], 4),
                        "H": round(e["H"], 4), "sf": round(sf, 4),
                        "unsafe": sf < 1.5 - 1e-6})
    return {
        "face": round(face, 4),
        "columns": columns,
        "min_sf": round(min(c["sf"] for c in columns), 4) if columns else None,
        "unsafe_columns": sum(1 for c in columns if c["unsafe"]),
    }


def door_seal_capacity(
    door_skus: List[Any],
    container: Any,
    available_depth_m: float,
    min_sf: float = 1.5,
) -> Dict[str, Any]:
    """估算封门件在“门面 SF≥min_sf”下需要的最小门区纵深。

    口径：
    - 只考虑 upright 朝向（封门墙按立放定义；其他朝向需业务显式允许另行评估）；
    - 最前一行受门面列 SF 限制，最多 `floor(2*dx/(min_sf*dz))` 层；
    - 后排可按柜高满层；每行槽位 = floor((Ly-0.02)/dy) × 层数；
    - 需要纵深 = 行数 × 该朝向 dx。

    对多个封门 SKU 返回逐 SKU 结果与保守合计（预检目前只对单 SKU 强制 422）。
    """
    ly = float(getattr(container, "Ly", 0.0))
    lz = float(getattr(container, "Lz", 0.0))
    if ly <= 0 or lz <= 0:
        return {"feasible": False, "required_depth_m": None,
                "available_depth_m": available_depth_m, "per_sku": [],
                "reason": "柜体宽高不可用"}
    per_sku = []
    for sku in door_skus or []:
        qty = int(getattr(getattr(sku, "quantity", None), "required", 0) or 0)
        if qty <= 0:
            continue
        box = getattr(sku, "box", None)
        if box is None:
            continue
        dims = (float(box.x), float(box.y), float(box.z))
        best = None
        for dx, dy in ((dims[0], dims[1]), (dims[1], dims[0])):
            dz = dims[2]
            if dx <= 1e-6 or dy <= 1e-6 or dz <= 1e-6:
                continue
            height_layers = int(math.floor((lz - 0.04) / dz + 1e-9))
            front_layers = int(math.floor((2.0 * dx) / (min_sf * dz) + 1e-9))
            front_layers = min(front_layers, height_layers)
            slots_y = int(math.floor((ly - 0.02) / dy + 1e-9))
            if front_layers < 1 or slots_y < 1:
                continue
            front_slots = slots_y * front_layers
            rear_slots = slots_y * height_layers
            if qty <= front_slots:
                rows = 1
            elif rear_slots <= 0:
                continue
            else:
                rows = 1 + int(math.ceil((qty - front_slots) / rear_slots))
            required = rows * dx
            cand = {
                "sku_id": getattr(sku, "sku_id", "?"),
                "dx": round(dx, 4), "dy": round(dy, 4), "dz": round(dz, 4),
                "front_layers": front_layers, "rear_layers": height_layers,
                "slots_front": front_slots, "slots_rear_per_row": rear_slots,
                "rows": rows, "required_depth_m": round(required, 4),
            }
            if best is None or required < best["required_depth_m"]:
                best = cand
        if best is not None:
            per_sku.append(best)

    if not per_sku:
        return {"feasible": False, "required_depth_m": None,
                "available_depth_m": round(float(available_depth_m), 4),
                "per_sku": [], "reason": "没有可用的封门件立放朝向"}
    # 多 SKU 保守取“逐 SKU 需求之和”；预检当前只对单 SKU 强制 422。
    required = sum(item["required_depth_m"] for item in per_sku)
    feasible = required <= float(available_depth_m) + 1e-6
    return {
        "feasible": bool(feasible),
        "required_depth_m": round(required, 4),
        "available_depth_m": round(float(available_depth_m), 4),
        "per_sku": per_sku,
        "reason": "" if feasible else (
            f"封门件在门面 SF≥{min_sf:g} 下需要 {required:.3f}m 门区纵深，"
            f"当前仅 {float(available_depth_m):.3f}m"),
    }


__all__ = ["is_door_seal_sku", "column_sf_at", "face_columns", "door_seal_capacity"]
