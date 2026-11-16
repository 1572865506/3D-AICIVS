"""统一目标与评分规范（PlanScore Spec）。

把"多方案怎么比"固定成一条可解释的字典序目标，而不是各处手写加权：

    T0 硬约束（任何一条不过 → 方案作废）
    T1 场景安全（开门倾覆 / 运输侧向失稳 / 偏载）
    T2 业务履约（刚性履行 / 弹性填充 / 装载顺序可执行）
    T3 方案质量（装载率 / 观感评分卡 / 几何总评）
    T4 结构稳健（支撑完整度 / 孤立箱 / 隐藏空腔）

T0 是一票否决；T1~T4 各输出 0~100 分，按策略档位的权重合成总分。
权重不是"拍脑袋常数"：安全档把 T1 提到最高，体量档把 T3 提上来，
但任何档位都不会把 T2 压到 0.25 以下——刚性履约是业务底线。

被谁调用：score.py（评分）、evaluate.py（编排与排序）、server.py（方案选择）。
"""

from dataclasses import dataclass, field
from typing import Dict, Tuple

POLICY_SAFETY_FIRST = "SAFETY_FIRST"
POLICY_BALANCED = "BALANCED"
POLICY_VOLUME_FIRST = "VOLUME_FIRST"
DEFAULT_POLICY = POLICY_BALANCED


@dataclass(frozen=True)
class TierWeights:
    """T1~T4 的合成权重（总和必须为 1）。"""
    safety: float
    fulfillment: float
    quality: float
    robustness: float

    def normalized(self) -> "TierWeights":
        total = self.safety + self.fulfillment + self.quality + self.robustness
        if total <= 1e-9:
            return TierWeights(0.25, 0.30, 0.30, 0.15)
        return TierWeights(
            self.safety / total,
            self.fulfillment / total,
            self.quality / total,
            self.robustness / total,
        )


@dataclass(frozen=True)
class PolicyProfile:
    """策略档位：权重 + 安全门槛 + 选择约束。"""
    key: str
    label: str
    description: str
    weights: TierWeights
    # T1 安全底线：推荐方案必须满足；不满足只能作为"待确认备选"。
    door_min_sf: float = 1.5
    transport_max_unstable_ratio: float = 0.15
    # 推荐方案的业务约束：不允许为了分数明显牺牲刚性履行/装载量。
    max_rigid_loss_pp: float = 0.5
    max_placed_loss_ratio: float = 0.02


POLICY_PROFILES: Dict[str, PolicyProfile] = {
    POLICY_SAFETY_FIRST: PolicyProfile(
        key=POLICY_SAFETY_FIRST,
        label="安全优先",
        description="开门/运输安全权重最高，适用于封门薄板、易碎、多站卸货货单",
        weights=TierWeights(safety=0.45, fulfillment=0.25, quality=0.20, robustness=0.10),
        door_min_sf=1.5,
        transport_max_unstable_ratio=0.10,
        max_rigid_loss_pp=0.5,
        max_placed_loss_ratio=0.02,
    ),
    POLICY_BALANCED: PolicyProfile(
        key=POLICY_BALANCED,
        label="均衡",
        description="安全、履约、装载率、稳健性均衡，适用于大多数常规货单",
        weights=TierWeights(safety=0.25, fulfillment=0.30, quality=0.30, robustness=0.15),
        door_min_sf=1.5,
        transport_max_unstable_ratio=0.15,
        max_rigid_loss_pp=0.5,
        max_placed_loss_ratio=0.02,
    ),
    POLICY_VOLUME_FIRST: PolicyProfile(
        key=POLICY_VOLUME_FIRST,
        label="装载率优先",
        description="装载率/密度权重最高，适用于无开门风险、以柜数成本为核心的货单",
        weights=TierWeights(safety=0.15, fulfillment=0.25, quality=0.45, robustness=0.15),
        door_min_sf=1.5,
        transport_max_unstable_ratio=0.15,
        max_rigid_loss_pp=0.5,
        max_placed_loss_ratio=0.02,
    ),
}

# 各分量的归一化区间（good=满分，bad=0 分；方向在 score.py 明确）。
THRESHOLDS: Dict[str, float] = {
    # T1
    "door_sf_full": 2.5,          # SF≥2.5 视为满安全余量
    "door_sf_min": 1.5,           # 业务安全底线
    "transport_ratio_good": 0.01,  # 失稳体积占货量 ≤1% 满分
    "transport_ratio_bad": 0.15,   # ≥15% 归零
    "cog_offset_good_pct": 2.0,
    "cog_offset_bad_pct": 12.0,
    # T2
    "sequence_score": 100.0,
    # T3
    "util_floor_pct": 60.0,
    "util_ceil_pct": 90.0,
    "geometry_good": 100.0,
    "geometry_fair": 72.0,
    "geometry_poor": 35.0,
    # T4
    "support_penalty_per_pct": 2.0,
    "island_penalty": 12.0,
    "hidden_void_penalty_per_pct": 4.0,
}

# 等级线（与 geometry_qa.plan_quality 的 A/B/C/D 保持一致，便于业务阅读）。
GRADE_LINES: Tuple[Tuple[float, str], ...] = ((80.0, "A"), (65.0, "B"), (50.0, "C"))


def get_policy(name: str = None) -> PolicyProfile:
    """按名称取策略档位；未知名称回落到 BALANCED（不静默改变语义）。"""
    key = str(name or DEFAULT_POLICY).upper()
    return POLICY_PROFILES.get(key, POLICY_PROFILES[DEFAULT_POLICY])


def grade_for(score: float, hard_fail: bool = False) -> str:
    """分数 → 等级；T0 不过直接 F（区别于质量等级 D）。"""
    if hard_fail:
        return "F"
    for line, grade in GRADE_LINES:
        if score >= line:
            return grade
    return "D"


__all__ = [
    "POLICY_SAFETY_FIRST",
    "POLICY_BALANCED",
    "POLICY_VOLUME_FIRST",
    "DEFAULT_POLICY",
    "TierWeights",
    "PolicyProfile",
    "POLICY_PROFILES",
    "THRESHOLDS",
    "GRADE_LINES",
    "get_policy",
    "grade_for",
]
