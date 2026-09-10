"""统一 Python/HTTP 求解参数；输入字典，输出经过范围校验的模式、种子和软预算。"""
from dataclasses import dataclass
import math


class SolverBudgetExceeded(Exception):
    """搜索已耗尽预算；只能保留之前验证通过的结果。"""


@dataclass(frozen=True)
class SolverOptions:
    mode: str = 'OPTIMIZE'
    seed: int = 42
    time_budget: float = 18.0

    @classmethod
    def parse(cls, options=None, **explicit):
        raw=dict(options or {})
        unknown=set(raw)-{'mode','seed','time_budget'}
        if unknown:
            raise ValueError(f'不支持的求解参数: {sorted(unknown)}')
        raw.update({k:v for k,v in explicit.items() if v is not None})
        mode=str(raw.get('mode','OPTIMIZE')).upper()
        if mode not in {'FAST','BALANCED','OPTIMIZE','MAX_COMPACT','ROBUST'}:
            raise ValueError('未知求解模式')
        budget=float(raw.get('time_budget',18.0))
        if not math.isfinite(budget) or not 0 < budget <= 300:
            raise ValueError('求解预算必须在 (0, 300] 秒内')
        seed=int(raw.get('seed',42))
        if seed != 42:
            raise ValueError('当前确定性求解器仅支持 seed=42，暂不支持随机搜索')
        return cls(mode,seed,budget)
