"""
共享约束内核（Constraint Kernel）——单一规则源。

背景：系统曾存在多套约束实现（UnifiedSolver 门禁、feasibility/HardValidationPipeline、
compaction 内联、physics_kernel），语义漂移导致"同一策略两套判定"。本模块把
**与数据结构无关的纯判定**收敛到一处，供生产门禁与遗留过滤器共同调用：

- tipping_safe：刚体纵向倾覆（SF = 2·dx/dz >= 1.5，门端豁免，前向支承豁免）
- same_sku_chain_depth：同款垂直接触链深度（层数计数的唯一权威）
- pressure_within_limit：表面压强（传递载荷 / 接触面积）

输入统一使用 placement dict 列表（键：sku_id/x/y/z/dx/dy/dz/weight_kg/
_bearing_load/_pressure_load），与 UnifiedSolver 内部表示一致。

被谁调用：backend/solver_v2/solver/unified_solver.py（生产门禁）、
backend/solver_v2/feasibility/pipeline.py（遗留过滤器，补齐缺失规则）。
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class TippingVerdict:
    safe: bool
    safety_factor: float
    reason: str


def tipping_verdict(
    cand: Dict[str, Any],
    placements: List[Dict[str, Any]],
    container_length: float,
    eps: float = 1e-4,
) -> TippingVerdict:
    """纵向倾覆判定（0.5g 制动工况）。"""
    dx, dz = cand["dx"], cand["dz"]
    if dz <= 1e-6:
        return TippingVerdict(True, float("inf"), "DEGENERATE_DZ")

    sf = (2.0 * dx) / dz
    if sf >= 1.5 - eps:
        return TippingVerdict(True, sf, "INTRINSIC_SF")

    if cand["x"] + dx >= container_length - 0.04 - eps:
        return TippingVerdict(True, sf, "DOOR_FACE_SUPPORT")

    target_x = cand["x"] + dx
    min_y_ov = 0.20 * cand["dy"]
    min_z_ov = 0.20 * cand["dz"]
    for other in placements:
        if other is cand:
            continue
        if abs(other["x"] - target_x) <= 0.03:
            y_ov = min(cand["y"] + cand["dy"], other["y"] + other["dy"]) - max(cand["y"], other["y"])
            z_ov = min(cand["z"] + cand["dz"], other["z"] + other["dz"]) - max(cand["z"], other["z"])
            if y_ov >= min_y_ov - eps and z_ov >= min_z_ov - eps:
                return TippingVerdict(True, sf, "FORWARD_SUPPORT")
    return TippingVerdict(False, sf, "NO_FORWARD_SUPPORT")


def tipping_safe(cand: Dict[str, Any], placements: List[Dict[str, Any]],
                 container_length: float, eps: float = 1e-4) -> bool:
    return tipping_verdict(cand, placements, container_length, eps).safe


def same_sku_chain_depth(
    sku_id: str, x: float, y: float, z: float,
    dx: float, dy: float, placements: List[Dict[str, Any]],
) -> int:
    """同款 SKU 垂直接触链深度（含候选自身）；15% 双向接触重叠视为同柱。"""
    depth = 1
    cur_z = round(z, 4)
    while cur_z > 1e-3:
        found = False
        for p in placements:
            if p.get("sku_id") != sku_id:
                continue
            if abs(round(p["z"] + p["dz"], 4) - cur_z) < 1e-3:
                ox = min(x + dx, p["x"] + p["dx"]) - max(x, p["x"])
                oy = min(y + dy, p["y"] + p["dy"]) - max(y, p["y"])
                if ox > 0.15 * min(dx, p["dx"]) and oy > 0.15 * min(dy, p["dy"]):
                    depth += 1
                    cur_z = round(p["z"], 4)
                    found = True
                    break
        if not found:
            break
    return depth


def pressure_violation(
    placements: List[Dict[str, Any]],
    cand: Dict[str, Any],
    max_pressure_by_sku: Dict[str, Optional[float]],
    eps: float = 1e-4,
) -> Optional[Tuple[str, float, float]]:
    """
    直接接触层的表面压强检查。

    返回 None 表示通过；否则 (被压箱 placement_id, 累计压强, 上限)。
    压强 = 传递载荷 / 接触面积 = 单件重量 / 底面面积（与接触比例无关）。
    """
    z = cand["z"]
    if z <= 1e-3:
        return None
    cand_area = max(1e-6, cand["dx"] * cand["dy"])
    for p in placements:
        if p is cand:
            continue
        if abs(round(p["z"] + p["dz"], 4) - round(z, 4)) >= 1e-3:
            continue
        ox = min(cand["x"] + cand["dx"], p["x"] + p["dx"]) - max(cand["x"], p["x"])
        oy = min(cand["y"] + cand["dy"], p["y"] + p["dy"]) - max(cand["y"], p["y"])
        if ox <= eps or oy <= eps:
            continue
        limit = max_pressure_by_sku.get(p.get("sku_id"))
        if not limit or limit <= 0:
            continue
        added = cand.get("weight_kg", 0.0) / cand_area
        current = p.get("_pressure_load", 0.0)
        if current + added > float(limit) + eps:
            return (p.get("placement_id", "?"), current + added, float(limit))
    return None
