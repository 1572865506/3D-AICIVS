# -*- coding: utf-8 -*-
"""
共享物理内核 (Shared Physics Kernel)

提供求解器与验证器共用的物理检查纯函数。
所有函数是幂等纯函数——相同输入永远产出相同结果。
数学标准与 IndependentGlobalValidator 的 10 维审计完全同构。

被谁调用:
  - placement_engine/sequential_placer.py (放置前预检)
  - validation/independent_validator.py (放置后全量审计, 未来对齐)
  - brain/inference.py (策略评估时的快速可行性筛查)
"""

from .collision import check_no_collision

__all__ = [
    "check_no_collision",
]

# The following modules will be exported as they are completed in Phase 1:
try:
    from .support import check_support
    __all__.append("check_support")
except ImportError:
    pass

try:
    from .tipping import check_tipping_safety
    __all__.append("check_tipping_safety")
except ImportError:
    pass

try:
    from .bearing import check_bearing_capacity
    __all__.append("check_bearing_capacity")
except ImportError:
    pass

try:
    from .constraint_gate import check_business_constraints
    __all__.append("check_business_constraints")
except ImportError:
    pass
