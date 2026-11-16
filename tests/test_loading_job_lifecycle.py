"""Job/Plan 生命周期测试：LRU、TTL、单方案不常驻、并发只构建一次、clear 全清。"""

import os
import sys
import threading
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from backend.api.service import LoadingAPIService, LoadingJobStore


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class TestLoadingJobStore:
    def test_lru_evicts_oldest(self):
        clock = FakeClock()
        store = LoadingJobStore(max_jobs=2, ttl_s=999, clock=clock)
        assert store.put("a", {"v": 1}) == []
        assert store.put("b", {"v": 2}) == []
        assert store.put("c", {"v": 3}) == ["a"]
        assert store.get("a")[0] is None
        assert store.get("b")[0] == {"v": 2}
        assert store.get("c")[0] == {"v": 3}

    def test_get_touches_lru(self):
        clock = FakeClock()
        store = LoadingJobStore(max_jobs=2, ttl_s=999, clock=clock)
        store.put("a", 1)
        store.put("b", 2)
        assert store.get("a")[0] == 1  # a 变为最近使用
        assert store.put("c", 3) == ["b"]

    def test_ttl_expires_idle_entry(self):
        clock = FakeClock()
        store = LoadingJobStore(max_jobs=4, ttl_s=10, clock=clock)
        store.put("a", 1)
        clock.advance(11)
        value, evicted = store.get("a")
        assert value is None
        assert evicted == ["a"]
        assert len(store) == 0

    def test_clear_returns_all_ids(self):
        store = LoadingJobStore(max_jobs=4, ttl_s=999)
        store.put("a", 1)
        store.put("b", 2)
        assert set(store.clear()) == {"a", "b"}
        assert len(store) == 0


class TestLoadingAPIService:
    def _service(self):
        return LoadingAPIService(store=LoadingJobStore(max_jobs=4, ttl_s=999))

    def _entry(self, key, recommended):
        return {"key": key, "label": key, "recommended": recommended,
                "evaluation": {"score": 80}, "solution": object()}

    def test_single_recommended_plan_not_retained(self):
        svc = self._service()
        svc.store.put("job", {"version": "BLK007C", "metrics": {}})
        svc.register_alternatives("job", [self._entry("main", True)], None, [])
        assert "job" not in svc._plans

    def test_clear_covers_records_and_plans(self):
        svc = self._service()
        svc.store.put("job", {"version": "BLK007C", "metrics": {}})
        svc.register_alternatives(
            "job", [self._entry("main", True), self._entry("alt", False)], None, [])
        assert "job" in svc._plans
        svc.clear()
        assert len(svc.store) == 0
        assert svc._plans == {}
        assert svc.dispatch("/api/v1/loading/job")[0] == 404

    def test_concurrent_plan_build_only_once(self):
        svc = self._service()
        svc.store.put("job", {"version": "BLK007C", "metrics": {
            "plans": [], "recommended_plan": "main"}})
        svc.register_alternatives(
            "job", [self._entry("main", True), self._entry("alt", False)], None, [])
        calls = []
        started = threading.Event()

        def fake_register(*args, **kwargs):
            calls.append(kwargs.get("store_result"))
            started.set()
            time.sleep(0.15)
            return {"version": "BLK007C", "id": args[0]}

        svc.register_solver_output = fake_register
        results = []

        def worker():
            results.append(svc.dispatch("/api/v1/loading/job/plans/1")[0])

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        assert started.wait(1.0)
        for t in threads:
            t.join()
        assert calls == [False]  # 只构建一次，且不写主 store
        assert results == [200, 200]

    def test_plan_build_failure_returns_500_json(self):
        svc = self._service()
        svc.store.put("job", {"version": "BLK007C", "metrics": {}})
        svc.register_alternatives(
            "job", [self._entry("main", True), self._entry("alt", False)], None, [])
        svc.register_solver_output = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        code, body = svc.dispatch("/api/v1/loading/job/plans/1")
        assert code == 500
        assert body["error"] == "PLAN_BUILD_FAILED"
