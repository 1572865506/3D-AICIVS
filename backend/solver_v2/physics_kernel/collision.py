# -*- coding: utf-8 -*-
"""
碰撞检测纯函数 (Collision & Bounds Detection)

与 IndependentGlobalValidator 第 1、2 维审计完全同构:
  - 容器边界越界检查 (OUT_OF_BOUNDS)
  - 箱体间 3D AABB 穿透检查 (COLLISION_OVERLAP)

所有函数均为幂等纯函数, 无副作用。
支持输入字典或 Placement 实体模型。

被谁调用:
  - physics_kernel/__init__.py 统一导出
  - physics_kernel/unified_gate.py 聚合放置预检
  - placement_engine/ 任何放置引擎
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

# 全局几何精度常量 (与验证器保持 1e-4 米一致)
GEOM_EPSILON: float = 1e-4


def normalize_box(item: Any) -> Dict[str, Any]:
    """统一将 Placement 对象或字典标准化为包含基础几何字段的字典。"""
    if isinstance(item, dict):
        return item
    pos = getattr(item, "position", None)
    ori = getattr(item, "orientation", None)
    return {
        "x": float(getattr(pos, "x", 0.0) if pos is not None else getattr(item, "x", 0.0)),
        "y": float(getattr(pos, "y", 0.0) if pos is not None else getattr(item, "y", 0.0)),
        "z": float(getattr(pos, "z", 0.0) if pos is not None else getattr(item, "z", 0.0)),
        "dx": float(getattr(ori, "dx", 0.0) if ori is not None else getattr(item, "dx", 0.0)),
        "dy": float(getattr(ori, "dy", 0.0) if ori is not None else getattr(item, "dy", 0.0)),
        "dz": float(getattr(ori, "dz", 0.0) if ori is not None else getattr(item, "dz", 0.0)),
        "sku_id": getattr(item, "sku_id", ""),
        "weight_kg": float(getattr(item, "weight_kg", 0.0)),
        "placement_id": str(getattr(item, "placement_id", "")),
        "context": getattr(item, "context", None),
    }


def check_no_collision(
    candidate: Union[Dict[str, Any], Any],
    placements: List[Union[Dict[str, Any], Any]],
    container_dims: Tuple[float, float, float],
    spatial_index: Optional[Any] = None,
    epsilon: float = GEOM_EPSILON,
) -> Tuple[bool, Optional[str]]:
    """检查候选放置是否无碰撞且严格在容器边界内。

    数学标准与 IndependentGlobalValidator._validate_bounds 和
    _validate_overlaps 完全同构。

    Args:
        candidate: 候选放置 (字典或 Placement)。需包含/对应 x, y, z, dx, dy, dz。
        placements: 已放置列表 (字典或 Placement 列表)。
        container_dims: (cL, cW, cH) 容器内部尺寸 (米)。
        spatial_index: 可选的 SpatialIndex 加速查询结构。
        epsilon: 几何精度容差 (默认 1e-4 米)。

    Returns:
        (is_ok, reason): is_ok=True 表示合法无违规。
    """
    cand = normalize_box(candidate)

    ok, reason = _check_bounds(cand, container_dims, epsilon)
    if not ok:
        return False, reason

    ok, reason = _check_overlap(cand, placements, spatial_index, epsilon)
    if not ok:
        return False, reason

    return True, None


def _check_bounds(
    candidate: Dict[str, Any],
    container_dims: Tuple[float, float, float],
    epsilon: float = GEOM_EPSILON,
) -> Tuple[bool, Optional[str]]:
    """容器边界越界检查。与验证器第 1 维审计同构。

    容差判断标准:
      x ∈ [-epsilon, cL + epsilon]
      y ∈ [-epsilon, cW + epsilon]
      z ∈ [-epsilon, cH + epsilon]
    """
    x, y, z = candidate["x"], candidate["y"], candidate["z"]
    dx, dy, dz = candidate["dx"], candidate["dy"], candidate["dz"]
    c_l, c_w, c_h = container_dims

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
    placements: List[Union[Dict[str, Any], Any]],
    spatial_index: Optional[Any] = None,
    epsilon: float = GEOM_EPSILON,
) -> Tuple[bool, Optional[str]]:
    """箱体间 3D AABB 穿透检查。与验证器第 2 维审计同构。

    两个 AABB 产生体积干涉当且仅当在 X, Y, Z 三个轴上的正重叠均大于容差:
      cx0 < px1 且 cx1 > px0
      cy0 < py1 且 cy1 > py0
      cz0 < pz1 且 cz1 > pz0
    """
    cx0 = candidate["x"] + epsilon
    cx1 = candidate["x"] + candidate["dx"] - epsilon
    cy0 = candidate["y"] + epsilon
    cy1 = candidate["y"] + candidate["dy"] - epsilon
    cz0 = candidate["z"] + epsilon
    cz1 = candidate["z"] + candidate["dz"] - epsilon

    # 若几何体积在容差收缩后退化，直接安全放行
    if cx1 <= cx0 or cy1 <= cy0 or cz1 <= cz0:
        return True, None

    # 使用 SpatialIndex 加速检索
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

    for raw_p in check_list:
        p = normalize_box(raw_p)
        px0 = p["x"] + epsilon
        px1 = p["x"] + p["dx"] - epsilon
        py0 = p["y"] + epsilon
        py1 = p["y"] + p["dy"] - epsilon
        pz0 = p["z"] + epsilon
        pz1 = p["z"] + p["dz"] - epsilon

        if cx0 < px1 and cx1 > px0 and cy0 < py1 and cy1 > py0 and cz0 < pz1 and cz1 > pz0:
            sku_id = p.get("sku_id", "?")
            return False, f"与已放置箱 {sku_id} 发生穿透碰撞 (overlap)"

    return True, None
