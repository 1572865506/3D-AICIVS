"""TrialScore：求解器内部试算候选的快速评分（PlanScore 的轻量版）。

为什么需要它：
- 求解器每轮会跑多个 trial（LARGE_FIRST / DENSITY_FIRST / …），原先用一段
  内联线性公式挑最优，权重散落在 solve() 里，无法与交付评分/多方案评分对齐。
- 完整 PlanScore 需要 geometry_qa（O(n²) 观感统计），在每个 trial 上算代价过高。
  本模块只算"放置阶段已经有的数据 + 门面 SF（O(n)）"，作为 trial 级的快速裁决；
  最终的方案级评分仍由 evaluation.score/evaluate 负责。

评分公式与历史行为**逐项等价**（先保证不改变基准/守卫结果）：
    rigid_ratio*5000 + placed_volume*100 + utilization
    - 10000(非法) - 500*违规 - 50000*刚性饥饿SKU - 30000(优先级倒挂)
输出分数保留 4 位小数（远小于 1% 的平局带宽，不影响裁决）。

`door_min_sf` 只在安全模式（门区限定/门端台阶/开门稳定）下用于平局裁决：
同一得分带内优先选择门面安全系数更高的 trial；非安全模式完全不参与排序。

被谁调用：unified_solver.solve() 的 trial 循环与平局裁决、tests。
"""

import collections
from typing import Any, Dict, Iterable, List, Optional

# 与历史内联公式完全一致的罚分常量（改这里必须同步跑全量守卫）
TRIAL_SCORE_WEIGHTS: Dict[str, float] = {
    "rigid_ratio": 5000.0,
    "placed_volume": 100.0,
    "utilization": 1.0,
    "invalid_penalty": 10000.0,
    "violation_penalty": 500.0,
    "starved_rigid_penalty": 50000.0,
    "priority_inversion_penalty": 30000.0,
}


def _field(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def door_open_stats(placements: Iterable[Any], container_length: float) -> Dict[str, Any]:
    """门面整列 SF（与 geometry_qa.door_open 同口径，O(n)）。

    SF = 2·dx / H；H 为同 (x0, y0) 列的堆叠总高。
    没有货物靠近门面时返回 min_sf=None（不参与安全裁决）。
    """
    boxes: List[tuple] = []
    for p in placements or []:
        if isinstance(p, dict):
            boxes.append((float(p.get("x", 0.0)), float(p.get("y", 0.0)),
                          float(p.get("dx", 0.0)), float(p.get("dy", 0.0)),
                          float(p.get("dz", 0.0))))
        else:
            boxes.append((float(p.position.x), float(p.position.y),
                          float(p.orientation.dx), float(p.orientation.dy),
                          float(p.orientation.dz)))
    if not boxes:
        return {"min_sf": None, "unsafe_columns": 0, "column_count": 0}

    face = max(x + dx for (x, _, dx, _, _) in boxes)
    if face < container_length - 0.65:
        return {"min_sf": None, "unsafe_columns": 0, "column_count": 0}

    cols: Dict[tuple, Dict[str, float]] = collections.defaultdict(
        lambda: {"H": 0.0, "D": 0.0})
    for (x, y, dx, _, dz) in boxes:
        if face - (x + dx) > 1e-3:
            continue
        key = (round(x, 3), round(y, 3))
        cols[key]["H"] += dz
        cols[key]["D"] = max(cols[key]["D"], dx)
    if not cols:
        return {"min_sf": None, "unsafe_columns": 0, "column_count": 0}

    sfs = [(2.0 * e["D"]) / max(e["H"], 1e-6) for e in cols.values()]
    return {
        "min_sf": round(min(sfs), 3),
        "unsafe_columns": sum(1 for s in sfs if s < 1.5 - 1e-6),
        "column_count": len(cols),
    }


def score_trial(
    *,
    rigid_ratio: float,
    placed_volume: float,
    utilization: float,
    is_valid: bool,
    violations: int,
    starved_rigid_count: int,
    priority_inversion: bool,
    placements: Iterable[Any] = (),
    container_length: Optional[float] = None,
) -> Dict[str, Any]:
    """计算 trial 排序分与硬状态（公式与历史内联实现逐项等价）。"""
    w = TRIAL_SCORE_WEIGHTS
    score = (
        float(rigid_ratio) * w["rigid_ratio"]
        + float(placed_volume) * w["placed_volume"]
        + float(utilization) * w["utilization"]
        - (w["invalid_penalty"] if not is_valid else 0.0)
        - float(violations) * w["violation_penalty"]
        - float(starved_rigid_count) * w["starved_rigid_penalty"]
        - (w["priority_inversion_penalty"] if priority_inversion else 0.0)
    )
    door = (door_open_stats(placements, float(container_length))
            if container_length is not None else
            {"min_sf": None, "unsafe_columns": 0, "column_count": 0})
    return {
        "score": round(score, 4),
        "hard_fail": bool((not is_valid) or violations > 0
                          or starved_rigid_count > 0 or priority_inversion),
        "rigid_ratio": round(float(rigid_ratio), 6),
        "placed_volume": round(float(placed_volume), 4),
        "utilization": round(float(utilization), 4),
        "door_min_sf": door["min_sf"],
        "door_unsafe_columns": door["unsafe_columns"],
        "door_column_count": door["column_count"],
    }


__all__ = ["TRIAL_SCORE_WEIGHTS", "door_open_stats", "score_trial"]
