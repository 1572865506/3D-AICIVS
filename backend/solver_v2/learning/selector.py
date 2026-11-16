"""策略选择器（影子模式）：根据货单特征建议 SAFETY_FIRST / BALANCED / VOLUME_FIRST。

重要边界：
- 只做"建议"，不自动改变交付方案；server/UI 必须显式展示并且人不点不动。
- 模型缺失、样本不足、置信度低、或与场景安全底线冲突时，一律回退手工策略。
- 安全底线是手写的：封门薄板/易碎场景不允许模型建议"装载率优先"来绕过开门安全。

被谁调用：backend/server.py（响应 learningSuggestion）、dashboard 状态接口。
"""

import json
import os
from typing import Any, Dict, List, Optional

from backend.solver_v2.evaluation.scenarios import detect_scenario
from backend.solver_v2.evaluation.spec import POLICY_SAFETY_FIRST, POLICY_VOLUME_FIRST
from backend.solver_v2.learning.features import extract_features, to_vector
from backend.solver_v2.learning.model import predict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULT_MODEL_PATH = os.path.join(PROJECT_ROOT, "data", "learning", "policy_model.json")
DEFAULT_MIN_CONFIDENCE = 0.55
# 这些场景下模型不得建议"装载率优先"（手写安全底线，优先于学习结果）
_PROTECTED_SCENARIOS = {"DOOR_THIN_PANEL", "FRAGILE"}

_model_cache: Dict[str, Any] = {"path": None, "mtime": None, "model": None}


def load_model(model_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    path = model_path or DEFAULT_MODEL_PATH
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    if _model_cache["path"] == path and _model_cache["mtime"] == mtime:
        return _model_cache["model"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            model = json.load(f)
    except (OSError, ValueError):
        return None
    _model_cache.update({"path": path, "mtime": mtime, "model": model})
    return model


def suggest_policy(
    cargo_list: List[Any],
    container: Any,
    model_path: Optional[str] = None,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> Dict[str, Any]:
    """返回策略建议（永远带有可解释来源与回退路径）。"""
    scenario = detect_scenario(cargo_list, container)
    fallback_policy = scenario["policy"]
    model = load_model(model_path)
    if not model or not (model.get("samples")):
        return {
            "policy": fallback_policy,
            "confidence": 0.0,
            "source": "fallback",
            "scenario": scenario["scenario"],
            "scenarioPolicy": fallback_policy,
            "note": "无可用模型，回退场景默认策略",
            "neighbors": [],
            "modelMetrics": {},
        }

    features = extract_features(cargo_list, container)
    pred = predict(model, to_vector(features))
    policy = pred.get("policy")
    confidence = float(pred.get("confidence") or 0.0)
    metrics = model.get("metrics") or {}
    enabled = bool(metrics.get("enabled", True))

    if not enabled:
        return {
            "policy": fallback_policy, "confidence": confidence, "source": "fallback",
            "scenario": scenario["scenario"], "scenarioPolicy": fallback_policy,
            "note": "模型未通过验证门槛（启用条件不满足），回退场景默认策略",
            "neighbors": pred.get("neighbors") or [], "modelMetrics": metrics,
        }
    if policy is None or confidence < min_confidence:
        return {
            "policy": fallback_policy, "confidence": confidence, "source": "fallback",
            "scenario": scenario["scenario"], "scenarioPolicy": fallback_policy,
            "note": f"置信度 {confidence:.2f} 低于阈值 {min_confidence:.2f}，回退场景默认策略",
            "neighbors": pred.get("neighbors") or [], "modelMetrics": metrics,
        }
    if scenario["scenario"] in _PROTECTED_SCENARIOS and policy == POLICY_VOLUME_FIRST:
        return {
            "policy": POLICY_SAFETY_FIRST, "confidence": confidence, "source": "fallback",
            "scenario": scenario["scenario"], "scenarioPolicy": fallback_policy,
            "note": "场景含开门/易碎风险，学习建议的装载率优先被安全底线否决",
            "neighbors": pred.get("neighbors") or [], "modelMetrics": metrics,
        }

    return {
        "policy": policy,
        "confidence": round(confidence, 4),
        "source": "learned",
        "scenario": scenario["scenario"],
        "scenarioPolicy": fallback_policy,
        "note": "影子模式建议，不自动应用",
        "neighbors": pred.get("neighbors") or [],
        "modelMetrics": metrics,
    }


__all__ = ["DEFAULT_MODEL_PATH", "load_model", "suggest_policy"]
