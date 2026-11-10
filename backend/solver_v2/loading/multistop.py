"""
多点卸货（Multi-Stop Unloading）规划模块。

业务约束：一柜多站配送时，**先卸的货物必须靠门**（后装），后卸的货物在柜内深处
（先装）。等价于沿柜长把货物按卸货站序分区，且装柜顺序必须与卸货顺序相反。

设计：
- 输入：每个 SKU 的卸货站序 `unload_stop`（1 = 第一站，最大站序 = 终点站）。
- 分区：按各站货物体积占比把可用柜长划分区段；终点站 → 柜尾（x 小），
  第一站 → 门端（x 大）。设最小段长与安全余量，容量不足时返回错误。
- 裁决：求解器门禁按区段硬约束（MULTISTOP_REGION_VIOLATION），
  并建议按站序降序装载（先装终点站）。

被谁调用：backend/solver_v2/solver/unified_solver.py（solve 前置分区 + 门禁）、
backend/solver_v2/validation/config_precheck.py（配置一致性检查）。
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class StopRegion:
    stop: int
    x_start: float
    x_end: float
    volume_m3: float
    sku_ids: Tuple[str, ...]


def plan_stop_regions(
    cargo_list: List[Any],
    container: Any,
    min_depth_m: float = 0.6,
    door_reserve_m: float = 0.2,
    gap_ratio: float = 0.03,
) -> Tuple[Dict[int, StopRegion], List[str]]:
    """
    计算每个卸货站的纵深区段。

    返回 (regions_by_stop, errors)。errors 非空表示配置不可行。
    """
    errors: List[str] = []
    stops: Dict[int, Dict[str, Any]] = {}
    for c in cargo_list:
        raw_stop = getattr(c, "unload_stop", None)
        if raw_stop is None:
            continue
        try:
            stop = int(raw_stop)
        except (TypeError, ValueError):
            errors.append(f"{getattr(c, 'sku_id', '?')} 的卸货站序非法: {raw_stop!r}")
            continue
        if stop < 1:
            errors.append(f"{getattr(c, 'sku_id', '?')} 的卸货站序必须 >= 1")
            continue
        box = getattr(c, "box", None)
        qty = getattr(getattr(c, "quantity", None), "required", 0) or 0
        vol = (box.x * box.y * box.z * qty) if box is not None else 0.0
        entry = stops.setdefault(stop, {"volume": 0.0, "skus": []})
        entry["volume"] += vol
        entry["skus"].append(c.sku_id)

    if not stops:
        return {}, errors

    total_len = float(container.Lx)
    usable_len = total_len - door_reserve_m
    total_vol = sum(v["volume"] for v in stops.values()) or 1e-9
    if usable_len <= 0:
        return {}, ["柜体可用纵深不足，无法做多点卸货分区"]

    # 站序降序：最大站序（终点站）在最深处
    ordered = sorted(stops.keys(), reverse=True)
    regions: Dict[int, StopRegion] = {}
    cursor = 0.0
    remaining_len = usable_len
    remaining_vol = total_vol
    for idx, stop in enumerate(ordered):
        vol = stops[stop]["volume"]
        if idx == len(ordered) - 1:
            depth = remaining_len  # 最后一站吃掉剩余纵深（含余量）
        else:
            depth = usable_len * (vol / remaining_vol)
            depth = max(min_depth_m, depth)
            depth = min(depth, remaining_len - min_depth_m * (len(ordered) - idx - 1))
        x0 = round(cursor * (1 + gap_ratio), 4)
        x1 = round(cursor + depth, 4)
        if depth < min_depth_m - 1e-6 or x1 <= x0:
            errors.append(f"站 {stop} 分区深度不足（{depth:.2f}m < 最小 {min_depth_m}m），"
                          f"请检查货量或增加柜型")
        regions[stop] = StopRegion(stop=stop, x_start=x0, x_end=x1,
                                   volume_m3=round(vol, 3), sku_ids=tuple(stops[stop]["skus"]))
        cursor = x1
        remaining_len -= depth
        remaining_vol -= vol
    return regions, errors


def stop_of(sku: Any) -> Optional[int]:
    raw = getattr(sku, "unload_stop", None)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def loading_order_by_stop(cargo_list: List[Any]) -> List[str]:
    """建议装柜顺序：按卸货站序降序（终点站先装，第一站最后装）。"""
    pairs = []
    for c in cargo_list:
        s = stop_of(c)
        if s is None:
            continue
        pairs.append((s, getattr(c, "sku_id", "?")))
    pairs.sort(key=lambda x: (-x[0], x[1]))
    return [sku for _, sku in pairs]
