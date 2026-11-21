"""
用途: 基于纯 Python 标准库 sqlite3 的 SaaS 持久化存储层，管理用户、月度配额账本、双币种订单、3D 分享链接与 API Key。
输入: 数据库路径 db_path (默认读取 AICIVS_SAAS_DB 或 data/saas.db) 及业务操作参数。
输出: 用户、配额、订单、分享链接及 API Key 的结构化字典与原子校验结果。
被谁调用: backend/saas/auth.py、backend/saas/__init__.py 及后端 API 网关 (gateway_dev)。
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .plans import PLANS, SUPPORTED_CURRENCIES, get_credit_pack, get_plan

_STANDARD_ALGO_MODES = frozenset({"", "standard", "default", "unified", "unified_solver"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _current_month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class SaaSStore:
    """
    用途: 线程安全的 SQLite SaaS 数据与配额账本引擎。
    输入: db_path (Optional[str | Path]) - SQLite 文件路径或 ":memory:"。
    输出: 提供用户管理、配额原子扣减、幂等支付回调、分享链接与 API Key 管理方法。
    被谁调用: gateway_dev 初始化单例及单元测试。
    """

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        resolved = db_path or os.environ.get("AICIVS_SAAS_DB") or "data/saas.db"
        self.db_path = str(resolved)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            if self.db_path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
                    region TEXT NOT NULL DEFAULT 'CN', locale TEXT NOT NULL DEFAULT 'zh-CN',
                    unit_system TEXT NOT NULL DEFAULT 'metric', plan_id TEXT NOT NULL DEFAULT 'free',
                    extra_credits INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS usage_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, month_key TEXT NOT NULL,
                    delta INTEGER NOT NULL, source TEXT NOT NULL, sku_count INTEGER NOT NULL DEFAULT 0,
                    algorithm_mode TEXT NOT NULL DEFAULT 'standard', meta_json TEXT, created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
                CREATE INDEX IF NOT EXISTS idx_usage_user_month ON usage_ledger(user_id, month_key);
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, item_type TEXT NOT NULL,
                    item_id TEXT NOT NULL, currency TEXT NOT NULL, amount REAL NOT NULL,
                    provider TEXT NOT NULL, provider_ref TEXT, status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL, paid_at TEXT, FOREIGN KEY (user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS share_links (
                    token TEXT PRIMARY KEY, user_id TEXT NOT NULL, job_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY (user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL,
                    key_prefix TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, last_used_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
                """
            )
            self._conn.commit()

    def close(self) -> None:
        """关闭数据库连接。"""
        with self._lock:
            self._conn.close()

    @staticmethod
    def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        return dict(row) if row is not None else None

    def create_user(
        self,
        email: str,
        password_hash: str,
        region: str = "CN",
        locale: str = "zh-CN",
        unit_system: str = "metric",
        plan_id: str = "free",
    ) -> Dict[str, Any]:
        """
        用途: 创建新注册用户记录。
        输入: email、password_hash、region、locale、unit_system、plan_id。
        输出: 新建用户的字典（含 id、plan_id、extra_credits 等）。
        被谁调用: gateway_dev 注册接口。
        """
        norm_email = email.strip().lower()
        if plan_id not in PLANS:
            raise ValueError(f"Unknown plan_id: {plan_id}")
        user_id = f"usr_{uuid.uuid4().hex[:16]}"
        now = _utc_now()
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO users (id, email, password_hash, region, locale, unit_system, plan_id, extra_credits, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
                    (user_id, norm_email, password_hash, region, locale, unit_system, plan_id, now),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError("EMAIL_EXISTS") from exc
        return self.get_user_by_id(user_id)  # type: ignore[return-value]

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """
        用途: 根据邮箱查询用户完整记录（含 password_hash 供登录校验）。
        输入: email (str)。
        输出: 用户字典或 None。
        被谁调用: gateway_dev 登录/注册接口。
        """
        norm_email = email.strip().lower()
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE email = ?", (norm_email,)).fetchone()
        return self._row_to_dict(row)

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        用途: 根据用户 ID 查询用户记录。
        输入: user_id (str)。
        输出: 用户字典或 None。
        被谁调用: auth.authenticate_request() 及配额/订单接口。
        """
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._row_to_dict(row)

    def update_user_prefs(
        self,
        user_id: str,
        region: Optional[str] = None,
        locale: Optional[str] = None,
        unit_system: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        用途: 更新用户的地区、语言或计量单位偏好。
        输入: user_id 及可选的 region、locale、unit_system。
        输出: 更新后的用户字典；若用户不存在则返回 None。
        被谁调用: gateway_dev 用户偏好设置接口。
        """
        updates, params = [], []
        for col, val in (("region", region), ("locale", locale), ("unit_system", unit_system)):
            if val is not None:
                updates.append(f"{col} = ?")
                params.append(val)
        if not updates:
            return self.get_user_by_id(user_id)
        params.append(user_id)
        with self._lock:
            self._conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
            self._conn.commit()
        return self.get_user_by_id(user_id)

    def _compute_quota_locked(self, user: Dict[str, Any], month_key: str) -> Dict[str, Any]:
        plan = get_plan(user["plan_id"]) or PLANS["free"]
        row = self._conn.execute(
            "SELECT COALESCE(SUM(delta), 0) AS used FROM usage_ledger "
            "WHERE user_id = ? AND month_key = ? AND source = 'monthly_plan'",
            (user["id"], month_key),
        ).fetchone()
        monthly_used = int(row["used"]) if row else 0
        monthly_quota = int(plan["monthly_quota"])
        monthly_remaining = max(0, monthly_quota - monthly_used)
        extra_credits = max(0, int(user.get("extra_credits", 0)))
        return {
            "plan_id": plan["id"],
            "month_key": month_key,
            "monthly_quota": monthly_quota,
            "monthly_used": monthly_used,
            "monthly_remaining": monthly_remaining,
            "extra_credits": extra_credits,
            "total_remaining": monthly_remaining + extra_credits,
            "max_skus": plan["max_skus"],
            "allow_export": plan["allow_export"],
            "allow_dirty_import": plan["allow_dirty_import"],
            "allow_advanced_algo": plan["allow_advanced_algo"],
            "allow_share_link": plan["allow_share_link"],
            "allow_api_key": plan["allow_api_key"],
            "watermark": plan["watermark"],
        }

    def get_quota_summary(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        用途: 查询用户当月套餐配额使用情况与加油包剩余次数。
        输入: user_id (str)。
        输出: 配额摘要字典（含 monthly_quota、monthly_used、extra_credits、total_remaining 等）；用户不存在返回 None。
        被谁调用: gateway_dev 配额查询接口及 check_and_consume_solve。
        """
        month_key = _current_month_key()
        with self._lock:
            user = self.get_user_by_id(user_id)
            return self._compute_quota_locked(user, month_key) if user is not None else None

    def check_and_consume_solve(
        self,
        user_id: str,
        sku_count: int,
        algorithm_mode: str = "standard",
        require_dirty_import: bool = False,
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        用途: 原子化校验用户套餐功能权限、SKU 上限及算力配额，并在通过后扣减 1 次额度。
        输入: user_id、sku_count、algorithm_mode、require_dirty_import。
        输出: (ok, error_code, quota_info) 三元组；失败时 ok=False 且 error_code 为 i18n 错误码。
        被谁调用: gateway_dev /api/solve 前置门禁。
        """
        month_key = _current_month_key()
        norm_mode = (algorithm_mode or "standard").strip().lower()
        with self._lock:
            user = self.get_user_by_id(user_id)
            if user is None:
                return False, "USER_NOT_FOUND", {}
            plan = get_plan(user["plan_id"]) or PLANS["free"]
            quota_info = self._compute_quota_locked(user, month_key)

            max_skus = plan.get("max_skus")
            if max_skus is not None and int(sku_count) > int(max_skus):
                return False, "SKU_LIMIT_EXCEEDED", quota_info
            if require_dirty_import and not plan.get("allow_dirty_import", False):
                return False, "PRO_FEATURE_REQUIRED", quota_info
            if norm_mode not in _STANDARD_ALGO_MODES and not plan.get("allow_advanced_algo", False):
                return False, "PRO_FEATURE_REQUIRED", quota_info

            if quota_info["monthly_remaining"] > 0:
                source = "monthly_plan"
            elif quota_info["extra_credits"] > 0:
                source = "extra_credits"
                self._conn.execute(
                    "UPDATE users SET extra_credits = extra_credits - 1 WHERE id = ? AND extra_credits > 0",
                    (user_id,),
                )
            else:
                return False, "QUOTA_EXCEEDED", quota_info

            self._conn.execute(
                "INSERT INTO usage_ledger (user_id, month_key, delta, source, sku_count, algorithm_mode, created_at) "
                "VALUES (?, ?, 1, ?, ?, ?, ?)",
                (user_id, month_key, source, int(sku_count), norm_mode, _utc_now()),
            )
            self._conn.commit()
            updated_user = self.get_user_by_id(user_id) or user
            return True, None, self._compute_quota_locked(updated_user, month_key)

    def create_order(
        self, user_id: str, item_type: str, item_id: str, currency: str, provider: str
    ) -> Dict[str, Any]:
        """
        用途: 创建订阅套餐或按次加油包的待支付订单。
        输入: user_id、item_type ("plan" | "credit_pack")、item_id、currency ("CNY" | "USD")、provider。
        输出: 新建订单字典。
        被谁调用: gateway_dev 下单接口。
        """
        curr = currency.upper()
        if curr not in SUPPORTED_CURRENCIES:
            raise ValueError("INVALID_CURRENCY")
        item = get_plan(item_id) if item_type == "plan" else (
            get_credit_pack(item_id) if item_type == "credit_pack" else None
        )
        if item is None:
            raise ValueError("INVALID_ITEM")

        order_id = f"ord_{uuid.uuid4().hex[:16]}"
        amount = float(item["prices"][curr])
        now = _utc_now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO orders (order_id, user_id, item_type, item_id, currency, amount, provider, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (order_id, user_id, item_type, item_id, curr, amount, provider, now),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        return dict(row)

    def mark_order_paid(self, order_id: str, provider_ref: str = "") -> Optional[Dict[str, Any]]:
        """
        用途: 幂等标记订单为已支付，并自动升级用户套餐或累加 extra_credits。
        输入: order_id (str)、provider_ref (str, 第三方支付流水号)。
        输出: 最新订单字典；若订单不存在则返回 None。
        被谁调用: gateway_dev 支付 Webhook / 模拟支付确认接口。
        """
        now = _utc_now()
        with self._lock:
            row = self._conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
            if row is None:
                return None
            order = dict(row)
            if order["status"] == "paid":
                return order
            cur = self._conn.execute(
                "UPDATE orders SET status = 'paid', provider_ref = ?, paid_at = ? "
                "WHERE order_id = ? AND status != 'paid'",
                (provider_ref, now, order_id),
            )
            if cur.rowcount == 1:
                if order["item_type"] == "plan":
                    self._conn.execute(
                        "UPDATE users SET plan_id = ? WHERE id = ?",
                        (order["item_id"], order["user_id"]),
                    )
                elif order["item_type"] == "credit_pack":
                    pack = get_credit_pack(order["item_id"])
                    credits = int(pack["credits"]) if pack else 0
                    if credits > 0:
                        self._conn.execute(
                            "UPDATE users SET extra_credits = extra_credits + ? WHERE id = ?",
                            (credits, order["user_id"]),
                        )
            self._conn.commit()
            updated = self._conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        return dict(updated) if updated else None

    def create_share_link(
        self, user_id: str, job_id: str, payload: Dict[str, Any] | str
    ) -> Dict[str, Any]:
        """
        用途: 创建 3D 装柜结果分享链接记录。
        输入: user_id、job_id、payload (dict 或 JSON 字符串)。
        输出: 含 token、user_id、job_id、created_at 的字典。
        被谁调用: gateway_dev 分享链接生成接口。
        """
        token = secrets.token_urlsafe(18)
        payload_json = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        now = _utc_now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO share_links (token, user_id, job_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (token, user_id, job_id, payload_json, now),
            )
            self._conn.commit()
        return {"token": token, "user_id": user_id, "job_id": job_id, "created_at": now}

    def get_share_link(self, token: str) -> Optional[Dict[str, Any]]:
        """
        用途: 根据分享 token 查询 3D 装柜分享数据。
        输入: token (str)。
        输出: 含反序列化 payload 的字典；若不存在返回 None。
        被谁调用: gateway_dev 分享页只读接口。
        """
        with self._lock:
            row = self._conn.execute("SELECT * FROM share_links WHERE token = ?", (token,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        try:
            data["payload"] = json.loads(data["payload_json"])
        except Exception:
            data["payload"] = {}
        return data

    def create_api_key(self, user_id: str, name: str = "default") -> Dict[str, Any]:
        """
        用途: 为企业版用户签发新的 API Key（数据库仅存 SHA-256 哈希，明文仅此一次返回）。
        输入: user_id (str)、name (str)。
        输出: 含 api_key 明文、key_prefix、name、created_at 的字典。
        被谁调用: gateway_dev API Key 管理接口。
        """
        raw_key = f"aicivs_live_{secrets.token_urlsafe(24)}"
        key_hash, key_prefix, now = _hash_api_key(raw_key), raw_key[:16], _utc_now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO api_keys (key_hash, user_id, name, key_prefix, created_at) VALUES (?, ?, ?, ?, ?)",
                (key_hash, user_id, name, key_prefix, now),
            )
            self._conn.commit()
        return {"api_key": raw_key, "key_prefix": key_prefix, "name": name, "created_at": now}

    def verify_api_key(self, raw_key: str) -> Optional[Dict[str, Any]]:
        """
        用途: 校验 API Key 有效性并更新最后使用时间。
        输入: raw_key (str) - 请求头中的明文 API Key。
        输出: 关联用户字典；无效时返回 None。
        被谁调用: auth.authenticate_request()。
        """
        if not raw_key:
            return None
        key_hash = _hash_api_key(raw_key.strip())
        with self._lock:
            row = self._conn.execute("SELECT user_id FROM api_keys WHERE key_hash = ?", (key_hash,)).fetchone()
            if row is None:
                return None
            self._conn.execute("UPDATE api_keys SET last_used_at = ? WHERE key_hash = ?", (_utc_now(), key_hash))
            self._conn.commit()
            return self.get_user_by_id(row["user_id"])
