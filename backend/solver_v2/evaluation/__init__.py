"""统一目标 / 场景模型 / 评分入口（PlanScore）。

模块边界：
- spec.py       目标分层、策略档位、阈值（唯一权重来源）
- scenarios.py  货单场景识别与默认策略
- score.py      单方案分层评分与扣分解释
- evaluate.py   统一评分入口 + 候选排序 + 取舍对比

被谁调用：server.py、solver 候选集、tests/。
"""

from backend.solver_v2.evaluation.evaluate import compare_plans, evaluate_plan, rank_plans
from backend.solver_v2.evaluation.scenarios import detect_scenario
from backend.solver_v2.evaluation.score import score_plan
from backend.solver_v2.evaluation.spec import (
    DEFAULT_POLICY,
    POLICY_BALANCED,
    POLICY_PROFILES,
    POLICY_SAFETY_FIRST,
    POLICY_VOLUME_FIRST,
    PolicyProfile,
    get_policy,
    grade_for,
)

__all__ = [
    "DEFAULT_POLICY",
    "POLICY_BALANCED",
    "POLICY_PROFILES",
    "POLICY_SAFETY_FIRST",
    "POLICY_VOLUME_FIRST",
    "PolicyProfile",
    "get_policy",
    "grade_for",
    "detect_scenario",
    "score_plan",
    "evaluate_plan",
    "rank_plans",
    "compare_plans",
]
