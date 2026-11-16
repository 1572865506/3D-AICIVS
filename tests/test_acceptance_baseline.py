"""虚拟货单验收冻结基线一致性测试。

基线由 `scripts/freeze_acceptance_baseline.py` 从验收报告生成；本测试只做
容忍带比较，防止后续为了让用例通过而偷偷改虚拟货单数量/目标体积比。

容忍带：
- status 必须一致（KNOWN/PASS 不得互相漂移）；
- PlanScore ±5；
- 利用率 ±3pp；
- 刚性 ±1pp（仅非载重受限用例）；
- 门面 SF ±0.35（无 SF 的用例不比较）。
"""

import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(PROJECT_ROOT, "tests", "acceptance_baseline.json")
REPORT = os.path.join(PROJECT_ROOT, "tests", "harness_reports", "acceptance_report.json")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class TestAcceptanceBaseline:
    def test_report_covers_baseline_cases(self):
        if not os.path.exists(REPORT):
            import pytest
            pytest.skip("acceptance report not generated")
        base = _load(BASELINE)
        report = _load(REPORT)
        live = {c["case_id"]: c for c in report["cases"]}
        assert set(live) == set(base["cases"])

    def test_status_and_metrics_within_bands(self):
        if not os.path.exists(REPORT):
            import pytest
            pytest.skip("acceptance report not generated")
        base = _load(BASELINE)
        report = _load(REPORT)
        live = {c["case_id"]: c for c in report["cases"]}
        failures = []
        for case_id, expected in base["cases"].items():
            actual = live[case_id]
            if actual["status"] != expected["status"]:                failures.append(f"{case_id}: status {expected['status']} -> {actual['status']}")
            for key, tol in (("score", 5.0), ("utilization_pct", 3.0)):
                e, a = expected.get(key), actual.get(key)
                if e is None or a is None:
                    continue
                if abs(float(a) - float(e)) > tol:
                    failures.append(f"{case_id}: {key} {e} -> {a} (tol {tol})")
            e_r, a_r = expected.get("rigid_ratio"), actual.get("rigid_ratio")
            if e_r is not None and a_r is not None and abs(float(a_r) - float(e_r)) > 0.01:
                failures.append(f"{case_id}: rigid {e_r} -> {a_r} (tol 1pp)")
            e_sf, a_sf = expected.get("door_min_sf"), actual.get("door_min_sf")
            if e_sf is not None and a_sf is not None and abs(float(a_sf) - float(e_sf)) > 0.35:
                failures.append(f"{case_id}: door_sf {e_sf} -> {a_sf} (tol 0.35)")
        assert not failures, "验收基线漂移：\n" + "\n".join(failures)
