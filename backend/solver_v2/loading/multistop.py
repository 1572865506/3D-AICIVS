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

from backend.solver_v2.domain.models import PackingRole, ZoneType


def _is_door_seal(c: Any) -> bool:
    return (
        PackingRole.DOOR_SEAL in tuple(getattr(c, "packing_roles", ()) or ())
        or getattr(c, "target_zone", None) == ZoneType.DOOR
    )


def _stop_value(c: Any) -> Optional[int]:
    raw = getattr(c, "unload_stop", None)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


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
    has_door_seal = any(_is_door_seal(c) for c in cargo_list)
    ordered = sorted(stops.keys(), reverse=True)
    # 门端区段边界：
    # - 有封门件且有货：站 1 延伸到门端（cL-0.04），封门件落在门区内；
    # - 有封门件但站 1 不是封门件：站 1 止于非门货锁定线（cL-door_reserve）；
    # - 无封门件：没有门区锁定，直接到 cL-0.04。
    door_stop_seals = any(
        _is_door_seal(c)
        for c in cargo_list
        if _stop_value(c) is not None and _stop_value(c) == min(stops)
    )
    if not has_door_seal:
        door_boundary = round(total_len - 0.04, 4)
    elif door_stop_seals:
        door_boundary = round(total_len - 0.04, 4)
    else:
        door_boundary = round(total_len - max(0.2, door_reserve_m), 4)

    total_vol = sum(v["volume"] for v in stops.values()) or 1e-9
    if door_boundary <= min_depth_m * len(ordered):
        return {}, ["柜体可用纵深不足以容纳所有卸货站（含最小段长）"]

    # 站序降序：最大站序（终点站）在最深处；x=0 → door_boundary 连续分配
    regions: Dict[int, StopRegion] = {}
    cursor = 0.0
    remaining_len = door_boundary
    remaining_vol = total_vol
    for idx, stop in enumerate(ordered):
        vol = stops[stop]["volume"]
        stops_left = len(ordered) - idx
        if idx == len(ordered) - 1:
            depth = remaining_len
        else:
            # 用"剩余纵深 / 剩余体积"逐站分配（旧实现误用常量 usable_len，
            # 会让最后一站只剩最小段长再被 gap 收缩）
            depth = remaining_len * (vol / max(1e-9, remaining_vol))
            depth = max(min_depth_m, depth)
            depth = min(depth, remaining_len - min_depth_m * (stops_left - 1))
        depth = max(0.0, depth)
        x0 = round(cursor, 4)
        x1 = round(cursor + depth, 4)
        if depth < min_depth_m - 1e-6:
            errors.append(f"站 {stop} 分区深度不足（{depth:.2f}m < 最小 {min_depth_m}m），"
                          f"请检查货量或增加柜型")
        # 容量粗检：区段体积 × 0.75 典型装载效率；超过 115% 视为明显不可行
        _cap = depth * float(getattr(container, "Ly", 0.0)) * float(getattr(container, "Lz", 0.0)) * 0.75
        if _cap > 0 and vol > _cap * 1.15:
            errors.append(f"站 {stop} 货量 {vol:.2f}m³ 超过区段容量 {_cap:.2f}m³，"
                          f"请增加站数/减少货量/换大柜")
        regions[stop] = StopRegion(stop=stop, x_start=x0, x_end=x1,
                                   volume_m3=round(vol, 3), sku_ids=tuple(stops[stop]["skus"]))
        cursor = x1
        remaining_len -= depth
        remaining_vol -= vol
    return regions, errors


def stop_of(sku: Any) -> Optional[int]:
    return _stop_value(sku)


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
