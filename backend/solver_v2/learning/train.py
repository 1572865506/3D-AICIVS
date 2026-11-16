"""离线训练策略选择器：从"多策略模拟结果"里学习 场景 → 最佳策略档。

数据来源：scripts/build_learning_dataset.py 生成的 JSONL，每行 = 一个货单 ×
一个策略档的求解与 PlanScore 结果。标签 = 同一货单中"T0/T1 通过且总分最高"
的策略；没有任何策略通过安全底线时取总分最高者（并在标签里保留风险）。

训练产物：
- data/learning/policy_model.json：标准化 k-NN 模型 + 留一验证指标
- data/learning/train_report.json：样本数、准确率、多数类基线、策略分布

启用门槛（写进模型 metrics.enabled）：
  样本 ≥ 10 且 留一准确率 ≥ max(0.60, 多数类基线 + 0.10)
不满足时 selector 自动回退手工策略，不影响交付。

运行：python scripts/train_policy_selector.py
被谁调用：人工/CI；server 只读取模型，不训练。
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.learning.features import to_vector  # noqa: E402
from backend.solver_v2.learning.model import fit, leave_one_out  # noqa: E402

DEFAULT_DATASET = os.path.join(PROJECT_ROOT, "tests", "harness_reports", "learning_dataset.jsonl")
DEFAULT_MODEL = os.path.join(PROJECT_ROOT, "data", "learning", "policy_model.json")
DEFAULT_REPORT = os.path.join(PROJECT_ROOT, "data", "learning", "train_report.json")


def _load_records(path: str) -> List[Dict[str, Any]]:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
    return records


def _label_for_case(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    valid = [r for r in records if isinstance((r.get("evaluation") or {}).get("score"), (int, float))]
    if not valid:
        return {}
    eligible = [
        r for r in valid
        if not (r.get("evaluation") or {}).get("hard_fail")
        and bool(((r.get("evaluation") or {}).get("tiers") or {}).get("T1", {}).get("passed", False))
    ]
    pool = eligible or valid

    def _key(r):
        ev = r.get("evaluation") or {}
        m = ev.get("metrics") or {}
        return (float(ev.get("score", 0.0)),
                float(m.get("rigid_ratio", 0.0) or 0.0),
                float(m.get("utilization_pct", 0.0) or 0.0))

    best = max(pool, key=_key)
    return {
        "case_id": best.get("case_id"),
        "policy": best.get("policy"),
        "score": (best.get("evaluation") or {}).get("score"),
        "safe": bool(eligible),
        "features": best.get("features") or {},
    }


def train(dataset_path: str = DEFAULT_DATASET,
          model_path: str = DEFAULT_MODEL,
          report_path: str = DEFAULT_REPORT,
          k: int = 3) -> Dict[str, Any]:
    records = _load_records(dataset_path)
    if not records:
        raise SystemExit(f"No records in {dataset_path}")

    by_case: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        by_case.setdefault(str(r.get("case_id")), []).append(r)

    samples = []
    for case_id, case_records in by_case.items():
        labeled = _label_for_case(case_records)
        if not labeled.get("policy") or not labeled.get("features"):
            continue
        samples.append({
            "case_id": case_id,
            "x": to_vector(labeled["features"]),
            "policy": labeled["policy"],
            "score": labeled["score"],
            "safe": labeled["safe"],
        })

    if len(samples) < 3:
        raise SystemExit(f"Too few labeled cases: {len(samples)}")

    loo_acc = leave_one_out(samples, k=k)
    label_counts = Counter(s["policy"] for s in samples)
    majority = max(label_counts.values()) / len(samples)
    # 至少两类标签才有学习价值；准确率门槛取 max(0.60, 多数类+0.10) 但不超过 0.95
    # （多数类=1.0 时 "基线+0.10" 会超过 1，永远无法启用）。
    acc_gate = min(0.95, max(0.60, majority + 0.10))
    enabled = bool(len(samples) >= 10 and len(label_counts) >= 2 and loo_acc >= acc_gate)

    model = fit(samples, k=k)
    model["metrics"].update({
        "enabled": enabled,
        "samples": len(samples),
        "loo_accuracy": round(loo_acc, 4),
        "majority_baseline": round(majority, 4),
        "accuracy_gate": round(acc_gate, 4),
        "label_counts": dict(label_counts),
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "source": os.path.relpath(dataset_path, PROJECT_ROOT),
    })

    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    with open(model_path, "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, indent=2)
    report = {
        "dataset": os.path.relpath(dataset_path, PROJECT_ROOT),
        "cases": len(samples),
        "records": len(records),
        "enabled": enabled,
        "loo_accuracy": round(loo_acc, 4),
        "majority_baseline": round(majority, 4),
        "accuracy_gate": round(acc_gate, 4),
        "label_counts": dict(label_counts),
        "policy_scores": {
            p: [s["score"] for s in samples if s["policy"] == p] for p in label_counts
        },
        "trained_at": datetime.now().isoformat(timespec="seconds"),
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"Policy selector trained: cases={len(samples)} loo={loo_acc:.2%} "
          f"baseline={majority:.2%} enabled={enabled}")
    return report


def main():
    parser = argparse.ArgumentParser(description="训练策略选择器（影子模式）")
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    parser.add_argument("--k", type=int, default=3)
    args = parser.parse_args()
    train(args.dataset, args.model, args.report, args.k)


if __name__ == "__main__":
    main()
