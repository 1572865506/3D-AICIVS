# -*- coding: utf-8 -*-
"""
支撑面积比与空中悬空检查纯函数 (Support Ratio & Floating Check)

与 IndependentGlobalValidator 第 7 维审计及禁顶叠规则完全同构:
  - 地面层免检 (z <= 1e-3 永远返回 100% 充分支撑，核心铁律)
  - 接触面高度判定 (z 轴接触间隙 <= 1.0mm)
  - 支撑面积比计算 (与 candidate 底面积对比，默认 >= 0.70)
  - 下层箱体禁顶叠规则预检 (allow_stacking_on_top 与 stack_on_self)

所有函数均为纯函数, 幂等无副作用。

被谁调用:
  - physics_kernel/__init__.py 统一导出
  - physics_kernel/unified_gate.py 聚合放置预检
  - placement_engine/ 任何放置引擎
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union
from .collision import GEOM_EPSILON, normalize_box

Z_CONTACT_TOL: float = 1e-3


def check_support(
    candidate: Union[Dict[str, Any], Any],
    placements: List[Union[Dict[str, Any], Any]],
    min_support_ratio: float = 0.70,
    spatial_index: Optional[Any] = None,
    cargo_specs: Optional[Dict[str, Any]] = None,
    epsilon: float = GEOM_EPSILON,
) -> Tuple[bool, float, Optional[str]]:
    """检查候选放置的底部支撑是否充分，并核验下层箱体禁顶叠策略。

    数学标准与 IndependentGlobalValidator._validate_rules_and_physics 完全同构。

    Args:
        candidate: 候选放置 (字典或 Placement)。
        placements: 已放置列表 (字典或 Placement 列表)。
        min_support_ratio: 最小支撑面积比例 (默认 0.70，若 cargo_specs 中指定则优先采用规格)。
        spatial_index: 可选的空间哈希索引加速查询。
        cargo_specs: 可选的 SKU 元数据映射 (sku_id -> CargoSKU)。
        epsilon: 几何容差。

    Returns:
        (is_ok, support_ratio, reason): is_ok=True 表示支撑合规。
    """
    cand = normalize_box(candidate)
    cand_z = cand["z"]

    # 核心铁律: 地面层永远充分支撑 (无条件放行)
    if cand_z <= Z_CONTACT_TOL:
        return True, 1.0, None

    cand_x, cand_y = cand["x"], cand["y"]
    cand_dx, cand_dy = cand["dx"], cand["dy"]
    cand_area = cand_dx * cand_dy

    if cand_area <= 1e-6:
        return True, 1.0, None

    # 获取候选 SKU 专属要求
    cand_sku = cand.get("sku_id")
    effective_min_ratio = min_support_ratio
    if cargo_specs and cand_sku and cand_sku in cargo_specs:
        spec = cargo_specs[cand_sku]
        stack_policy = getattr(spec, "stacking_policy", None)
        if stack_policy is not None and getattr(stack_policy, "min_support_ratio", None) is not None:
            effective_min_ratio = float(stack_policy.min_support_ratio)

    # 查询下层直接接触箱体
    if spatial_index is not None and len(spatial_index) > 0:
        try:
            from ..geometry.aabb import AABB
            query_aabb = AABB(
                min_x=cand_x - 0.05,
                min_y=cand_y - 0.05,
                min_z=cand_z - Z_CONTACT_TOL - 0.01,
                max_x=cand_x + cand_dx + 0.05,
                max_y=cand_y + cand_dy + 0.05,
                max_z=cand_z + 0.01,
            )
            cand_ids = spatial_index.query_candidate_ids(query_aabb, expand_eps=0.05)
            candidates_list = []
            for cid in cand_ids:
                item = spatial_index.get_item(cid)
                if item is not None and item.data is not None:
                    candidates_list.append(item.data)
        except Exception:
            candidates_list = placements
    else:
        candidates_list = placements

    total_contact_area = 0.0

    for raw_p in candidates_list:
        p = normalize_box(raw_p)
        p_top_z = p["z"] + p["dz"]

        if abs(p_top_z - cand_z) <= Z_CONTACT_TOL:
            ix0 = max(cand_x, p["x"])
            ix1 = min(cand_x + cand_dx, p["x"] + p["dx"])
            iy0 = max(cand_y, p["y"])
            iy1 = min(cand_y + cand_dy, p["y"] + p["dy"])

            if ix1 > ix0 + epsilon and iy1 > iy0 + epsilon:
                overlap_area = (ix1 - ix0) * (iy1 - iy0)
                total_contact_area += overlap_area

                # 检查下层直接支撑箱体是否禁止顶叠 (NO_TOP_STACKING)
                if cargo_specs is not None:
                    p_sku_id = p.get("sku_id")
                    p_spec = cargo_specs.get(p_sku_id)
                    if p_spec is not None:
                        stack_policy = getattr(p_spec, "stacking_policy", None)
                        if stack_policy is not None:
                            allow_top = getattr(stack_policy, "allow_stacking_on_top", True)
                            if not allow_top:
                                allow_self = getattr(stack_policy, "stack_on_self", True)
                                if not allow_self:
                                    return False, 0.0, f"下层支撑箱 {p_sku_id} 属于绝对封顶件，严禁任何箱体堆叠在其上方"
                                elif cand_sku != p_sku_id:
                                    return False, 0.0, f"下层支撑箱 {p_sku_id} 禁止异品类杂货在其上方顶叠 (尝试放置 {cand_sku})"

    support_ratio = min(1.0, round(total_contact_area / cand_area, 6))

    if support_ratio < effective_min_ratio - epsilon:
        return False, support_ratio, (
            f"支撑面积不足: 实际支撑率 {support_ratio * 100:.1f}% < 要求 {effective_min_ratio * 100:.1f}%"
        )

    return True, support_ratio, None
