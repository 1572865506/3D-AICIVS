"""产品交付默认选项与策略档映射（server / 验收脚本共用的唯一入口）。

背景：门区安全默认值此前写在 server.py 里（刚性封门件 → confine，
刚性封门薄板 → 0.25m 台阶），验收脚本若要模拟“产品真实交付”只能复制一遍。
本模块把这段语义收成单一实现，并支持按策略档生成不同约束组合：

- SAFETY_FIRST（或 policy=None）：封门件门区限定 + 薄板门端 0.25m 台阶
- BALANCED：仅封门件归位，不做门端台阶
- VOLUME_FIRST：不施加门端安全约束（装载率优先，需门禁告警）

算法层默认仍然是"全关"（直接调用 UnifiedSolver 不传 options 时行为不变）；
产品层/验收层显式调用本模块。

被谁调用：backend/server.py、scripts/run_acceptance.py、scripts/build_learning_dataset.py。
"""

from typing import Any, Dict, List, Optional

from backend.solver_v2.domain.models import PackingRole, ZoneType
from backend.solver_v2.evaluation.spec import (
    POLICY_BALANCED,
    POLICY_SAFETY_FIRST,
    POLICY_VOLUME_FIRST,
    get_policy,
)

THIN_PANEL_MAX_M = 0.12
THIN_PANEL_ASPECT_RATIO = 2.5
DEFAULT_DOOR_STEP_M = 0.25


def is_rigid_door(sku: Any) -> bool:
    """是否为"刚性封柜门件"（区域=门 或 角色含 DOOR_SEAL，且非弹性）。"""
    is_elastic = bool(
        getattr(getattr(sku, "quantity", None), "is_elastic", False)
        or getattr(sku, "is_elastic", False)
    )
    is_door = (
        getattr(sku, "target_zone", None) == ZoneType.DOOR
        or PackingRole.DOOR_SEAL in tuple(getattr(sku, "packing_roles", ()) or ())
    )
    return is_door and not is_elastic


def has_rigid_door(cargo_skus: List[Any]) -> bool:
    return any(is_rigid_door(s) for s in cargo_skus)


def has_thin_door(cargo_skus: List[Any]) -> bool:
    """刚性封门件中是否存在最薄边 ≤10cm 的薄板（开门倾覆高风险）。"""
    for sku in cargo_skus:
        if not is_rigid_door(sku):
            continue
        box = getattr(sku, "box", None)
        dims = [
            getattr(box, "x", 9.0) if box is not None else 9.0,
            getattr(box, "y", 9.0) if box is not None else 9.0,
            getattr(box, "z", 9.0) if box is not None else 9.0,
        ]
        _min = min(float(v) for v in dims)
        _max = max(float(v) for v in dims)
        if _min <= THIN_PANEL_MAX_M + 1e-6 or _max / max(_min, 1e-6) >= THIN_PANEL_ASPECT_RATIO:
            return True
    return False


def build_product_options(
    cargo_skus: List[Any],
    policy: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """按策略档 + 请求覆盖生成 solve options。

    payload 中的显式字段（doorSealConfine / doorStepDepth /
    doorOpenStabilityGlobal）优先级最高；policy 只决定默认值。
    """
    payload = payload or {}
    # None = 产品安全默认；显式传入未知档位时与评分侧一致回退 BALANCED
    key = POLICY_SAFETY_FIRST if policy is None else get_policy(policy).key
    rigid_door = has_rigid_door(cargo_skus)
    thin_door = has_thin_door(cargo_skus)

    if key == POLICY_VOLUME_FIRST:
        confine = False
        step = 0.0
    elif key == POLICY_BALANCED:
        confine = rigid_door
        step = 0.0
    else:  # SAFETY_FIRST / 未知档位 → 产品安全默认
        confine = rigid_door
        step = DEFAULT_DOOR_STEP_M if (
            thin_door and payload.get("doorOpenStability", True)
        ) else 0.0

    if "doorSealConfine" in payload:
        confine = bool(payload.get("doorSealConfine"))
    if "doorStepDepth" in payload:
        step = float(payload.get("doorStepDepth") or 0.0)

    # Phase B：低稳定纸箱的“同图案前向支撑墙”。
    # 产品默认只在无刚性封门件的货单开启；15-SKU（薄板封门）保持原安全路径，
    # 避免支撑墙改变门区容量与装载率。payload 显式值优先，便于 A/B/关闭。
    deferred = payload.get("deferredTippingAudit", not rigid_door)

    return {
        "door_open_stability": bool(payload.get("doorOpenStabilityGlobal", False)),
        "door_seal_confine": bool(confine),
        "door_step_depth": float(step),
        "deferred_tipping_audit": bool(deferred),
    }


__all__ = [
    "THIN_PANEL_MAX_M",
    "DEFAULT_DOOR_STEP_M",
    "is_rigid_door",
    "has_rigid_door",
    "has_thin_door",
    "build_product_options",
]
