"""服务安全边界与请求上限测试（不启动 HTTP server）。

覆盖：
1. 静态白名单：仓库内部文件/路径穿越/目录列表必须 404；
2. CORS 只允许本机/显式白名单；
3. 可选 Bearer Token；
4. timeBudget/alternatives/备选预算/策略档/货单规模校验；
5. SolveGate 并发闸门；
6. INPUT_INVALID → 422 分类。
"""

import os
import sys
import types

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from backend.api.error_response import classify_api_exception
from backend.api.request_limits import (
    InputValidationError,
    SolveGate,
    validate_alternative_budget,
    validate_alternative_profiles,
    validate_alternatives,
    validate_manifest_size,
    validate_seed,
    validate_time_budget,
)
from backend.api.security import (
    allowed_cors_origin,
    is_allowed_static_path,
    is_authorized,
)


@pytest.fixture()
def static_root(tmp_path):
    (tmp_path / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    (tmp_path / "test_dashboard.html").write_text("ok", encoding="utf-8")
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "server.py").write_text("secret", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "fixture.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]", encoding="utf-8")
    return str(tmp_path)


class TestStaticAllowlist:
    def test_pages_and_frontend_assets_allowed(self, static_root):
        assert is_allowed_static_path("/", static_root)
        assert is_allowed_static_path("/index.html", static_root)
        assert is_allowed_static_path("/test_dashboard.html", static_root)
        assert is_allowed_static_path("/frontend/src/app.js", static_root)
        assert is_allowed_static_path("/frontend/src/app.js?v=1", static_root)

    def test_repository_internals_blocked(self, static_root):
        for path in ("/backend/server.py", "/tests/fixture.json", "/.git/config",
                     "/README.md", "/data/annotations/annotations.jsonl"):
            assert not is_allowed_static_path(path, static_root), path

    def test_path_traversal_blocked(self, static_root):
        for path in ("/frontend/../backend/server.py",
                     "/frontend/%2e%2e/backend/server.py",
                     "/frontend/..%2fbackend/server.py",
                     "/frontend\\..\\backend\\server.py"):
            assert not is_allowed_static_path(path, static_root), path

    def test_directory_requests_blocked(self, static_root):
        assert not is_allowed_static_path("/frontend/", static_root)
        assert not is_allowed_static_path("/frontend/src/", static_root)
        assert not is_allowed_static_path("/frontend/src", static_root)

    def test_missing_file_blocked(self, static_root):
        assert not is_allowed_static_path("/frontend/src/missing.js", static_root)


class TestCorsAndToken:
    def test_local_origins_allowed(self):
        assert allowed_cors_origin("http://localhost:8080") == "http://localhost:8080"
        assert allowed_cors_origin("http://127.0.0.1:8080") == "http://127.0.0.1:8080"

    def test_external_origin_blocked(self):
        assert allowed_cors_origin("https://evil.example") == ""

    def test_explicit_extra_origin(self):
        assert allowed_cors_origin("https://ops.example", "https://ops.example") == "https://ops.example"

    def test_token(self):
        assert is_authorized(None, None) is True
        assert is_authorized("Bearer abc", "abc") is True
        assert is_authorized("Bearer wrong", "abc") is False
        assert is_authorized(None, "abc") is False


class TestRequestLimits:
    def test_time_budget(self):
        assert validate_time_budget(20) == 20.0
        assert validate_time_budget("30") == 30.0
        for bad in (0, -1, 121, float("nan"), float("inf"), "abc", None):
            with pytest.raises(InputValidationError):
                validate_time_budget(bad)

    def test_alternatives(self):
        assert validate_alternatives(0) == 0
        assert validate_alternatives(3) == 3
        for bad in (-1, 4, "abc"):
            with pytest.raises(InputValidationError):
                validate_alternatives(bad)

    def test_alternative_budget(self):
        assert validate_alternative_budget(30, 60) == 30.0
        with pytest.raises(InputValidationError):
            validate_alternative_budget(61, 60)
        with pytest.raises(InputValidationError):
            validate_alternative_budget(0, 60)
        with pytest.raises(InputValidationError):
            validate_alternative_budget(float("nan"), 60)

    def test_profiles(self):
        assert validate_alternative_profiles(["SAFETY_FIRST", "volume_first"]) == [
            "SAFETY_FIRST", "VOLUME_FIRST"]
        with pytest.raises(InputValidationError):
            validate_alternative_profiles("SAFETY_FIRST")
        with pytest.raises(InputValidationError):
            validate_alternative_profiles(["UNKNOWN"])

    def test_manifest_size(self):
        def sku(sku_id, qty):
            return types.SimpleNamespace(
                sku_id=sku_id, quantity=types.SimpleNamespace(required=qty))

        validate_manifest_size([sku(f"S{i}", 2) for i in range(10)])
        with pytest.raises(InputValidationError):
            validate_manifest_size([sku(f"S{i}", 1) for i in range(501)])
        with pytest.raises(InputValidationError):
            validate_manifest_size([sku("BIG", 50001)])

    def test_seed(self):
        assert validate_seed("42") == 42
        with pytest.raises(InputValidationError):
            validate_seed("abc")


class TestSolveGate:
    def test_single_slot(self):
        gate = SolveGate(max_concurrent=1)
        assert gate.try_acquire() is True
        assert gate.try_acquire() is False
        gate.release()
        assert gate.try_acquire() is True
        gate.release()

    def test_two_slots(self):
        gate = SolveGate(max_concurrent=2)
        assert gate.try_acquire() and gate.try_acquire()
        assert gate.try_acquire() is False
        gate.release()
        gate.release()


class TestErrorClassification:
    def test_input_invalid_maps_to_422(self):
        status, body = classify_api_exception(
            InputValidationError("INPUT_INVALID: timeBudgetSec 超限"))
        assert status == 422
        assert body["code"] == "INPUT_INVALID"
        assert body["category"] == "INPUT_CONSTRAINT"
        assert body["retryable"] is False
