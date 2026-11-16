"""HTTP 安全边界：静态资源白名单、CORS、可选 Bearer Token。

背景：默认的 SimpleHTTPRequestHandler 以仓库根目录为 document root，
会把 backend/、tests/、.git/、data/ 一起暴露；CORS 也是 *。本模块把
"只允许前端页面与前端资源"的规则收成可测试的纯函数。

被谁调用：backend/server.py（AICIVSRequestHandler.do_GET/do_HEAD）、tests。
"""

import hmac
import os
import posixpath
from typing import Optional
from urllib.parse import unquote, urlsplit

# 只开放真正需要浏览器直接访问的页面与前端资源
ALLOWED_EXACT = {
    "/",
    "/index.html",
    "/test_dashboard.html",
    "/algorithm_space.html",
    "/favicon.ico",
}
ALLOWED_PREFIXES = ("/frontend/",)


def normalize_static_path(path: str) -> Optional[str]:
    """返回规范化后的绝对路径；含穿越/反斜杠/空字节时返回 None。"""
    raw = urlsplit(path or "").path
    if not raw:
        return None
    decoded = unquote(raw)
    if "\x00" in decoded or "\\" in decoded:
        return None
    norm = posixpath.normpath(decoded)
    if not norm.startswith("/"):
        norm = "/" + norm
    return norm


def is_allowed_static_path(path: str, base_dir: str) -> bool:
    """静态白名单：只有页面文件与 /frontend/** 下的真实文件可被读取。"""
    norm = normalize_static_path(path)
    if norm is None:
        return False
    # 目录请求一律拒绝（避免目录列表）；根路径由 index.html 兜底
    if norm != "/" and norm.endswith("/"):
        return False

    base_real = os.path.realpath(base_dir)
    if norm == "/":
        target = os.path.join(base_real, "index.html")
        return os.path.isfile(target) and os.path.realpath(target).startswith(base_real + os.sep)
    if norm in ALLOWED_EXACT:
        target = os.path.join(base_real, norm.lstrip("/"))
        return os.path.isfile(target) and os.path.realpath(target).startswith(base_real + os.sep)

    for prefix in ALLOWED_PREFIXES:
        if not norm.startswith(prefix):
            continue
        root_real = os.path.realpath(os.path.join(base_real, prefix.strip("/")))
        target = os.path.realpath(os.path.join(base_real, norm.lstrip("/")))
        return (
            target.startswith(root_real + os.sep)
            and os.path.isfile(target)
        )
    return False


def allowed_cors_origin(origin: Optional[str],
                        extra_origins: Optional[str] = None) -> str:
    """同源/本机白名单；AICIVS_CORS_ORIGINS 可补充逗号分隔的显式来源。"""
    if not origin:
        return ""
    if origin.startswith("http://localhost:") or origin.startswith("http://127.0.0.1:"):
        return origin
    if origin in ("http://localhost", "http://127.0.0.1"):
        return origin
    extras = {
        item.strip().rstrip("/")
        for item in (extra_origins or os.environ.get("AICIVS_CORS_ORIGINS", "")).split(",")
        if item.strip()
    }
    return origin if origin.rstrip("/") in extras else ""


def is_authorized(auth_header: Optional[str], token: Optional[str]) -> bool:
    """未配置 token 时放行；配置后要求精确 Bearer Token。"""
    if not token:
        return True
    expected = f"Bearer {token}"
    return bool(auth_header) and hmac.compare_digest(auth_header, expected)


__all__ = [
    "ALLOWED_EXACT",
    "ALLOWED_PREFIXES",
    "normalize_static_path",
    "is_allowed_static_path",
    "allowed_cors_origin",
    "is_authorized",
]
