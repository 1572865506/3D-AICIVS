"""
用途: 提供纯标准库 PBKDF2-HMAC-SHA256 密码哈希校验、无状态 HMAC-SHA256 JWT 签发验签及统一请求认证。
输入: 明文密码、JWT 载荷与密钥、HTTP 请求头及 SaaSStore 实例。
输出: 密码哈希串、JWT 字符串、验签载荷及 (user_dict, error_code) 认证结果。
被谁调用: backend/saas/__init__.py 及后端 API 网关 (gateway_dev)。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Dict, Mapping, Optional, Tuple

from .store import SaaSStore

_PBKDF2_ITERATIONS = 120_000
_FALLBACK_JWT_SECRET = secrets.token_hex(32)


def _get_jwt_secret(secret: Optional[str] = None) -> bytes:
    raw = secret or os.environ.get("AICIVS_JWT_SECRET") or _FALLBACK_JWT_SECRET
    return raw.encode("utf-8")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def hash_password(password: str, iterations: int = _PBKDF2_ITERATIONS) -> str:
    """
    用途: 使用 PBKDF2-HMAC-SHA256 生成带随机盐的密码哈希。
    输入: password (str) - 用户明文密码；iterations (int) - 迭代次数。
    输出: 格式为 "pbkdf2_sha256$<iterations>$<salt_b64>$<dk_b64>" 的哈希字符串。
    被谁调用: gateway_dev 用户注册接口。
    """
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return (
        f"pbkdf2_sha256${iterations}$"
        f"{_b64url_encode(salt)}${_b64url_encode(dk)}"
    )


def verify_password(password: str, password_hash: str) -> bool:
    """
    用途: 使用恒定时间比对校验明文密码与存储哈希是否匹配。
    输入: password (str)、password_hash (str)。
    输出: 匹配返回 True，否则返回 False。
    被谁调用: gateway_dev 用户登录接口。
    """
    try:
        scheme, iter_str, salt_b64, dk_b64 = password_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iter_str)
        salt = _b64url_decode(salt_b64)
        expected_dk = _b64url_decode(dk_b64)
    except Exception:
        return False
    actual_dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual_dk, expected_dk)


def create_jwt(
    payload: Dict[str, Any],
    expires_in: int = 7 * 86400,
    secret: Optional[str] = None,
) -> str:
    """
    用途: 签发无状态 HS256 JWT。
    输入: payload (Dict[str, Any]) - 自定义声明（如 {"sub": user_id}）；expires_in (int) - 过期秒数；secret (Optional[str])。
    输出: 标准三段式 JWT 字符串。
    被谁调用: gateway_dev 登录/注册响应签发。
    """
    now = int(time.time())
    claims = dict(payload)
    claims.setdefault("iat", now)
    if expires_in > 0:
        claims.setdefault("exp", now + int(expires_in))

    header_b64 = _b64url_encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8")
    )
    payload_b64 = _b64url_encode(
        json.dumps(claims, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(_get_jwt_secret(secret), signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url_encode(sig)}"


def verify_jwt(
    token: str, secret: Optional[str] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    用途: 校验 HS256 JWT 签名与有效期。
    输入: token (str)、secret (Optional[str])。
    输出: (claims_dict, error_code) 元组；有效时 error_code 为 None，失效时返回 "INVALID_TOKEN" 或 "TOKEN_EXPIRED"。
    被谁调用: authenticate_request() 及 gateway_dev。
    """
    if not token or "." not in token:
        return None, "INVALID_TOKEN"
    parts = token.strip().split(".")
    if len(parts) != 3:
        return None, "INVALID_TOKEN"
    header_b64, payload_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(_get_jwt_secret(secret), signing_input, hashlib.sha256).digest()
    try:
        actual_sig = _b64url_decode(sig_b64)
    except Exception:
        return None, "INVALID_TOKEN"
    if not hmac.compare_digest(actual_sig, expected_sig):
        return None, "INVALID_TOKEN"

    try:
        header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
        claims = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        return None, "INVALID_TOKEN"

    if header.get("alg") != "HS256" or not isinstance(claims, dict):
        return None, "INVALID_TOKEN"

    exp = claims.get("exp")
    if exp is not None and int(time.time()) > int(exp):
        return None, "TOKEN_EXPIRED"
    return claims, None


def _get_header(headers: Mapping[str, str], target: str) -> Optional[str]:
    """大小写不敏感地从字典或 HTTPMessage 请求头提取指定字段。"""
    target_lower = target.lower()
    for key, val in headers.items():
        if str(key).lower() == target_lower:
            return str(val).strip()
    return None


def authenticate_request(
    headers: Mapping[str, str], store: SaaSStore
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    用途: 统一解析 HTTP 请求头中的 Bearer JWT 或 X-API-Key 并加载对应用户。
    输入: headers (Mapping[str, str]) - HTTP 请求头；store (SaaSStore) - 存储实例。
    输出: (user_dict, error_code) 元组；成功时 error_code 为 None，失败时 user_dict 为 None。
    被谁调用: gateway_dev 所有受保护 API 路由。
    """
    if not headers:
        return None, "AUTH_REQUIRED"

    auth_header = _get_header(headers, "Authorization")
    if auth_header:
        parts = auth_header.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            claims, err = verify_jwt(parts[1])
            if err is not None or claims is None:
                return None, err or "INVALID_TOKEN"
            user_id = claims.get("sub")
            if not user_id:
                return None, "INVALID_TOKEN"
            user = store.get_user_by_id(str(user_id))
            if user is None:
                return None, "INVALID_TOKEN"
            return user, None
        return None, "INVALID_TOKEN"

    api_key = _get_header(headers, "X-API-Key")
    if api_key:
        user = store.verify_api_key(api_key)
        if user is None:
            return None, "INVALID_API_KEY"
        return user, None

    return None, "AUTH_REQUIRED"
