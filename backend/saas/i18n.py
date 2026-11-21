"""
用途: 提供 3D-AICIVS 商业化 SaaS 模块的双语 (zh-CN / en-US) 错误码与提示文案翻译。
输入: 错误/提示码 (code)、语言区域 (locale)、可选格式化参数 (**kwargs)。
输出: 本地化后的中文或英文提示字符串。
被谁调用: backend/saas/__init__.py 及后端 API 网关 (gateway_dev)。
"""

from __future__ import annotations

from typing import Any, Dict

DEFAULT_LOCALE = "zh-CN"

MESSAGES: Dict[str, Dict[str, str]] = {
    "AUTH_REQUIRED": {
        "zh-CN": "请先登录后再执行此操作。",
        "en-US": "Authentication is required to perform this action.",
    },
    "INVALID_TOKEN": {
        "zh-CN": "登录凭证无效或已过期，请重新登录。",
        "en-US": "Invalid or expired authentication token. Please sign in again.",
    },
    "TOKEN_EXPIRED": {
        "zh-CN": "登录会话已过期，请重新登录。",
        "en-US": "Your session has expired. Please sign in again.",
    },
    "INVALID_API_KEY": {
        "zh-CN": "无效的 API Key。",
        "en-US": "Invalid API Key.",
    },
    "INVALID_CREDENTIALS": {
        "zh-CN": "邮箱或密码错误。",
        "en-US": "Invalid email or password.",
    },
    "EMAIL_EXISTS": {
        "zh-CN": "该邮箱已注册，请直接登录。",
        "en-US": "An account with this email already exists.",
    },
    "INVALID_EMAIL": {
        "zh-CN": "邮箱格式不正确。",
        "en-US": "Invalid email address format.",
    },
    "WEAK_PASSWORD": {
        "zh-CN": "密码长度至少需要 8 位。",
        "en-US": "Password must be at least 8 characters long.",
    },
    "USER_NOT_FOUND": {
        "zh-CN": "用户不存在。",
        "en-US": "User not found.",
    },
    "QUOTA_EXCEEDED": {
        "zh-CN": "本月装柜计算次数及加油包额度已耗尽，请升级套餐或购买加油包。",
        "en-US": "Monthly solve quota and extra credits exhausted. Please upgrade your plan or purchase a credit pack.",
    },
    "SKU_LIMIT_EXCEEDED": {
        "zh-CN": "当前套餐单次最多支持 {max_skus} 个 SKU（本次请求 {sku_count} 个），请升级至专业版以解锁不限 SKU。",
        "en-US": "Your current plan supports up to {max_skus} SKUs per solve (requested {sku_count}). Upgrade to Pro for unlimited SKUs.",
    },
    "PRO_FEATURE_REQUIRED": {
        "zh-CN": "该功能（脏表导入 / 无水印导出 / 高阶原型算法）仅对专业版及以上套餐开放。",
        "en-US": "This feature (dirty table import / watermark-free export / advanced algorithm) requires a Pro plan or higher.",
    },
    "BUSINESS_FEATURE_REQUIRED": {
        "zh-CN": "3D 分享链接与多席位协作仅对商业版及以上套餐开放。",
        "en-US": "3D share links and multi-seat collaboration require a Business plan or higher.",
    },
    "ENTERPRISE_FEATURE_REQUIRED": {
        "zh-CN": "API Key 编程接入仅对企业版套餐开放。",
        "en-US": "API Key access requires an Enterprise plan.",
    },
    "EXPORT_NOT_ALLOWED": {
        "zh-CN": "免费版暂不支持导出装柜报表，请升级至专业版及以上套餐。",
        "en-US": "Report export is not available on the Free plan. Please upgrade to Pro or higher.",
    },
    "ORDER_NOT_FOUND": {
        "zh-CN": "订单不存在。",
        "en-US": "Order not found.",
    },
    "INVALID_ITEM": {
        "zh-CN": "无效的商品或套餐类型。",
        "en-US": "Invalid plan or credit pack item.",
    },
    "INVALID_CURRENCY": {
        "zh-CN": "不支持的结算币种，仅支持 CNY 或 USD。",
        "en-US": "Unsupported currency. Only CNY and USD are supported.",
    },
    "SHARE_LINK_NOT_FOUND": {
        "zh-CN": "分享链接不存在或已失效。",
        "en-US": "Share link not found or expired.",
    },
    "ORDER_PAID": {
        "zh-CN": "支付成功，权益已生效。",
        "en-US": "Payment confirmed and entitlements activated.",
    },
    "OK": {
        "zh-CN": "操作成功。",
        "en-US": "Success.",
    },
}


def normalize_locale(locale: str | None) -> str:
    """
    用途: 将输入语言标识标准化为 "zh-CN" 或 "en-US"。
    输入: locale (str | None) - 原始语言标识，如 "zh"、"en-US"、"zh_CN"。
    输出: 标准化语言代码 ("zh-CN" 或 "en-US")。
    被谁调用: i18n.t() 及前端偏好设置处理。
    """
    if not locale:
        return DEFAULT_LOCALE
    lower = str(locale).strip().lower().replace("_", "-")
    if lower.startswith("en"):
        return "en-US"
    if lower.startswith("zh"):
        return "zh-CN"
    return DEFAULT_LOCALE


class _SafeFormatDict(dict):
    """格式化占位符缺失时保留原占位符，避免 KeyError。"""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def t(code: str, locale: str = "zh-CN", **kwargs: Any) -> str:
    """
    用途: 根据错误码或提示码返回对应语言的本地化文案。
    输入: code (str) - 提示码；locale (str) - 语言区域 ("zh-CN" / "en-US")；**kwargs - 模板插值参数。
    输出: 本地化文案字符串；若未知 code 则返回 code 本身。
    被谁调用: gateway_dev 错误响应构造及前端提示渲染。
    """
    norm_locale = normalize_locale(locale)
    entry = MESSAGES.get(code)
    if entry is None:
        return code
    template = entry.get(norm_locale) or entry.get(DEFAULT_LOCALE) or code
    if not kwargs:
        return template
    try:
        return template.format_map(_SafeFormatDict(**kwargs))
    except Exception:
        return template
