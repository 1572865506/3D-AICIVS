"""货单特征抽取（自学习选择器的输入）。

特征必须满足三点：
1. 只依赖货单/柜体的结构化字段，不依赖求解结果；
2. 可解释（业务看得懂：SKU 数、请求体积比、是否封门薄板、是否多站…）；
3. 与策略档相关（薄板/封门 → 安全；单 SKU 大货 → 装载率）。

被谁调用：learning.selector（推理）、learning.train（训练）、数据构建脚本。
"""

import math
from typing import Any, Dict, List

from backend.solver_v2.evaluation.product import has_rigid_door, has_thin_door

FEATURE_NAMES = (
    "sku_count",
    "log_total_qty",
    "requested_volume_ratio",
    "rigid_share",
    "elastic_share",
    "has_rigid_door",
    "has_thin_panel",
    "has_fragile",
    "multi_stop",
    "stop_count",
    "payload_limited",
    "single_sku_dominant",
    "max_dim_ratio",
    "avg_pkg_volume",
    "container_len_norm",
    "container_width_norm",
    "container_height_norm",
)


def _required(sku: Any) -> int:
    return int(
        getattr(getattr(sku, "quantity", None), "required", 0)
        or getattr(sku, "quantity_required", 0)
        or 0
    )


def _is_elastic(sku: Any) -> bool:
    return bool(
        getattr(getattr(sku, "quantity", None), "is_elastic", False)
        or getattr(sku, "is_elastic", False)
    )


def extract_features(cargo_list: List[Any], container: Any) -> Dict[str, float]:
    """抽取固定顺序的特征字典（所有值均为有限浮点数）。"""
    cargo = list(cargo_list or [])
    total_qty = sum(_required(s) for s in cargo)
    rigid_qty = sum(_required(s) for s in cargo if not _is_elastic(s))
    elastic_qty = total_qty - rigid_qty

    req_vol = 0.0
    req_weight = 0.0
    max_dim = 0.0
    max_qty = 0
    stop_count = 0
    has_fragile = False
    for sku in cargo:
        qty = _required(sku)
        box = getattr(sku, "box", None)
        if box is not None:
            dims = (float(box.x), float(box.y), float(box.z))
            req_vol += dims[0] * dims[1] * dims[2] * qty
            max_dim = max(max_dim, *dims)
        req_weight += float(getattr(sku, "weight_kg", 0.0) or 0.0) * qty
        max_qty = max(max_qty, qty)
        if getattr(sku, "unload_stop", None) is not None:
            stop_count += 1
        text = (getattr(sku, "source_requirement_text", "") or "")
        if "易碎" in text or "不可压" in text:
            has_fragile = True

    container_vol = float(getattr(container, "volume", 0.0) or 0.0)
    payload_cap = float(getattr(container, "max_payload_kg", 0.0) or 0.0)

    feats = {
        "sku_count": float(len(cargo)),
        "log_total_qty": math.log10(total_qty + 1.0),
        "requested_volume_ratio": req_vol / max(1e-9, container_vol),
        "rigid_share": rigid_qty / max(1, total_qty),
        "elastic_share": elastic_qty / max(1, total_qty),
        "has_rigid_door": 1.0 if has_rigid_door(cargo) else 0.0,
        "has_thin_panel": 1.0 if has_thin_door(cargo) else 0.0,
        "has_fragile": 1.0 if has_fragile else 0.0,
        "multi_stop": 1.0 if stop_count > 0 else 0.0,
        "stop_count": float(stop_count),
        "payload_limited": 1.0 if (payload_cap > 0 and req_weight > payload_cap) else 0.0,
        "single_sku_dominant": 1.0 if (total_qty > 0 and max_qty / total_qty >= 0.6) else 0.0,
        "max_dim_ratio": max_dim / 1.5,
        "avg_pkg_volume": req_vol / max(1, total_qty),
        "container_len_norm": float(getattr(container, "Lx", 0.0) or 0.0) / 16.0,
        "container_width_norm": float(getattr(container, "Ly", 0.0) or 0.0) / 2.5,
        "container_height_norm": float(getattr(container, "Lz", 0.0) or 0.0) / 3.0,
    }
    return {k: float(feats.get(k, 0.0)) for k in FEATURE_NAMES}


def to_vector(features: Dict[str, float]) -> List[float]:
    return [float(features.get(name, 0.0)) for name in FEATURE_NAMES]


__all__ = ["FEATURE_NAMES", "extract_features", "to_vector"]
