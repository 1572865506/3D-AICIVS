# -*- coding: utf-8 -*-
"""
共享物理内核 (Shared Physics Kernel)

提供求解器与验证器共用的物理与工艺检查纯函数体系。
所有函数为幂等纯函数——相同输入永远产出相同结果。
数学标准与 IndependentGlobalValidator 的 10 维审计完全同构。

包含 6 大核心核验模块与 1 个聚合入口:
  1. check_no_collision: 容器边界越界与箱体间 3D AABB 穿透检查 (对齐第 1/2 维)
  2. check_orientation: 旋转姿态合法性与上下文匹配 (对齐第 4 维)
  3. check_business_constraints: 载重、落地、堆叠层数与门区隔离门禁 (对齐第 3/5/6 维)
  4. check_support: 支撑面积比与下层禁顶叠检查 (对齐第 7 维, z<=1e-3 地面免检)
  5. check_bearing_capacity: 垂直重力级联分摊与表面压强检查 (对齐第 8 维)
  6. check_tipping_safety: 纵向制动倾覆力矩安全系数与贴靠检查 (对齐 Gate 11 / TIP-03)
  7. check_placement_feasibility: 聚合全量预检门禁入口

被谁调用:
  - placement_engine/ (启发式/引导搜索/Transformer决策大脑放置前预检门禁)
  - validation/independent_validator.py (独立审计同构比对)
  - tests/test_physics_kernel_consistency.py (一致性单测守护)
"""

from .collision import check_no_collision, normalize_box, GEOM_EPSILON
from .orientation import check_orientation
from .support import check_support
from .tipping import check_tipping_safety
from .bearing import check_bearing_capacity
from .constraint_gate import check_business_constraints, compute_stack_column_depth
from .unified_gate import check_placement_feasibility

__all__ = [
    "check_no_collision",
    "check_orientation",
    "check_support",
    "check_tipping_safety",
    "check_bearing_capacity",
    "check_business_constraints",
    "check_placement_feasibility",
    "compute_stack_column_depth",
    "normalize_box",
    "GEOM_EPSILON",
]
