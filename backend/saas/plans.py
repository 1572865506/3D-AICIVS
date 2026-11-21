"""
用途: 定义 3D-AICIVS 商业化 SaaS 订阅套餐 (PLANS) 与按次加油包 (CREDIT_PACKS)，提供双币种定价与目录查询接口。
输入: 套餐 ID (plan_id)、加油包 ID (pack_id)、可选币种过滤 (currency: "CNY" | "USD")。
输出: 套餐/加油包规格字典及标准化目录结构。
被谁调用: backend/saas/store.py、backend/saas/__init__.py 及后端 API 网关 (gateway_dev)。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

SUPPORTED_CURRENCIES = ("CNY", "USD")

PLANS: Dict[str, Dict[str, Any]] = {
    "free": {
        "id": "free",
        "name": {"zh-CN": "免费版", "en-US": "Free"},
        "prices": {"CNY": 0, "USD": 0},
        "billing_cycle": "monthly",
        "monthly_quota": 10,
        "max_skus": 15,
        "allow_export": False,
        "allow_dirty_import": False,
        "allow_advanced_algo": False,
        "allow_share_link": False,
        "allow_api_key": False,
        "watermark": True,
        "seats": 1,
    },
    "pro": {
        "id": "pro",
        "name": {"zh-CN": "专业版", "en-US": "Pro"},
        "prices": {"CNY": 249, "USD": 49},
        "billing_cycle": "monthly",
        "monthly_quota": 200,
        "max_skus": None,
        "allow_export": True,
        "allow_dirty_import": True,
        "allow_advanced_algo": True,
        "allow_share_link": False,
        "allow_api_key": False,
        "watermark": False,
        "seats": 1,
    },
    "business": {
        "id": "business",
        "name": {"zh-CN": "商业版", "en-US": "Business"},
        "prices": {"CNY": 1499, "USD": 169},
        "billing_cycle": "monthly",
        "monthly_quota": 1000,
        "max_skus": None,
        "allow_export": True,
        "allow_dirty_import": True,
        "allow_advanced_algo": True,
        "allow_share_link": True,
        "allow_api_key": False,
        "watermark": False,
        "seats": 5,
    },
    "enterprise": {
        "id": "enterprise",
        "name": {"zh-CN": "企业版", "en-US": "Enterprise"},
        "prices": {"CNY": 4999, "USD": 499},
        "billing_cycle": "monthly",
        "monthly_quota": 10000,
        "max_skus": None,
        "allow_export": True,
        "allow_dirty_import": True,
        "allow_advanced_algo": True,
        "allow_share_link": True,
        "allow_api_key": True,
        "watermark": False,
        "seats": 50,
    },
}

CREDIT_PACKS: Dict[str, Dict[str, Any]] = {
    "pack_30": {
        "id": "pack_30",
        "name": {"zh-CN": "30次加油包", "en-US": "30-Solve Credit Pack"},
        "prices": {"CNY": 99, "USD": 15},
        "credits": 30,
    },
    "pack_200": {
        "id": "pack_200",
        "name": {"zh-CN": "200次加油包", "en-US": "200-Solve Credit Pack"},
        "prices": {"CNY": 499, "USD": 75},
        "credits": 200,
    },
}


def get_plan(plan_id: str) -> Optional[Dict[str, Any]]:
    """
    用途: 根据套餐 ID 获取套餐配置副本。
    输入: plan_id (str) - 套餐标识，如 "free"、"pro"、"business"、"enterprise"。
    输出: 套餐配置字典副本；若不存在则返回 None。
    被谁调用: store.py、gateway_dev 计费与权限校验逻辑。
    """
    plan = PLANS.get(plan_id)
    return deepcopy(plan) if plan is not None else None


def get_credit_pack(pack_id: str) -> Optional[Dict[str, Any]]:
    """
    用途: 根据加油包 ID 获取按次加油包配置副本。
    输入: pack_id (str) - 加油包标识，如 "pack_30"、"pack_200"。
    输出: 加油包配置字典副本；若不存在则返回 None。
    被谁调用: store.py 订单创建与支付回调逻辑。
    """
    pack = CREDIT_PACKS.get(pack_id)
    return deepcopy(pack) if pack is not None else None


def _format_catalog_item(item: Dict[str, Any], currency: Optional[str]) -> Dict[str, Any]:
    """按指定币种格式化单个商品条目。"""
    entry = deepcopy(item)
    if currency:
        curr = currency.upper()
        if curr not in SUPPORTED_CURRENCIES:
            raise ValueError(f"Unsupported currency: {currency}")
        entry["currency"] = curr
        entry["price"] = entry["prices"][curr]
    return entry


def list_catalog(currency: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """
    用途: 列出全部商业化订阅套餐与按次加油包目录。
    输入: currency (Optional[str]) - 可选币种 ("CNY" 或 "USD")；传入时会附加 price/currency 字段。
    输出: {"plans": [...], "credit_packs": [...]} 字典。
    被谁调用: 商业化目录查询 API (gateway_dev)。
    """
    plans = [_format_catalog_item(item, currency) for item in PLANS.values()]
    packs = [_format_catalog_item(item, currency) for item in CREDIT_PACKS.values()]
    return {"plans": plans, "credit_packs": packs}
