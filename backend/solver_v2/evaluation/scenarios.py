"""场景识别（Scenario Model）：从货单本身推断"这单该怕什么"。

场景不识别的后果在历史上有实证：同一套默认参数在 15-SKU 产线单上
门面 SF 只有 0.064（开门即倒），而在单 SKU 大货单上又因为过度保守
丢掉 30pp 装载率。所以策略档位必须由场景驱动，而不是全局一个默认值。

识别出的场景用于两处：
1. 选择默认评分策略档（安全优先 / 均衡 / 装载率优先）；
2. 在方案摘要里解释"为什么这个方案被推荐/被扣分"。

被谁调用：evaluate.py（评分编排）、server.py（决策默认策略）。
"""

from typing import Any, Dict, List, Optional

from backend.solver_v2.evaluation.spec import (
    POLICY_BALANCED,
    POLICY_SAFETY_FIRST,
    POLICY_VOLUME_FIRST,
    get_policy,
)

# 易碎/不可压/不可倒置等业务措辞（沿用 UI 现有需求文本约定）
_FRAGILE_KEYWORDS = ("易碎", "不可压", "不可倒", "不能倒", "FRAGILE", "防震")
_DOOR_KEYWORDS = ("封柜门", "封门", "靠门")
_THIN_PANEL_MAX_M = 0.10


def _is_elastic(sku: Any) -> bool:
    return bool(
        getattr(getattr(sku, "quantity", None), "is_elastic", False)
        or getattr(sku, "is_elastic", False)
    )


def _required(sku: Any) -> int:
    return int(
        getattr(getattr(sku, "quantity", None), "required", 0)
        or getattr(sku, "quantity_required", 0)
        or 0
    )


def _box_dims(sku: Any) -> Optional[tuple]:
    box = getattr(sku, "box", None)
    if box is None:
        return None
    try:
        return (float(box.x), float(box.y), float(box.z))
    except (TypeError, ValueError):
        return None


def _roles(sku: Any) -> List[str]:
    return [str(getattr(r, "value", r)).upper() for r in (getattr(sku, "packing_roles", ()) or ())]


def detect_scenario(cargo_list: List[Any], container: Any = None,
                    requested_policy: Optional[str] = None) -> Dict[str, Any]:
    """识别货单场景并给出建议策略档。

    返回：
    - scenario: 主场景名（DOOR_THIN_PANEL / FRAGILE / MULTI_STOP / ...）
    - flags: 结构化事实（供评分解释与前端展示）
    - reasons: 人话原因（为什么建议这个档位）
    - policy: 最终生效策略（显式请求优先）
    """
    cargo = list(cargo_list or [])
    flags: Dict[str, Any] = {
        "sku_count": len(cargo),
        "total_required": 0,
        "rigid_required": 0,
        "elastic_required": 0,
        "has_rigid_door": False,
        "has_thin_panel": False,
        "has_fragile": False,
        "multi_stop": False,
        "payload_limited": False,
        "single_sku_dominant": False,
        "requested_volume_ratio": 0.0,
    }
    reasons: List[str] = []
    rigid_door_ids: List[str] = []

    total_vol = 0.0
    req_weight = 0.0
    sku_counts: Dict[str, int] = {}

    for sku in cargo:
        req = _required(sku)
        elastic = _is_elastic(sku)
        flags["total_required"] += req
        if elastic:
            flags["elastic_required"] += req
        else:
            flags["rigid_required"] += req
        sku_counts[getattr(sku, "sku_id", "")] = req

        dims = _box_dims(sku)
        if dims is not None:
            total_vol += dims[0] * dims[1] * dims[2] * req
            if min(dims) <= _THIN_PANEL_MAX_M + 1e-6:
                flags["has_thin_panel"] = True
        req_weight += float(getattr(sku, "weight_kg", 0.0) or 0.0) * req

        text = (getattr(sku, "source_requirement_text", "") or "").upper()
        if any(k.upper() in text for k in _FRAGILE_KEYWORDS):
            flags["has_fragile"] = True
        if getattr(sku, "unload_stop", None) is not None:
            flags["multi_stop"] = True

        is_door = (
            "DOOR_SEAL" in _roles(sku)
            or str(getattr(getattr(sku, "target_zone", None), "value", "")).upper() == "DOOR"
            or any(k in (getattr(sku, "source_requirement_text", "") or "") for k in _DOOR_KEYWORDS)
        )
        if is_door and not elastic:
            flags["has_rigid_door"] = True
            rigid_door_ids.append(getattr(sku, "sku_id", "?"))

    container_vol = float(getattr(container, "volume", 0.0) or 0.0)
    if container_vol > 0:
        flags["requested_volume_ratio"] = round(total_vol / container_vol, 4)
    payload_cap = float(getattr(container, "max_payload_kg", 0.0) or 0.0)
    flags["payload_limited"] = bool(payload_cap > 0 and req_weight > payload_cap)

    max_qty = max(sku_counts.values()) if sku_counts else 0
    if flags["total_required"] > 0 and max_qty / flags["total_required"] >= 0.6:
        flags["single_sku_dominant"] = True

    # ---- 主场景判定（优先级 = 风险从高到低）----
    if flags["has_rigid_door"] and flags["has_thin_panel"]:
        scenario = "DOOR_THIN_PANEL"
        reasons.append(
            "含刚性封门薄板（厚≤10cm）：开门后门面整列可能前倾，"
            "安全权重上调（封门件须留在门区 + 门端台阶）"
        )
    elif flags["has_fragile"]:
        scenario = "FRAGILE"
        reasons.append("含易碎/不可压货物：安全权重上调，避免高堆与侧压")
    elif flags["multi_stop"]:
        scenario = "MULTI_STOP"
        reasons.append("多点卸货：装载顺序需与卸货站序反向，履约权重优先")
    elif flags["single_sku_dominant"]:
        scenario = "SINGLE_SKU_MASS"
        reasons.append("单 SKU 占绝对多数：策略差异小，以装载率与稳定性为主")
    elif flags["sku_count"] >= 8:
        scenario = "HETEROGENEOUS"
        reasons.append("多 SKU 混合货单：以装载率、墙体连续性与碎片化控制为主")
    else:
        scenario = "GENERAL"

    if flags["payload_limited"]:
        reasons.append("请求总重超过柜体载重：履约率不设硬门槛，但需提示未装原因")

    # ---- 策略档：显式请求优先；否则按场景给默认 ----
    if requested_policy:
        # 与评分侧使用同一归一化：未知档位回退 BALANCED，而不是原样透传
        policy = get_policy(requested_policy).key
    elif scenario in ("DOOR_THIN_PANEL", "FRAGILE"):
        policy = POLICY_SAFETY_FIRST
    elif scenario == "SINGLE_SKU_MASS":
        policy = POLICY_VOLUME_FIRST
    else:
        policy = POLICY_BALANCED

    return {
        "scenario": scenario,
        "flags": flags,
        "reasons": reasons,
        "policy": policy,
        "rigid_door_skus": rigid_door_ids,
    }


__all__ = ["detect_scenario"]
