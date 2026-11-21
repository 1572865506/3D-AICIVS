"""商业化 SaaS 网关、存储、鉴权、配额与双币种账单回归测试。"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pytest

from backend.saas import (
    SaaSStore,
    authenticate_request,
    create_jwt,
    hash_password,
    list_catalog,
    t,
    verify_jwt,
    verify_password,
)


def _http_json(
    base_url: str,
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[int, Dict[str, Any]]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(f"{base_url}{path}", data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return exc.code, json.loads(raw) if raw else {}


@pytest.fixture()
def saas_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import backend.server as srv

    db_path = tmp_path / "saas_test.db"
    monkeypatch.setenv("AICIVS_SAAS_MODE", "1")
    monkeypatch.setenv("AICIVS_SAAS_DB", str(db_path))
    monkeypatch.setenv("AICIVS_JWT_SECRET", "test-jwt-secret-3d-aicivs")
    monkeypatch.delenv("AICIVS_API_TOKEN", raising=False)

    test_store = SaaSStore(db_path)
    monkeypatch.setattr(srv, "SAAS_STORE", test_store)
    httpd = srv.ThreadedHTTPServer(("127.0.0.1", 0), srv.AICIVSRequestHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", test_store
    finally:
        httpd.shutdown()
        httpd.server_close()
        test_store.close()


def test_store_auth_and_i18n(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AICIVS_JWT_SECRET", "unit-test-secret")
    store = SaaSStore(":memory:")
    try:
        pw_hash = hash_password("Secret123!", iterations=10_000)
        assert verify_password("Secret123!", pw_hash) is True
        assert verify_password("WrongPass!", pw_hash) is False

        user = store.create_user("Alice@Example.com", pw_hash, region="CN", locale="zh-CN")
        assert user["email"] == "alice@example.com"
        assert user["plan_id"] == "free"

        with pytest.raises(ValueError, match="EMAIL_EXISTS"):
            store.create_user("alice@example.com", pw_hash)

        fetched = store.get_user_by_email("ALICE@example.com")
        assert fetched is not None and fetched["id"] == user["id"]

        token = create_jwt({"sub": user["id"], "email": user["email"]}, expires_in=3600)
        claims, err = verify_jwt(token)
        assert err is None and claims is not None and claims["sub"] == user["id"]
        assert verify_jwt(token + "x")[1] == "INVALID_TOKEN"

        expired = create_jwt({"sub": user["id"], "exp": int(time.time()) - 10})
        assert verify_jwt(expired)[1] == "TOKEN_EXPIRED"

        auth_user, auth_err = authenticate_request({"Authorization": f"Bearer {token}"}, store)
        assert auth_err is None and auth_user is not None and auth_user["id"] == user["id"]
        assert authenticate_request({}, store)[1] == "AUTH_REQUIRED"

        key_info = store.create_api_key(user["id"], name="ci-key")
        key_user, key_err = authenticate_request({"X-API-Key": key_info["api_key"]}, store)
        assert key_err is None and key_user is not None and key_user["id"] == user["id"]
        assert authenticate_request({"X-API-Key": "aicivs_live_invalid"}, store)[1] == "INVALID_API_KEY"

        assert "15" in t("SKU_LIMIT_EXCEEDED", "zh-CN", max_skus=15, sku_count=20)
        assert "20" in t("SKU_LIMIT_EXCEEDED", "en-US", max_skus=15, sku_count=20)
        assert "加油包" in t("QUOTA_EXCEEDED", "zh-CN")
        assert "credit pack" in t("QUOTA_EXCEEDED", "en-US")
        assert "专业版" in t("PRO_FEATURE_REQUIRED", "zh-CN")
        assert "Pro plan" in t("PRO_FEATURE_REQUIRED", "en-US")
    finally:
        store.close()


def test_plan_limits_and_quota_gate():
    store = SaaSStore(":memory:")
    try:
        user = store.create_user("free@example.com", hash_password("Pass1234!", iterations=10_000))
        uid = user["id"]

        ok, err, _ = store.check_and_consume_solve(uid, sku_count=16)
        assert (ok, err) == (False, "SKU_LIMIT_EXCEEDED")

        ok, err, _ = store.check_and_consume_solve(uid, sku_count=5, require_dirty_import=True)
        assert (ok, err) == (False, "PRO_FEATURE_REQUIRED")

        ok, err, _ = store.check_and_consume_solve(uid, sku_count=5, algorithm_mode="proto_ems")
        assert (ok, err) == (False, "PRO_FEATURE_REQUIRED")

        for idx in range(10):
            ok, err, info = store.check_and_consume_solve(uid, sku_count=15, algorithm_mode="unified")
            assert ok is True and err is None
            assert info["monthly_used"] == idx + 1
            assert info["monthly_remaining"] == 9 - idx

        ok, err, info = store.check_and_consume_solve(uid, sku_count=1)
        assert (ok, err) == (False, "QUOTA_EXCEEDED")
        assert info["total_remaining"] == 0
    finally:
        store.close()


def test_dual_currency_billing_and_webhook_idempotency():
    cny_cat = list_catalog("CNY")
    usd_cat = list_catalog("USD")
    assert cny_cat["plans"][1]["currency"] == "CNY" and cny_cat["plans"][1]["price"] == 249
    assert usd_cat["plans"][1]["currency"] == "USD" and usd_cat["plans"][1]["price"] == 49

    store = SaaSStore(":memory:")
    try:
        user = store.create_user("buyer@example.com", hash_password("Pass1234!", iterations=10_000))
        uid = user["id"]

        ord_cny = store.create_order(uid, "plan", "pro", "CNY", "wechat")
        assert ord_cny["amount"] == 249.0 and ord_cny["status"] == "pending"
        paid_1 = store.mark_order_paid(ord_cny["order_id"], provider_ref="wx_001")
        paid_2 = store.mark_order_paid(ord_cny["order_id"], provider_ref="wx_001")
        assert paid_1 is not None and paid_1["status"] == "paid"
        assert paid_2 is not None and paid_2["status"] == "paid"
        assert store.get_user_by_id(uid)["plan_id"] == "pro"  # type: ignore[index]

        ord_ali = store.create_order(uid, "credit_pack", "pack_30", "CNY", "alipay")
        assert ord_ali["amount"] == 99.0
        ord_usd = store.create_order(uid, "credit_pack", "pack_30", "USD", "stripe")
        assert ord_usd["amount"] == 15.0
        store.mark_order_paid(ord_usd["order_id"], provider_ref="pi_001")
        store.mark_order_paid(ord_usd["order_id"], provider_ref="pi_001")
        assert store.get_user_by_id(uid)["extra_credits"] == 30  # type: ignore[index]

        ord_pad = store.create_order(uid, "plan", "business", "USD", "paddle")
        assert ord_pad["amount"] == 169.0
        store.mark_order_paid(ord_pad["order_id"], provider_ref="pad_001")
        assert store.get_user_by_id(uid)["plan_id"] == "business"  # type: ignore[index]
    finally:
        store.close()


def test_http_gateway_e2e(saas_server):
    base_url, store = saas_server

    # 1. 注册、重复冲突与登录
    st, reg = _http_json(
        base_url, "POST", "/api/v1/auth/register",
        {"email": "e2e@example.com", "password": "Password123", "region": "US"},
    )
    assert st == 201 and reg["success"] is True and reg["user"]["locale"] == "en-US"
    token = reg["token"]
    uid = reg["user"]["id"]
    auth_hdr = {"Authorization": f"Bearer {token}"}

    st, dup = _http_json(
        base_url, "POST", "/api/v1/auth/register",
        {"email": "e2e@example.com", "password": "Password123"},
    )
    assert st == 409 and dup["code"] == "EMAIL_EXISTS"

    st, bad_login = _http_json(
        base_url, "POST", "/api/v1/auth/login",
        {"email": "e2e@example.com", "password": "WrongPassword"},
    )
    assert st == 401 and bad_login["code"] == "INVALID_CREDENTIALS"

    st, login = _http_json(
        base_url, "POST", "/api/v1/auth/login",
        {"email": "e2e@example.com", "password": "Password123"},
    )
    assert st == 200 and login["token"]

    # 2. /auth/me GET & PATCH + /billing/plans
    st, me = _http_json(base_url, "GET", "/api/v1/auth/me", headers=auth_hdr)
    assert st == 200 and me["quota"]["monthly_quota"] == 10

    st, patched = _http_json(
        base_url, "PATCH", "/api/v1/auth/me",
        {"locale": "zh-CN", "unit_system": "imperial"}, headers=auth_hdr,
    )
    assert st == 200 and patched["user"]["locale"] == "zh-CN" and patched["user"]["unit_system"] == "imperial"

    st, plans = _http_json(base_url, "GET", "/api/v1/billing/plans?currency=USD")
    assert st == 200 and len(plans["plans"]) == 4 and plans["plans"][2]["price"] == 169

    # 3. /api/v1/loading/jobs 401 / 403 / 402 / 200
    container = {"length": 5898, "width": 2352, "height": 2393, "maxWeight": 28200}
    sku_one = [{"skuId": "SKU-1", "length": 400, "width": 300, "height": 300, "weight": 10, "quantity": 1}]
    sku_sixteen = [
        {"skuId": f"SKU-{i}", "length": 300, "width": 200, "height": 200, "weight": 5, "quantity": 1}
        for i in range(16)
    ]

    st, unauth = _http_json(base_url, "POST", "/api/v1/loading/jobs", {"container": container, "manifest": sku_one})
    assert st == 401 and unauth["code"] == "AUTH_REQUIRED"

    st, sku_err = _http_json(
        base_url, "POST", "/api/v1/loading/jobs",
        {"container": container, "manifest": sku_sixteen}, headers=auth_hdr,
    )
    assert st == 403 and sku_err["code"] == "SKU_LIMIT_EXCEEDED"

    st, algo_err = _http_json(
        base_url, "POST", "/api/v1/loading/jobs",
        {"container": container, "manifest": sku_one, "algorithmMode": "proto_ems"}, headers=auth_hdr,
    )
    assert st == 403 and algo_err["code"] == "PRO_FEATURE_REQUIRED"

    # 4. /api/v1/share 权限拦截 -> 购买 Business 套餐 -> Webhook 幂等放行
    st, share_denied = _http_json(
        base_url, "POST", "/api/v1/share", {"job_id": "job_1", "payload": {"boxes": []}}, headers=auth_hdr,
    )
    assert st == 403 and share_denied["code"] == "PRO_FEATURE_REQUIRED"

    for _ in range(10):
        ok, _, _ = store.check_and_consume_solve(uid, sku_count=1)
        assert ok is True
    st, quota_err = _http_json(
        base_url, "POST", "/api/v1/loading/jobs",
        {"container": container, "manifest": sku_one}, headers=auth_hdr,
    )
    assert st == 402 and quota_err["code"] == "QUOTA_EXCEEDED"

    st, checkout = _http_json(
        base_url, "POST", "/api/v1/billing/checkout",
        {"provider": "stripe", "item_type": "plan", "item_id": "business", "currency": "USD"},
        headers=auth_hdr,
    )
    assert st == 200 and checkout["order"]["status"] == "pending"

    order_id = checkout["order"]["order_id"]
    st, hook1 = _http_json(
        base_url, "POST", "/api/v1/billing/webhook/stripe",
        {"order_id": order_id, "provider_ref": "stripe_evt_1"},
    )
    st2, hook2 = _http_json(
        base_url, "POST", "/api/v1/billing/webhook/stripe",
        {"order_id": order_id, "provider_ref": "stripe_evt_1"},
    )
    assert st == 200 and st2 == 200 and hook1["quota"]["plan_id"] == "business" and hook2["quota"]["plan_id"] == "business"

    st, share_ok = _http_json(
        base_url, "POST", "/api/v1/share",
        {"job_id": "job_biz", "payload": {"utilization": 88.5}}, headers=auth_hdr,
    )
    assert st == 200 and share_ok["token"]
    st, share_get = _http_json(base_url, "GET", share_ok["share_url"])
    assert st == 200 and share_get["share"]["payload"]["utilization"] == 88.5

    # 5. Business 用户执行 /api/v1/loading/jobs 成功并扣减 1 次配额
    st, job_ok = _http_json(
        base_url, "POST", "/api/v1/loading/jobs",
        {"container": container, "manifest": sku_one, "timeBudgetSec": 1.0}, headers=auth_hdr,
    )
    assert st == 200 and job_ok.get("status") == "complete" and job_ok.get("job_id")
    st, me_after = _http_json(base_url, "GET", "/api/v1/auth/me", headers=auth_hdr)
    assert st == 200 and me_after["quota"]["monthly_used"] == 11
