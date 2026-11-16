"""自学习模块（影子模式）：场景特征 → 策略档建议。

模块边界：
- features.py：货单结构化特征
- model.py：标准化 k-NN（可解释、可回退）
- selector.py：推理 + 安全底线 + 低置信回退（只建议，不自动应用）
- train.py：离线训练与留一验证（CLI 调用，server 不训练）

被谁调用：backend/server.py、scripts/train_policy_selector.py、tests。
"""

from backend.solver_v2.learning.features import FEATURE_NAMES, extract_features, to_vector
from backend.solver_v2.learning.selector import DEFAULT_MODEL_PATH, load_model, suggest_policy

__all__ = [
    "FEATURE_NAMES",
    "extract_features",
    "to_vector",
    "DEFAULT_MODEL_PATH",
    "load_model",
    "suggest_policy",
]
