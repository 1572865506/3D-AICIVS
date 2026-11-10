# -*- coding: utf-8 -*-
"""
纵向倾覆力矩与防倾倒安全检查纯函数 (Longitudinal Tipping & Overturning Safety)

与 IndependentGlobalValidator Gate 11 (TIP-03) 完全同构:
  - 0.5g 纵向减速制动自稳定安全系数: SF = 2.0 * dx / dz >= 1.50
  - 柜门前沿刚性阻挡豁免 (x + dx >= cL - 0.04m)
  - 前向 (+X) 紧邻货物接触支撑判定 (间隙 <= 30mm, Y/Z 轴接触跨度 >= 20%)

所有函数均为纯函数, 幂等无副作用。

被谁调用:
  - physics_kernel/__init__.py 统一导出
  - physics_kernel/unified_gate.py 聚合放置预检
  - placement_engine/ 任何放置引擎
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union
from .collision import GEOM_EPSILON, normalize_box

DOOR_MARGIN_M: float = 0.04
FORWARD_GAP_TOL_M: float = 0.03
MIN_OVERLAP_RATIO: float = 0.20
MIN_SAFETY_FACTOR: float = 1.50


def check_tipping_safety(
    candidate: Union[Dict[str, Any], Any],
    placements: List[Union[Dict[str, Any], Any]],
    container_length: float,
    min_safety_factor: float = MIN_SAFETY_FACTOR,
    spatial_index: Optional[Any] = None,
    epsilon: float = GEOM_EPSILON,
) -> Tuple[bool, float, Optional[str]]:
    """检查候选放置是否满足 0.5g 紧急制动工况下的纵向倾覆力矩安全要求。

    数学标准与 IndependentGlobalValidator Gate 11 (TIP-03) 完全同构。

    Args:
        candidate: 候选放置 (字典或 Placement)。
        placements: 已放置列表 (字典或 Placement 列表)。
        container_length: 容器内长 cL (米)。
        min_safety_factor: 最小倾覆力矩安全系数 (默认 1.50)。
        spatial_index: 可选的空间哈希索引加速查询。
        epsilon: 几何容差。

    Returns:
        (is_ok, safety_factor, reason): is_ok=True 表示倾覆稳定或有充分前向阻挡支撑。
    """
    cand = normalize_box(candidate)
    dx, dy, dz = cand["dx"], cand["dy"], cand["dz"]

    if dz <= 1e-6:
        return True, 999.0, None

    # 1. 固有自稳安全系数: SF = 2.0 * dx / dz (0.5g 减速工况下重心投影落在底面内)
    sf = (2.0 * dx) / dz
    if sf >= min_safety_factor - epsilon:
        return True, sf, None

    # 2. 贴近集装箱门侧 (+X 边界), 柜门物理结构提供硬阻挡
    if cand["x"] + dx >= container_length - DOOR_MARGIN_M - epsilon:
        return True, sf, None

    # 3. 检查前方 (+X 方向) 是否有紧密贴靠的支撑货物
    target_x = cand["x"] + dx
    min_y_ov = MIN_OVERLAP_RATIO * dy
    min_z_ov = MIN_OVERLAP_RATIO * dz

    if spatial_index is not None and len(spatial_index) > 0:
        try:
            from ..geometry.aabb import AABB
            query_aabb = AABB(
                min_x=target_x - FORWARD_GAP_TOL_M - 0.01,
                min_y=cand["y"] - 0.05,
                min_z=cand["z"] - 0.05,
                max_x=target_x + FORWARD_GAP_TOL_M + 0.01,
                max_y=cand["y"] + dy + 0.05,
                max_z=cand["z"] + dz + 0.05,
            )
            cand_ids = spatial_index.query_candidate_ids(query_aabb, expand_eps=0.05)
            check_list = []
            for cid in cand_ids:
                item = spatial_index.get_item(cid)
                if item is not None and item.data is not None:
                    check_list.append(item.data)
        except Exception:
            check_list = placements
    else:
        check_list = placements

    for raw_p in check_list:
        other = normalize_box(raw_p)
        if abs(other["x"] - target_x) <= FORWARD_GAP_TOL_M + epsilon:
            y_ov = min(cand["y"] + dy, other["y"] + other["dy"]) - max(cand["y"], other["y"])
            z_ov = min(cand["z"] + dz, other["z"] + other["dz"]) - max(cand["z"], other["z"])
            if y_ov >= min_y_ov - epsilon and z_ov >= min_z_ov - epsilon:
                return True, sf, None

    sku_id = cand.get("sku_id", "?")
    p_id = cand.get("placement_id", sku_id)
    return False, sf, (
        f"倾覆失稳风险: 箱体 {p_id} (SKU: {sku_id}) 无前向支撑且自身抗倾覆裕度不足 (SF={sf:.2f} < {min_safety_factor:.2f})"
    )
