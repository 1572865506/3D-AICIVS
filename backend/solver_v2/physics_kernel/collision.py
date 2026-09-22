# -*- coding: utf-8 -*-
"""
碰撞检测纯函数 (Collision Detection)

与 IndependentGlobalValidator 第 2 维审计同构:
  - 容器边界越界检查 (OUT_OF_BOUNDS)
  - 箱体间 AABB 穿透检查 (COLLISION_OVERLAP)

所有函数为纯函数, 无副作用, 不含任何货物类型判断。

被谁调用:
  - physics_kernel/__init__.py 统一导出
  - placement_engine/sequential_placer.py 放置前预检
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# 全局精度常量 (与验证器一致)
GEOM_EPSILON: float = 1e-4


def check_no_collision(
    candidate: Dict[str, Any],
    placements: List[Dict[str, Any]],
    container_dims: Tuple[float, float, float],
    spatial_index: Optional[Any] = None,
    epsilon: float = GEOM_EPSILON,
) -> Tuple[bool, Optional[str]]:
    """检查候选放置是否无碰撞且在容器边界内。

    数学标准与 IndependentGlobalValidator._validate_bounds 和
    _validate_overlaps 完全同构。

    Args:
        candidate: 候选放置字典, 需包含 x, y, z, dx, dy, dz 键。
        placements: 已放置列表。
        container_dims: (cL, cW, cH) 容器内部尺寸 (米)。
        spatial_index: 可选的 SpatialIndex 加速查询。
        epsilon: 几何精度容差 (默认 1e-4 米)。

    Returns:
        (is_ok, reason): is_ok=True 表示无碰撞且在边界内。
    """
    ok, reason = _check_bounds(candidate, container_dims, epsilon)
    if not ok:
        return False, reason

    ok, reason = _check_overlap(candidate, placements, spatial_index, epsilon)
    if not ok:
        return False, reason

    return True, None


def _check_bounds(
    candidate: Dict[str, Any],
    container_dims: Tuple[float, float, float],
    epsilon: float = GEOM_EPSILON,
) -> Tuple[bool, Optional[str]]:
    """容器边界越界检查。与验证器第 1 维审计同构。

    收缩候选盒边缘 epsilon 后判断是否在容器范围内:
      x ∈ [-epsilon, cL + epsilon]
      y ∈ [-epsilon, cW + epsilon]
      z ∈ [-epsilon, cH + epsilon]
    """
    x, y, z = candidate["x"], candidate["y"], candidate["z"]
    dx, dy, dz = candidate["dx"], candidate["dy"], candidate["dz"]
    c_l, c_w, c_h = container_dims

    # 候选盒的最大坐标
    x1 = x + dx
    y1 = y + dy
    z1 = z + dz

    if x < -epsilon or y < -epsilon or z < -epsilon:
        return False, f"负坐标越界: ({x:.4f}, {y:.4f}, {z:.4f})"

    if x1 > c_l + epsilon:
        return False, f"X轴越界: x+dx={x1:.4f} > cL={c_l:.4f}"

    if y1 > c_w + epsilon:
        return False, f"Y轴越界: y+dy={y1:.4f} > cW={c_w:.4f}"

    if z1 > c_h + epsilon:
        return False, f"Z轴越界: z+dz={z1:.4f} > cH={c_h:.4f}"

    return True, None


def _check_overlap(
    candidate: Dict[str, Any],
    placements: List[Dict[str, Any]],
    spatial_index: Optional[Any] = None,
    epsilon: float = GEOM_EPSILON,
) -> Tuple[bool, Optional[str]]:
    """箱体间 AABB 穿透检查。与验证器第 2 维审计同构。

    两个 AABB 穿透当且仅当在 X, Y, Z 三个轴上都有正重叠:
      cx0 < px1 且 cx1 > px0  (X轴重叠)
      cy0 < py1 且 cy1 > py0  (Y轴重叠)
      cz0 < pz1 且 cz1 > pz0  (Z轴重叠)

    使用 epsilon 收缩避免将紧密贴合误判为穿透。
    """
    cx0 = candidate["x"] + epsilon
    cx1 = candidate["x"] + candidate["dx"] - epsilon
    cy0 = candidate["y"] + epsilon
    cy1 = candidate["y"] + candidate["dy"] - epsilon
    cz0 = candidate["z"] + epsilon
    cz1 = candidate["z"] + candidate["dz"] - epsilon

    # 使用 SpatialIndex 加速 (如果可用)
    if spatial_index is not None and len(spatial_index) > 0:
        try:
            from ..geometry.aabb import AABB
            query_aabb = AABB(
                min_x=candidate["x"],
                min_y=candidate["y"],
                min_z=candidate["z"],
                max_x=candidate["x"] + candidate["dx"],
                max_y=candidate["y"] + candidate["dy"],
                max_z=candidate["z"] + candidate["dz"],
            )
            cand_ids = spatial_index.query_intersect(query_aabb, eps=epsilon)
            check_list = []
            for cid in cand_ids:
                item = spatial_index.get_item(cid)
                if item is not None and item.data is not None:
                    check_list.append(item.data)
        except Exception:
            check_list = placements
    else:
        check_list = placements

    for p in check_list:
        px0 = p["x"] + epsilon
        px1 = p["x"] + p["dx"] - epsilon
        py0 = p["y"] + epsilon
        py1 = p["y"] + p["dy"] - epsilon
        pz0 = p["z"] + epsilon
        pz1 = p["z"] + p["dz"] - epsilon

        if cx0 < px1 and cx1 > px0 and cy0 < py1 and cy1 > py0 and cz0 < pz1 and cz1 > pz0:
            sku_id = p.get("sku_id", "?")
            return False, f"与已放置箱 {sku_id} 发生穿透碰撞"

    return True, None
