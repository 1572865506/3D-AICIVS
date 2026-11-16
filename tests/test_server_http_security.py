"""真实 HTTP 边界测试：静态白名单、Token、422/413/429。

启动一个绑定 127.0.0.1:0 的临时服务器，验证 server.py 的实际行为（不是纯函数）。
"""

import http.client
import json
import os
import sys
import threading

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from backend.server import (
    AICIVSRequestHandler, SOLVE_GATE, ThreadedHTTPServer, run_server)
from backend.api.request_limits import MAX_BODY_BYTES


@pytest.fixture(scope="class")
def live_server():
    httpd = ThreadedHTTPServer(("127.0.0.1", 0), AICIVSRequestHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


def _request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=8)
    try:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        hdrs = dict(headers or {})
        if data is not None:
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            parsed = {"raw": raw[:200]}
        return resp.status, parsed
    finally:
        conn.close()


MINI_MANIFEST = {
    "container": {"usable": {"L": 2.4, "W": 1.2, "H": 1.2}, "maxPayloadTons": 20},
    "manifest": [{"sku": "A", "name": "A", "w": 0.4, "d": 0.4, "h": 0.4,
                  "weight": 2, "quantity": 4, "requirement": "放中间"}],
}


class TestStaticBoundary:
    def test_index_and_frontend_assets_served(self, live_server):
        assert _request(live_server, "GET", "/")[0] == 200
        assert _request(live_server, "GET", "/frontend/src/backendSwitch.js")[0] == 200

    def test_repository_internals_404(self, live_server):
        for path in ("/backend/server.py", "/tests/fixtures/production_15sku.json",
                     "/.git/config", "/data/annotations/annotations.jsonl"):
            assert _request(live_server, "GET", path)[0] == 404, path


class TestRequestBoundaries:
    def test_time_budget_out_of_range_is_422(self, live_server):
        body = dict(MINI_MANIFEST, timeBudgetSec=0)
        status, data = _request(live_server, "POST", "/api/v2/pack", body)
        assert status == 422
        assert data["code"] == "INPUT_INVALID"

    def test_alternatives_out_of_range_is_422(self, live_server):
        body = dict(MINI_MANIFEST, timeBudgetSec=5, alternatives=9)
        status, data = _request(live_server, "POST", "/api/v2/pack", body)
        assert status == 422
        assert data["code"] == "INPUT_INVALID"

    def test_unknown_alternative_profile_is_422(self, live_server):
        body = dict(MINI_MANIFEST, timeBudgetSec=5, alternatives=1,
                    alternativeProfiles=["NOT_A_PROFILE"])
        status, data = _request(live_server, "POST", "/api/v2/pack", body)
        assert status == 422
        assert data["code"] == "INPUT_INVALID"

    def test_alternative_budget_above_main_is_422(self, live_server):
        body = dict(MINI_MANIFEST, timeBudgetSec=5, alternatives=1,
                    alternativeBudgetSec=30)
        status, data = _request(live_server, "POST", "/api/v2/pack", body)
        assert status == 422
        assert data["code"] == "INPUT_INVALID"

    def test_oversized_body_is_413(self, live_server):
        conn = http.client.HTTPConnection("127.0.0.1", live_server, timeout=8)
        try:
            conn.putrequest("POST", "/api/v2/pack")
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", str(MAX_BODY_BYTES + 1))
            conn.endheaders()
            conn.send(b"{}")
            resp = conn.getresponse()
            assert resp.status == 413
        finally:
            conn.close()

    def test_busy_solver_returns_429(self, live_server):
        assert SOLVE_GATE.try_acquire() is True
        try:
            body = dict(MINI_MANIFEST, timeBudgetSec=2)
            status, data = _request(live_server, "POST", "/api/v2/pack", body)
            assert status == 429
            assert data["code"] == "SOLVER_BUSY"
            assert data["retryable"] is True
        finally:
            SOLVE_GATE.release()


class TestToken:
    def test_token_required_when_configured(self, live_server, monkeypatch):
        monkeypatch.setenv("AICIVS_API_TOKEN", "secret-token")
        assert _request(live_server, "GET", "/api/v1/annotations")[0] == 401
        status, _ = _request(live_server, "GET", "/api/v1/annotations",
                             headers={"Authorization": "Bearer secret-token"})
        assert status == 200

    def test_health_stays_public(self, live_server, monkeypatch):
        monkeypatch.setenv("AICIVS_API_TOKEN", "secret-token")
        assert _request(live_server, "GET", "/api/v1/health")[0] == 200


def test_run_server_default_host_is_loopback():
    import inspect
    assert inspect.signature(run_server).parameters["host"].default == "127.0.0.1"
