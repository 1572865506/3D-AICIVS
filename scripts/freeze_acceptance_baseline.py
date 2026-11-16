"""把当前虚拟货单验收报告冻结为期望基线（tests/acceptance_baseline.json）。

规则：一旦冻结，后续只允许解释偏差，不允许再调虚拟货单数量/目标体积比来
"调到通过"。验收脚本/测试用容忍带比较，超出时要求人工复核。

运行：python scripts/freeze_acceptance_baseline.py
被谁调用：人工/CI；tests/test_acceptance_baseline.py 读取。
"""

import json
import os
from datetime import date

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT = os.path.join(PROJECT_ROOT, "tests", "harness_reports", "acceptance_report.json")
TARGET = os.path.join(PROJECT_ROOT, "tests", "acceptance_baseline.json")


def main():
    with open(REPORT, "r", encoding="utf-8") as f:
        report = json.load(f)
    cases = {}
    for case in report.get("cases", []):
        cases[case["case_id"]] = {
            "status": case["status"],
            "score": case.get("score"),
            "utilization_pct": case.get("utilization_pct"),
            "rigid_ratio": case.get("rigid_ratio"),
            "door_min_sf": case.get("door_min_sf"),
            "policy": case.get("policy"),
            "known_issue": case.get("known_issue"),
        }
    payload = {
        "schema": 1,
        "generated_at": date.today().isoformat(),
        "source": "tests/harness_reports/acceptance_report.json",
        "note": "虚拟货单验收冻结基线；数量/目标体积比不得再为通过而调整。",
        "case_count": len(cases),
        "summary": report.get("summary") or {},
        "cases": cases,
    }
    with open(TARGET, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Acceptance baseline frozen: {TARGET} ({len(cases)} cases)")


if __name__ == "__main__":
    main()
