# -*- coding: utf-8 -*-
"""
姿态合法性与上下文匹配纯函数 (Orientation & Context Legality)

与 IndependentGlobalValidator 第 4 维审计完全同构:
  - 校验箱体三维尺寸是否为基准 SKU 的合法三维置换
  - 判定放置朝向分类 (UPRIGHT, FLAT, SIDE)
  - 校验 OrientationPolicy 及 PlacementContext 上下文准入规则
    (例如仅在 TOP_FILL 上下文允许 FLAT 平放)

所有函数均为纯函数, 幂等无副作用。

被谁调用:
  - physics_kernel/__init__.py 统一导出
  - physics_kernel/unified_gate.py 聚合放置预检
  - placement_engine/ 任何放置引擎
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, Union
from ..domain.models import OrientationMode, PlacementContext
from .collision import GEOM_EPSILON, normalize_box


def check_orientation(
    candidate: Union[Dict[str, Any], Any],
    cargo_spec: Any,
    context: Optional[Any] = None,
    epsilon: float = GEOM_EPSILON,
) -> Tuple[bool, Optional[str]]:
    """检查候选箱体放置朝向是否合法。

    数学标准与 IndependentGlobalValidator._validate_orientations 完全同构。

    Args:
        candidate: 候选放置字典或 Placement 对象。
        cargo_spec: 对应的 CargoSKU 规格对象。
        context: 放置上下文 (PlacementContext)。若未提供，优先从 candidate 中提取。
        epsilon: 几何精度容差 (默认 1e-4)。

    Returns:
        (is_ok, reason): is_ok=True 表示姿态合规。
    """
    if cargo_spec is None:
        return True, None

    cand = normalize_box(candidate)
    dx, dy, dz = cand["dx"], cand["dy"], cand["dz"]
    base_box = getattr(cargo_spec, "box", None)
    if base_box is None:
        return True, None

    bx, by, bz = base_box.x, base_box.y, base_box.z

    # 1. 尺寸置换全等性校验
    dims_cand = sorted([dx, dy, dz])
    dims_base = sorted([bx, by, bz])
    if any(abs(dc - db) > epsilon for dc, db in zip(dims_cand, dims_base)):
        return False, (
            f"姿态尺寸不匹配: 候选尺寸 ({dx:.3f}, {dy:.3f}, {dz:.3f}) "
            f"非基准 SKU 尺寸 ({bx:.3f}, {by:.3f}, {bz:.3f}) 的合法排列"
        )

    policy = getattr(cargo_spec, "orientation_policy", None)
    if policy is None:
        return True, None

    ctx = context or cand.get("context") or PlacementContext.GENERAL

    # 2. 匹配朝向模式并核验准入上下文
    legal = False

    # (1) 正立 UPRIGHT: 高度对应 bz
    if abs(dz - bz) <= epsilon and (
        (abs(dx - bx) <= epsilon and abs(dy - by) <= epsilon)
        or (abs(dx - by) <= epsilon and abs(dy - bx) <= epsilon)
    ):
        rule = policy.rule_for(OrientationMode.UPRIGHT, ctx)
        if rule and rule.allows(policy.context_region(ctx), base_height=cand["z"]):
            legal = True

    # (2) 平放 FLAT: 高度对应 by
    if not legal and abs(dz - by) <= epsilon and (
        (abs(dx - bx) <= epsilon and abs(dy - bz) <= epsilon)
        or (abs(dx - bz) <= epsilon and abs(dy - bx) <= epsilon)
    ):
        rule = policy.rule_for(OrientationMode.FLAT, ctx)
        if rule and rule.allows(policy.context_region(ctx), base_height=cand["z"]):
            legal = True

    # (3) 侧放 SIDE: 高度对应 bx
    if not legal and abs(dz - bx) <= epsilon and (
        (abs(dx - by) <= epsilon and abs(dy - bz) <= epsilon)
        or (abs(dx - bz) <= epsilon and abs(dy - by) <= epsilon)
    ):
        rule = policy.rule_for(OrientationMode.SIDE, ctx)
        if rule and rule.allows(policy.context_region(ctx), base_height=cand["z"]):
            legal = True

    if not legal:
        sku_id = getattr(cargo_spec, "sku_id", cand.get("sku_id", "?"))
        return False, f"SKU {sku_id} 放置朝向 ({dx:.3f}x{dy:.3f}x{dz:.3f}) 在上下文 {ctx} 下不被允许"

    return True, None
