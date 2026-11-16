"""极简可解释分类器：标准化 k-NN（按案例投票）。

为什么不用神经网络：样本量只有几十，商用要求可审计、可回退。
k-NN 的决策可以直接解释为"与哪些历史货单相似、它们分别选了什么策略"，
训练与推理都是纯 Python，无额外依赖，模型文件可读可审。

被谁调用：learning.train（拟合/留一验证）、learning.selector（推理）。
"""

import math
from typing import Any, Dict, List, Optional

from backend.solver_v2.learning.features import FEATURE_NAMES

DEFAULT_K = 3


def _standardize(samples: List[List[float]]):
    n = len(samples)
    if n == 0:
        return [0.0] * len(FEATURE_NAMES), [1.0] * len(FEATURE_NAMES)
    dim = len(samples[0])
    mean = [sum(row[i] for row in samples) / n for i in range(dim)]
    std = []
    for i in range(dim):
        var = sum((row[i] - mean[i]) ** 2 for row in samples) / n
        std.append(math.sqrt(var) if var > 1e-12 else 1.0)
    return mean, std


def _scale(x: List[float], mean: List[float], std: List[float]) -> List[float]:
    return [(float(v) - m) / s for v, m, s in zip(x, mean, std)]


def fit(samples: List[Dict[str, Any]], k: int = DEFAULT_K) -> Dict[str, Any]:
    """samples: [{case_id, x, policy, score}] → 可序列化模型。"""
    vectors = [list(map(float, s["x"])) for s in samples]
    mean, std = _standardize(vectors)
    scaled = [_scale(v, mean, std) for v in vectors]
    stored = []
    for s, v in zip(samples, scaled):
        stored.append({
            "case_id": s.get("case_id"),
            "x": [round(val, 6) for val in v],
            "policy": s.get("policy"),
            "score": s.get("score"),
        })
    return {
        "schema": 1,
        "type": "knn",
        "k": int(k),
        "feature_names": list(FEATURE_NAMES),
        "mean": [round(v, 6) for v in mean],
        "std": [round(v, 6) for v in std],
        "samples": stored,
        "metrics": {"samples": len(stored)},
    }


def predict(model: Dict[str, Any], x: List[float]) -> Dict[str, Any]:
    samples = model.get("samples") or []
    if not samples:
        return {"policy": None, "confidence": 0.0, "proba": {}, "neighbors": []}
    mean = model.get("mean") or [0.0] * len(x)
    std = model.get("std") or [1.0] * len(x)
    z = _scale(x, mean, std)
    dists = []
    for s in samples:
        d = math.sqrt(sum((a - b) ** 2 for a, b in zip(z, s["x"])))
        dists.append((d, s))
    dists.sort(key=lambda item: item[0])
    k = max(1, min(int(model.get("k", DEFAULT_K)), len(dists)))
    votes: Dict[str, float] = {}
    total = 0.0
    for d, s in dists[:k]:
        w = 1.0 / (d + 1e-6)
        votes[s["policy"]] = votes.get(s["policy"], 0.0) + w
        total += w
    proba = {p: v / total for p, v in votes.items()} if total > 0 else {}
    best = max(proba, key=proba.get) if proba else None
    return {
        "policy": best,
        "confidence": round(proba.get(best, 0.0), 4) if best else 0.0,
        "proba": {p: round(v, 4) for p, v in sorted(proba.items(), key=lambda kv: -kv[1])},
        "neighbors": [
            {"case_id": s.get("case_id"), "policy": s.get("policy"),
             "distance": round(d, 4), "score": s.get("score")}
            for d, s in dists[:k]
        ],
    }


def leave_one_out(samples: List[Dict[str, Any]], k: int = DEFAULT_K) -> float:
    """按 case 留一验证（每个样本用其余样本训练后预测）。"""
    if len(samples) < 2:
        return 0.0
    correct = 0
    for i, held in enumerate(samples):
        rest = samples[:i] + samples[i + 1:]
        model = fit(rest, k=k)
        pred = predict(model, held["x"])
        if pred["policy"] == held["policy"]:
            correct += 1
    return correct / len(samples)


__all__ = ["DEFAULT_K", "fit", "predict", "leave_one_out"]
