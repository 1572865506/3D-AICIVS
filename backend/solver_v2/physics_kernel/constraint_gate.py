# -*- coding: utf-8 -*-
"""
业务工艺规则与约束门禁纯函数 (Business Constraints Gate)

与 IndependentGlobalValidator 第 3、5、6 维审计完全同构:
  - 容器总有效载重核限 (Payload Capacity)
  - 严格仅限地面放置规则 (Floor-Only Stacking, 支持同品类合规自叠)
  - 最大垂直堆叠层数限制 (Max Stack Layers, 基于精确接触 DAG 最长链计算)
  - 门区隔离与硬边界封锁 (Door Zone Lockout / Forbidden Zone)

所有函数均为纯函数, 幂等无副作用。

被谁调用:
  - physics_kernel/__init__.py 统一导出
  - physics_kernel/unified_gate.py 聚合放置预检
  - placement_engine/ 任何放置引擎
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union
from ..domain.models import ZoneType, PackingRole
from .collision import GEOM_EPSILON, normalize_box

Z_CONTACT_TOL: float = 1e-3


def compute_stack_column_depth(
    cand: Dict[str, Any],
    placements: List[Dict[str, Any]],
    epsilon: float = GEOM_EPSILON,
) -> int:
    """计算候选箱体在同 SKU 垂直堆叠链中的真实层数深度 (含自身)。

    数学标准与 IndependentGlobalValidator._compute_stack_column_depth 完全同构。
    """
    cand_sku = cand.get("sku_id")
    curr_z = cand["z"]
    if curr_z <= Z_CONTACT_TOL:
        return 1

    depth = 1
    chk_z = curr_z
    chk_box = cand

    visited_levels = 0
    max_iter = 50

    while chk_z > Z_CONTACT_TOL and visited_levels < max_iter:
        visited_levels += 1
        found_lower = None

        for raw_p in placements:
            p = normalize_box(raw_p)
            if p.get("sku_id") != cand_sku:
                continue

            p_top_z = p["z"] + p["dz"]
            if abs(p_top_z - chk_z) <= Z_CONTACT_TOL:
                ox = min(chk_box["x"] + chk_box["dx"], p["x"] + p["dx"]) - max(chk_box["x"], p["x"])
                if ox > epsilon:
                    oy = min(chk_box["y"] + chk_box["dy"], p["y"] + p["dy"]) - max(chk_box["y"], p["y"])
                    if oy > epsilon:
                        contact_area = ox * oy
                        cand_area = chk_box["dx"] * chk_box["dy"]
                        # 至少有 10% 面积交叠判定为直接同类承托
                        if contact_area >= 0.10 * cand_area:
                            found_lower = p
                            break

        if found_lower is not None:
            depth += 1
            chk_z = found_lower["z"]
            chk_box = found_lower
        else:
            break

    return depth


def check_business_constraints(
    candidate: Union[Dict[str, Any], Any],
    placements: List[Union[Dict[str, Any], Any]],
    cargo_spec: Any,
    container_spec: Any,
    current_payload_weight: float = 0.0,
    door_zone_length: float = 0.0,
    has_door_skus: bool = False,
    rear_zone_length: float = 0.0,
    epsilon: float = GEOM_EPSILON,
) -> Tuple[bool, Optional[str]]:
    """聚合核验业务与工艺约束。

    数学标准与 IndependentGlobalValidator 第 3, 5, 6 维完全同构。

    Args:
        candidate: 候选放置 (字典或 Placement)。
        placements: 已放置列表 (字典或 Placement 列表)。
        cargo_spec: 候选箱对应的 CargoSKU 对象。
        container_spec: ContainerSpec 对象。
        current_payload_weight: 当前已装入总重量 (kg)。
        door_zone_length: 门区预留长度 (米)。
        has_door_skus: 是否存在门区专用货物。
        rear_zone_length: 尾部预留长度 (米)。
        epsilon: 几何容差。

    Returns:
        (is_ok, reason): is_ok=True 表示业务规则合规。
    """
    cand = normalize_box(candidate)
    cand_weight = cand.get("weight_kg", 0.0)
    cand_x = cand["x"]
    cand_z = cand["z"]
    cand_dx = cand["dx"]

    # 1. 车辆/集装箱总有效载重核限 (Payload Capacity)
    max_payload = getattr(container_spec, "max_payload_kg", 0.0)
    if max_payload > 0:
        if current_payload_weight + cand_weight > max_payload + epsilon:
            return False, (
                f"总载重超限: 当前放入后总重 {current_payload_weight + cand_weight:.1f}kg > 额定载重 {max_payload:.1f}kg"
            )

    sku_id = getattr(cargo_spec, "sku_id", cand.get("sku_id", "?"))
    inner_dim = getattr(container_spec, "inner_dim", None)
    c_lx = getattr(inner_dim, "x", getattr(container_spec, "length", 12.0))

    # 2. 区域隔离与禁入规则
    door_start = max(0.0, c_lx - door_zone_length)

    # 2.1 Explicit forbidden zones
    cargo_profile = getattr(cargo_spec, "cargo_profile", None)
    if cargo_profile is not None:
        zone_policy = getattr(cargo_profile, "zone_policy", None)
        if zone_policy is not None:
            forbidden = getattr(zone_policy, "forbidden", ())
            if ZoneType.DOOR in forbidden and (cand_x + cand_dx > door_start + epsilon):
                return False, f"Placement (SKU: {sku_id}) 违反显式门区禁入限制 (DOOR)"
            if ZoneType.REAR in forbidden and (cand_x <= rear_zone_length + epsilon):
                return False, f"Placement (SKU: {sku_id}) 违反显式尾部禁入限制 (REAR)"

    # 2.2 Door Zone Lockout (非门区专用件不可进入门区)
    if has_door_skus and door_zone_length > 0.05:
        target_zone = getattr(cargo_spec, "target_zone", None)
        packing_roles = getattr(cargo_spec, "packing_roles", ())
        is_door_allowed = (
            target_zone == ZoneType.DOOR
            or PackingRole.DOOR_SEAL in packing_roles
            or (
                cargo_profile is not None
                and zone_policy is not None
                and (ZoneType.DOOR in zone_policy.allowed or ZoneType.DOOR in zone_policy.preferred)
            )
        )
        if not is_door_allowed and (cand_x + cand_dx > door_start + epsilon):
            return False, f"普通货物 {sku_id} 越界进入门区专属隔离段 [X > {door_start:.3f}m]"

    # 3. 落地与堆叠规则
    stack_policy = getattr(cargo_spec, "stacking_policy", None)
    if stack_policy is not None:
        must_floor = getattr(stack_policy, "must_be_on_floor", False)
        max_layers = getattr(stack_policy, "max_stack_layers", None)
        if max_layers is None:
            max_layers = getattr(stack_policy, "max_layers", None)

        # 3.1 Floor Only 规则
        if must_floor and cand_z > epsilon:
            max_allowed = max_layers or 1
            # 检查支撑该箱体的下层箱子
            direct_supports = []
            has_foreign_support = False

            for raw_p in placements:
                p = normalize_box(raw_p)
                p_top_z = p["z"] + p["dz"]
                if abs(p_top_z - cand_z) <= Z_CONTACT_TOL:
                    ox = min(cand_x + cand_dx, p["x"] + p["dx"]) - max(cand_x, p["x"])
                    if ox > epsilon:
                        oy = min(cand["y"] + cand["dy"], p["y"] + p["dy"]) - max(cand["y"], p["y"])
                        if oy > epsilon and (ox * oy) >= 0.10 * (cand_dx * cand["dy"]):
                            direct_supports.append(p)
                            if p.get("sku_id") != sku_id:
                                has_foreign_support = True

            same_sku_depth = compute_stack_column_depth(cand, [normalize_box(p) for p in placements], epsilon)

            if has_foreign_support or not direct_supports or max_allowed <= 1 or same_sku_depth > max_allowed:
                return False, (
                    f"地面专属件 {sku_id} 必须落地: 置于 z={cand_z:.3f}m, "
                    f"层数={same_sku_depth}, 允许上限={max_allowed}, 异类底托={has_foreign_support}"
                )

        # 3.2 Max Stack Layers 规则 (即使未勾选 must_be_on_floor，也受垂直层数限制)
        if max_layers is not None and max_layers > 0:
            stack_depth = compute_stack_column_depth(cand, [normalize_box(p) for p in placements], epsilon)
            if stack_depth > max_layers:
                return False, (
                    f"同品类垂直堆码层数超限: 当前第 {stack_depth} 层 > 允许上限 {max_layers} 层"
                )

    return True, None
