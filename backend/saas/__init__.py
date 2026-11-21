"""
用途: 商业化 SaaS 核心底座包入口，统一导出套餐定义、SQLite 存储引擎、鉴权工具与双语 i18n 文案。
输入: 无（包级导出）。
输出: PLANS、CREDIT_PACKS、SaaSStore、auth 函数及 i18n t() 函数。
被谁调用: backend/server.py 或 gateway_dev 对接层。
"""

from __future__ import annotations

from .auth import (
    authenticate_request,
    create_jwt,
    hash_password,
    verify_jwt,
    verify_password,
)
from .i18n import MESSAGES, normalize_locale, t
from .plans import (
    CREDIT_PACKS,
    PLANS,
    SUPPORTED_CURRENCIES,
    get_credit_pack,
    get_plan,
    list_catalog,
)
from .store import SaaSStore

__all__ = [
    "PLANS",
    "CREDIT_PACKS",
    "SUPPORTED_CURRENCIES",
    "get_plan",
    "get_credit_pack",
    "list_catalog",
    "SaaSStore",
    "hash_password",
    "verify_password",
    "create_jwt",
    "verify_jwt",
    "authenticate_request",
    "MESSAGES",
    "normalize_locale",
    "t",
]
