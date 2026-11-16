"""虚拟货单集结构测试：保证生成器输出可被 solver/harness 正确消费。

检查：
1. 用例数量与覆盖原型（3C/家电/电商/托盘/易碎/多站/门区薄板/20GP/45HQ…）；
2. 每个用例字段完整（container/cargo/meta），数量>0、尺寸>0；
3. 体积比符合目标（仅落地/超重用例除外）；
4. 预期拒绝/已知问题字段结构合法。

不跑求解（求解由 scripts/run_acceptance.py 负责），<1s 完成。
"""

import glob
import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES_DIR = os.path.join(PROJECT_ROOT, "tests", "cases", "virtual")


def _load_cases():
    paths = sorted(glob.glob(os.path.join(CASES_DIR, "*.json")))
    return [(p, json.load(open(p, encoding="utf-8"))) for p in paths]


class TestVirtualManifests:
    def test_case_count_and_coverage(self):
        cases = _load_cases()
        assert len(cases) >= 12, f"virtual case count too small: {len(cases)}"
        ids = {c["case_id"] for _, c in cases}
        for must in (
            "VIRTUAL-3C-MIX-40HQ", "VIRTUAL-3C-THIN-DOOR-40HQ",
            "VIRTUAL-APPLIANCE-HEAVY-40GP", "VIRTUAL-ECOMMERCE-MIX-40HQ",
            "VIRTUAL-PALLET-SINGLE-40HQ", "VIRTUAL-FRAGILE-40HQ",
            "VIRTUAL-MULTISTOP-40HQ", "VIRTUAL-NODOOR-40GP",
            "VIRTUAL-20GP-DENSE", "VIRTUAL-45HQ-LONG",
        ):
            assert must in ids, f"missing archetype case: {must}"

    def test_schema_and_positive_dimensions(self):
        for path, case in _load_cases():
            assert case["case_id"].startswith("VIRTUAL-")
            assert case["meta"]["synthetic"] is True
            usable = case["container"]["usable"]
            assert usable["L"] > 0 and usable["W"] > 0 and usable["H"] > 0
            assert case["cargo"], path
            for item in case["cargo"]:
                assert item["quantity"] > 0, (path, item["sku"])
                assert item["w"] > 0 and item["d"] > 0 and item["h"] > 0, (path, item["sku"])
                assert item["weight"] >= 0

    def test_volume_ratio_is_realistic(self):
        for path, case in _load_cases():
            meta = case["meta"]
            if meta.get("expected_reject") or meta.get("floor_limited"):
                continue
            usable = case["container"]["usable"]
            container_vol = usable["L"] * usable["W"] * usable["H"]
            req_vol = sum(i["w"] * i["d"] * i["h"] * i["quantity"] for i in case["cargo"])
            ratio = req_vol / container_vol
            assert 0.3 <= ratio <= 0.95, (path, round(ratio, 3))

    def test_expected_fields_are_well_formed(self):
        for path, case in _load_cases():
            meta = case["meta"]
            assert isinstance(meta.get("expected_reject", []), list)
            assert isinstance(meta.get("expected_error", []), list)
            assert meta.get("time_budget_s", 0) > 0
            issue = meta.get("known_issue")
            assert issue is None or isinstance(issue, (str, dict))
            if isinstance(issue, dict):
                assert issue.get("id") and issue.get("note")


class TestAcceptanceReport:
    """验收报告结构（dashboard 消费）必须在生成后保持稳定。"""

    REPORT = os.path.join(PROJECT_ROOT, "tests", "harness_reports", "acceptance_report.json")

    def test_report_schema_if_present(self):
        import pytest
        if not os.path.exists(self.REPORT):
            pytest.skip("acceptance report not generated yet")
        data = json.load(open(self.REPORT, encoding="utf-8"))
        summary = data.get("summary") or {}
        cases = data.get("cases") or []
        assert summary.get("case_count") == len(cases)
        assert summary["pass"] + summary["warn"] + summary.get("known", 0) + \
            summary.get("expected_reject", 0) + summary["fail"] == len(cases)
        for case in cases:
            assert case["status"] in ("PASS", "WARN", "KNOWN", "EXPECTED_REJECT", "FAIL")
            assert isinstance(case.get("checks"), dict)
            if case["score"] is not None:
                assert 0.0 <= float(case["score"]) <= 100.0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
