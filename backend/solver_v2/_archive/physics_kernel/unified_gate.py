# -*- coding: utf-8 -*-
"""
聚合放置前预检门禁纯函数 (Unified Placement Pre-check Gate)

为后续放置引擎 (Beam Search, Transformer MCTS, 序列放置器) 提供统一预检入口。
以最短时间复杂度、最优拦截漏斗顺序进行短路判断:
  1. 边界与碰撞 (Collision & Bounds) - 纯几何 O(N) 或 O(1) 空间索引
  2. 姿态合法性 (Orientation & Context) - 局部属性 O(1)
  3. 业务与区域约束 (Business, Zone, Floor-only, Stack-limit)
  4. 底部物理支撑与禁顶叠 (Support Ratio & No-Top-Stacking)
  5. 垂直载荷传力与表面压强 (Bearing & Pressure DAG)
  6. 纵向减速倾覆自稳 (Longitudinal Tipping Moment)

所有函数均为纯函数, 幂等无副作用。

被谁调用:
  - physics_kernel/__init__.py 统一导出
  - placement_engine/ 任何放置引擎
  - tests/test_physics_kernel_consistency.py 一致性单测
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union
from .collision import GEOM_EPSILON, check_no_collision, normalize_box
from .orientation import check_orientation
from .support import check_support
from .bearing import check_bearing_capacity
from .tipping import check_tipping_safety
from .constraint_gate import check_business_constraints


def check_placement_feasibility(
    candidate: Union[Dict[str, Any], Any],
    placements: List[Union[Dict[str, Any], Any]],
    container_spec: Any,
    cargo_specs: Dict[str, Any],
    current_payload_weight: float = 0.0,
    door_zone_length: float = 0.0,
    has_door_skus: bool = False,
    rear_zone_length: float = 0.0,
    check_tipping: bool = True,
    spatial_index: Optional[Any] = None,
    context: Optional[Any] = None,
    epsilon: float = GEOM_EPSILON,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """对候选放置进行 6 维全量物理与工艺合法性短路核验。

    Returns:
        (is_feasible, violation_type, reason_message)
        如果合法，返回 (True, None, None)
    """
    cand = normalize_box(candidate)
    sku_id = cand.get("sku_id", "")
    cargo_spec = cargo_specs.get(sku_id) if cargo_specs else None

    # 获取容器尺寸
    inner_dim = getattr(container_spec, "inner_dim", None)
    if inner_dim is not None:
        c_lx, c_ly, c_lz = inner_dim.x, inner_dim.y, inner_dim.z
    elif isinstance(container_spec, (tuple, list)) and len(container_spec) == 3:
        c_lx, c_ly, c_lz = container_spec
    else:
        c_lx = getattr(container_spec, "Lx", getattr(container_spec, "length", 12.0))
        c_ly = getattr(container_spec, "Ly", getattr(container_spec, "width", 2.4))
        c_lz = getattr(container_spec, "Lz", getattr(container_spec, "height", 2.6))

    container_dims = (c_lx, c_ly, c_lz)

    # 1. 边界与空间碰撞预检
    ok_col, reason_col = check_no_collision(
        candidate=cand,
        placements=placements,
        container_dims=container_dims,
        spatial_index=spatial_index,
        epsilon=epsilon,
    )
    if not ok_col:
        viol_type = "OUT_OF_BOUNDS" if "越界" in (reason_col or "") else "COLLISION_OVERLAP"
        return False, viol_type, reason_col

    # 2. 姿态合法性与上下文匹配
    ok_ori, reason_ori = check_orientation(
        candidate=cand,
        cargo_spec=cargo_spec,
        context=context,
        epsilon=epsilon,
    )
    if not ok_ori:
        return False, "FORBIDDEN_ORIENTATION", reason_ori

    # 3. 业务工艺与区域约束门禁
    ok_biz, reason_biz = check_business_constraints(
        candidate=cand,
        placements=placements,
        cargo_spec=cargo_spec,
        container_spec=container_spec,
        current_payload_weight=current_payload_weight,
        door_zone_length=door_zone_length,
        has_door_skus=has_door_skus,
        rear_zone_length=rear_zone_length,
        epsilon=epsilon,
    )
    if not ok_biz:
        if "载重" in (reason_biz or ""):
            viol_type = "PAYLOAD_EXCEEDED"
        elif "门区" in (reason_biz or "") or "禁入" in (reason_biz or ""):
            viol_type = "DOOR_LOCKOUT_VIOLATION" if "门区专属" in (reason_biz or "") else "ZONE_VIOLATION"
        elif "落地" in (reason_biz or ""):
            viol_type = "FLOOR_ONLY_VIOLATION"
        elif "层数" in (reason_biz or ""):
            viol_type = "STACK_LIMIT_VIOLATION"
        else:
            viol_type = "CONSTRAINT_VIOLATION"
        return False, viol_type, reason_biz

    # 4. 底部物理支撑与下层禁顶叠核验
    ok_sup, ratio, reason_sup = check_support(
        candidate=cand,
        placements=placements,
        cargo_specs=cargo_specs,
        spatial_index=spatial_index,
        epsilon=epsilon,
    )
    if not ok_sup:
        viol_type = "NO_TOP_STACK_VIOLATION" if "封顶" in (reason_sup or "") or "顶叠" in (reason_sup or "") else "INSUFFICIENT_SUPPORT"
        return False, viol_type, reason_sup

    # 5. 垂直传力承重与表面压强核验
    if cargo_specs:
        ok_bear, reason_bear = check_bearing_capacity(
            candidate=cand,
            placements=placements,
            cargo_specs=cargo_specs,
            epsilon=epsilon,
        )
        if not ok_bear:
            viol_type = "PRESSURE_EXCEEDED" if "压强" in (reason_bear or "") else "BEARING_EXCEEDED"
            return False, viol_type, reason_bear

    # 6. 纵向倾覆防倒安全核验
    if check_tipping:
        ok_tip, sf, reason_tip = check_tipping_safety(
            candidate=cand,
            placements=placements,
            container_length=c_lx,
            spatial_index=spatial_index,
            epsilon=epsilon,
        )
        if not ok_tip:
            return False, "UNSTABLE_PLACEMENT", reason_tip

    return True, None, None
