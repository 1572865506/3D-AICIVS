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
    door_open: bool = False,
) -> TippingVerdict:
    """纵向倾覆判定（0.5g 制动工况）。

    door_open=True 时柜门不作为前向支承（用于"开门后倾覆"审计/安全模式）：
    门面箱必须自身 SF≥1.5 或由前方货箱支承。
    """
    dx, dz = cand["dx"], cand["dz"]
    if dz <= 1e-6:
        return TippingVerdict(True, float("inf"), "DEGENERATE_DZ")

    sf = (2.0 * dx) / dz
    if sf >= 1.5 - eps:
        return TippingVerdict(True, sf, "INTRINSIC_SF")

    if not door_open and cand["x"] + dx >= container_length - 0.04 - eps:
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
                 container_length: float, eps: float = 1e-4,
                 door_open: bool = False) -> bool:
    return tipping_verdict(cand, placements, container_length, eps, door_open).safe


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


def lateral_stable(
    cand: Dict[str, Any],
    placements: List[Dict[str, Any]],
    container_width: float,
    container_length: Optional[float] = None,
    eps: float = 1e-4,
) -> bool:
    """横向稳定（TIP-02 单一规则源）：高瘦箱必须有同层侧向接触或贴壁。

    运输途中横向位移会使无侧向约束的高瘦箱倾覆；此处按"贴壁/邻箱接触"判断。
    仅当箱体在某一水平轴上超过细长阈值（着地 2.5、离地 2.0；贴壁 3.5）时约束。
    传入 container_length 时，门端（x+dx 到达 cL-0.04）视为 +X 侧刚性支承
    （运输时柜门关闭）；开门状态的风险由 DG-020 单独审计。
    """
    dx, dy, dz = cand["dx"], cand["dy"], cand["dz"]
    if dx <= 1e-4 or dy <= 1e-4:
        return True

    slenderness_y = dz / dy
    slenderness_x = dz / dx
    is_ground = cand["z"] < 1e-3
    near_y_wall = cand["y"] <= 0.02 or (cand["y"] + dy) >= container_width - 0.02
    near_x_wall = cand["x"] <= 0.02

    thresh_base_y = 3.5 if (is_ground and near_y_wall) else (2.5 if is_ground else 2.0)
    thresh_base_x = 3.5 if (is_ground and near_x_wall) else (2.5 if is_ground else 2.0)
    needs_y = slenderness_y > thresh_base_y
    needs_x = slenderness_x > thresh_base_x
    if not needs_y and not needs_x:
        return True

    cx0, cx1 = cand["x"], cand["x"] + dx
    cy0, cy1 = cand["y"], cand["y"] + dy
    cz0, cz1 = cand["z"], cand["z"] + dz

    has_y_neg = cy0 <= 0.02
    has_y_pos = cy1 >= container_width - 0.02
    has_x_neg = cx0 <= 0.02
    # 门端（柜门关闭）提供 +X 侧支承；未给 length 时按无支承处理
    has_x_pos = (container_length is not None
                 and cx1 >= container_length - 0.04 - 0.02)

    min_x_overlap = 0.05 * dx
    min_y_overlap = 0.05 * dy
    min_z_overlap = 0.20 * dz

    for p in placements:
        if p is cand:
            continue
        px0, px1 = p["x"], p["x"] + p["dx"]
        py0, py1 = p["y"], p["y"] + p["dy"]
        pz0, pz1 = p["z"], p["z"] + p["dz"]
        z_ov = min(cz1, pz1) - max(cz0, pz0)
        if z_ov < min_z_overlap - 1e-4:
            continue
        x_ov = min(cx1, px1) - max(cx0, px0)
        y_ov = min(cy1, py1) - max(cy0, py0)
        if not has_y_neg and abs(py1 - cy0) <= 0.03 and x_ov >= min_x_overlap - 1e-4:
            has_y_neg = True
        if not has_y_pos and abs(py0 - cy1) <= 0.03 and x_ov >= min_x_overlap - 1e-4:
            has_y_pos = True
        if not has_x_neg and abs(px1 - cx0) <= 0.03 and y_ov >= min_y_overlap - 1e-4:
            has_x_neg = True
        if not has_x_pos and abs(px0 - cx1) <= 0.03 and y_ov >= min_y_overlap - 1e-4:
            has_x_pos = True

    if needs_y:
        if not is_ground:
            if slenderness_y > 3.0 and not (has_y_neg and has_y_pos):
                return False
            if not (has_y_neg or has_y_pos):
                return False
        elif not (has_y_neg or has_y_pos):
            return False

    if needs_x:
        if not is_ground:
            if slenderness_x > 3.0 and not (has_x_neg and has_x_pos):
                return False
            if not (has_x_neg or has_x_pos):
                return False
        elif not (has_x_neg or has_x_pos):
            return False

    return True


def pressure_violation(    placements: List[Dict[str, Any]],
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
