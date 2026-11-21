"""
Z 轴混高精确配方与 3D 复合块生成器。

用途：
    在指定高度上限 `target_h` 与区域尺寸 `(max_l, max_w)` 内，枚举 1-SKU 纯立柱与
    2-SKU 混高立柱（下层大件 + 顶层薄件/平放件），并在 XY 平面组合成高致密度、
    单品完单优先的 `CompoundBlock` 列表，供上层 EMS/装柜原型调度使用。

输入：
    - tensors: List[UniversalCargoTensor]（SKU 物理与约束定义）
    - rem_qty: Dict[str, int]（各 SKU 当前剩余待装数量）
    - target_h, max_w, max_l: 目标高度与 XY 可用包络上限（米）
    - allow_door: 是否允许包含仅限门口区（DOOR）的 SKU
    - flexible_unspecified: 未锁定竖放且非易碎品是否放宽为 6 向旋转
    - limit: 返回复合块数量上限

输出：
    - List[CompoundBlock]：按刚性完单优先、紧密度与 Z 轴满高排序的复合块列表。

被谁调用：
    - 装柜原型调度器（如 `ems_proto_dev` 负责的 EMS 原型）及单元测试。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from backend.solver_v2.domain.models import OrientationSpec, PlacementContext, UniversalCargoTensor, UniversalZone

_EPS = 1e-4
_FRAGILE_KEYWORDS = ("玻璃", "易碎", "glass", "fragile")


@dataclass
class BlockBox:
    """复合块内部单个箱体的局部放置描述（相对块原点 (0, 0, 0)）。"""

    sku_id: str
    dx: float
    dy: float
    dz: float
    ox: float
    oy: float
    oz: float
    weight_kg: float
    orientation: str
    is_elastic: bool


@dataclass
class CompoundBlock:
    """可整体放置的 3D 复合块，包含局部箱体列表与物理统计指标。"""

    dx: float
    dy: float
    dz: float
    boxes: List[BlockBox]
    sku_counts: Dict[str, int]
    cargo_vol: float
    fill_ratio: float
    is_door_block: bool
    total_weight_kg: float
    completes_skus: int


@dataclass
class _SkuMeta:
    """单个 SKU 的约束与候选朝向缓存。"""

    tensor: UniversalCargoTensor
    rem: int
    max_bearing_kg: Optional[float]
    max_stack_layers: Optional[int]
    allow_stacking_on_top: bool
    must_be_on_floor: bool
    is_door: bool
    is_elastic: bool
    orientations: List[Tuple[OrientationSpec, bool]]  # (spec, top_only)


@dataclass
class _Column:
    """沿 Z 轴堆叠的立柱原型（局部原点从 (0, 0, 0) 起）。"""

    dx: float
    dy: float
    dz: float
    boxes: List[BlockBox]
    sku_counts: Dict[str, int]
    cargo_vol: float
    total_weight_kg: float
    is_door: bool
    has_rigid: bool


def _is_fragile(tensor: UniversalCargoTensor) -> bool:
    text = f"{tensor.name} {tensor.category} {tensor.raw_requirement}".lower()
    return any(kw in text for kw in _FRAGILE_KEYWORDS)


def _all_six_orientations(tensor: UniversalCargoTensor) -> List[OrientationSpec]:
    l, w, h = round(tensor.length, 4), round(tensor.width, 4), round(tensor.height, 4)
    candidates = [
        OrientationSpec("UPRIGHT_NORMAL", l, w, h, is_upright=True),
        OrientationSpec("UPRIGHT_ROTATED", w, l, h, is_upright=True),
        OrientationSpec("FLAT_NORMAL", l, h, w, is_flat=True, is_upright=False),
        OrientationSpec("FLAT_ROTATED", h, l, w, is_flat=True, is_upright=False),
        OrientationSpec("SIDE_NORMAL", h, w, l, is_side=True, is_upright=False),
        OrientationSpec("SIDE_ROTATED", w, h, l, is_side=True, is_upright=False),
    ]
    seen, unique = set(), []
    for c in candidates:
        key = (round(c.dx, 4), round(c.dy, 4), round(c.dz, 4))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def _get_candidate_orientations(
    tensor: UniversalCargoTensor, flexible_unspecified: bool,
) -> List[Tuple[OrientationSpec, bool]]:
    """提取合法朝向列表及是否仅限顶层（top_only）标记。"""
    policy = getattr(tensor, "orientation_policy", None)
    keep_upright = getattr(tensor, "keep_upright", None)

    if flexible_unspecified and keep_upright is not True and not _is_fragile(tensor):
        raw_req = (tensor.raw_requirement or "").lower()
        if not any(k in raw_req for k in ("不可倒置", "竖放", "upright")):
            return [(spec, False) for spec in _all_six_orientations(tensor)]

    if policy is not None and hasattr(policy, "get_legal_orientations"):
        from backend.solver_v2.domain.models import BoxDim

        base = BoxDim(tensor.length, tensor.width, tensor.height)
        flat_top_only = bool(getattr(policy, "flat_only_on_top", False))
        seen, result = set(), []
        for ctx in (PlacementContext.MAIN_BODY, PlacementContext.TOP_FILL):
            for o3d in policy.get_legal_orientations(base, ctx):
                key = (round(o3d.dx, 4), round(o3d.dy, 4), round(o3d.dz, 4), o3d.is_flat)
                if key in seen:
                    continue
                seen.add(key)
                spec = OrientationSpec(
                    o3d.name, round(o3d.dx, 4), round(o3d.dy, 4), round(o3d.dz, 4),
                    is_upright=o3d.is_upright, is_flat=o3d.is_flat, is_side=o3d.is_side,
                )
                result.append((spec, bool(o3d.is_flat and flat_top_only)))
        if result:
            return result

    flat_top_only = bool(getattr(policy, "flat_only_on_top", False)) if policy is not None else False
    return [(spec, bool(spec.is_flat and flat_top_only)) for spec in tensor.orientations]


def _extract_sku_metas(
    tensors: List[UniversalCargoTensor], rem_qty: Dict[str, int],
    allow_door: bool, flexible_unspecified: bool,
) -> List[_SkuMeta]:
    metas: List[_SkuMeta] = []
    for t in tensors:
        rem, is_door = rem_qty.get(t.sku_id, 0), t.zone_preference == UniversalZone.DOOR
        if rem <= 0 or (is_door and not allow_door):
            continue
        oris = _get_candidate_orientations(t, flexible_unspecified)
        if not oris:
            continue
        max_bearing = getattr(t, "max_bearing_kg", None) or getattr(t, "max_bearing_weight_kg", None)
        allow_top = bool(getattr(t, "allow_stacking_on_top", True)) and not (t.max_stack_layers is not None and t.max_stack_layers <= 1)
        metas.append(_SkuMeta(
            t, rem, max_bearing, t.max_stack_layers, allow_top,
            bool(t.must_be_on_floor), is_door, bool(t.is_elastic), oris,
        ))
    return metas


def _max_layers_for_sku(meta: _SkuMeta, dz: float, target_h: float) -> int:
    k_h = int((target_h + _EPS) // dz) if dz > _EPS else 0
    if k_h <= 0:
        return 0
    if meta.must_be_on_floor or not meta.allow_stacking_on_top:
        return 1
    k_max = min(k_h, meta.rem)
    if meta.max_stack_layers is not None:
        k_max = min(k_max, meta.max_stack_layers)
    if meta.max_bearing_kg is not None and meta.tensor.weight_kg > _EPS:
        k_max = min(k_max, int((meta.max_bearing_kg + _EPS) // meta.tensor.weight_kg) + 1)
    return max(0, k_max)


def _offset_boxes(boxes: List[BlockBox], ox: float = 0.0, oy: float = 0.0, oz: float = 0.0) -> List[BlockBox]:
    return [BlockBox(b.sku_id, b.dx, b.dy, b.dz, round(b.ox + ox, 5), round(b.oy + oy, 5), round(b.oz + oz, 5), b.weight_kg, b.orientation, b.is_elastic) for b in boxes]


def _make_pure_columns(metas: List[_SkuMeta], target_h: float, max_w: float, max_l: float) -> List[_Column]:
    """生成 1-SKU 纯立柱候选。"""
    cols: List[_Column] = []
    for m in metas:
        t = m.tensor
        for spec, top_only in m.orientations:
            if spec.dx > max_l + _EPS or spec.dy > max_w + _EPS or spec.dz > target_h + _EPS:
                continue
            k_max = 1 if top_only else _max_layers_for_sku(m, spec.dz, target_h)
            if k_max <= 0:
                continue
            for k in sorted(({k_max, k_max - 1} if k_max >= 2 else {k_max}), reverse=True):
                if top_only and k > 1:
                    continue
                boxes = [BlockBox(t.sku_id, spec.dx, spec.dy, spec.dz, 0.0, 0.0, round(i * spec.dz, 5), t.weight_kg, spec.name, m.is_elastic) for i in range(k)]
                cols.append(_Column(
                    spec.dx, spec.dy, round(k * spec.dz, 5), boxes, {t.sku_id: k},
                    round(k * spec.dx * spec.dy * spec.dz, 6), round(k * t.weight_kg, 4), m.is_door, not m.is_elastic,
                ))
    return cols


def _make_mixed_columns(
    metas: List[_SkuMeta],
    target_h: float,
    max_w: float,
    max_l: float,
) -> List[_Column]:
    """生成 2-SKU 混高立柱（下层 A + 顶层 B），确保支撑率 >= 80% 且不超重。"""
    cols: List[_Column] = []
    # 限制候选对数量以保证生成速度（多 SKU + 6 向旋转下控制在毫秒级）
    sorted_metas = sorted(metas, key=lambda x: (x.is_elastic, -x.tensor.volume_m3 * x.rem))[:24]

    for ma in sorted_metas:
        if not ma.allow_stacking_on_top:
            continue
        ta = ma.tensor
        for sa, top_only_a in ma.orientations:
            if top_only_a or sa.dx > max_l + _EPS or sa.dy > max_w + _EPS or sa.dz > target_h + _EPS:
                continue
            ka_max = _max_layers_for_sku(ma, sa.dz, target_h)
            if ka_max <= 0:
                continue
            # 若 A 有 max_stack_layers，作为底层至少留 1 层给上层（保守限制）
            ka_limit = ka_max
            if ma.max_stack_layers is not None:
                ka_limit = min(ka_limit, max(1, ma.max_stack_layers - 1))

            for mb in sorted_metas:
                if mb.tensor.sku_id == ta.sku_id or mb.must_be_on_floor:
                    continue
                tb = mb.tensor
                for sb, top_only_b in mb.orientations:
                    # 顶层底面不得超过下层顶面，且面积支撑率 >= 80%
                    if sb.dx > sa.dx + _EPS or sb.dy > sa.dy + _EPS:
                        continue
                    nx_top = max(1, int((sa.dx + _EPS) // sb.dx))
                    ny_top = max(1, int((sa.dy + _EPS) // sb.dy))
                    top_footprint = nx_top * ny_top * sb.dx * sb.dy
                    base_footprint = sa.dx * sa.dy
                    if base_footprint <= _EPS or (top_footprint / base_footprint) < 0.80 - _EPS:
                        continue

                    for ka in range(ka_limit, 0, -1):
                        base_h = ka * sa.dz
                        rem_h = target_h - base_h
                        kb_h = int((rem_h + _EPS) // sb.dz) if rem_h >= sb.dz - _EPS else 0
                        if kb_h <= 0:
                            continue
                        kb_max = 1 if (top_only_b or not mb.allow_stacking_on_top) else min(kb_h, mb.rem // (nx_top * ny_top))
                        if mb.max_stack_layers is not None:
                            kb_max = min(kb_max, mb.max_stack_layers)
                        kb = kb_max
                        while kb >= 1:
                            top_cnt = nx_top * ny_top * kb
                            if top_cnt > mb.rem:
                                kb -= 1
                                continue
                            if ma.max_bearing_kg is not None and (ka - 1) * ta.weight_kg + top_cnt * tb.weight_kg > ma.max_bearing_kg + _EPS:
                                kb -= 1
                                continue
                            if kb > 1 and mb.max_bearing_kg is not None and (kb - 1) * tb.weight_kg > mb.max_bearing_kg + _EPS:
                                kb -= 1
                                continue
                            break
                        if kb <= 0:
                            continue

                        total_h = round(base_h + kb * sb.dz, 5)
                        if total_h < target_h * 0.85:
                            continue
                        boxes = [BlockBox(ta.sku_id, sa.dx, sa.dy, sa.dz, 0.0, 0.0, round(ia * sa.dz, 5), ta.weight_kg, sa.name, ma.is_elastic) for ia in range(ka)]
                        boxes.extend(
                            BlockBox(tb.sku_id, sb.dx, sb.dy, sb.dz, round(ix * sb.dx, 5), round(iy * sb.dy, 5), round(base_h + ib * sb.dz, 5), tb.weight_kg, sb.name, mb.is_elastic)
                            for ib in range(kb) for ix in range(nx_top) for iy in range(ny_top)
                        )
                        cnt_b = nx_top * ny_top * kb
                        cargo_vol = ka * sa.dx * sa.dy * sa.dz + cnt_b * sb.dx * sb.dy * sb.dz
                        cols.append(_Column(
                            dx=sa.dx, dy=sa.dy, dz=total_h, boxes=boxes,
                            sku_counts={ta.sku_id: ka, tb.sku_id: cnt_b}, cargo_vol=round(cargo_vol, 6),
                            total_weight_kg=round(ka * ta.weight_kg + cnt_b * tb.weight_kg, 4),
                            is_door=ma.is_door or mb.is_door, has_rigid=(not ma.is_elastic) or (not mb.is_elastic),
                        ))
    return cols


def _build_compound_block(
    dx: float, dy: float, dz: float, boxes: List[BlockBox], sku_counts: Dict[str, int],
    cargo_vol: float, is_door: bool, total_weight_kg: float,
    rem_qty: Dict[str, int], rigid_map: Dict[str, bool],
) -> CompoundBlock:
    box_vol = dx * dy * dz
    fill_ratio = round(cargo_vol / box_vol, 4) if box_vol > _EPS else 0.0
    completes = sum(1 for sid, cnt in sku_counts.items() if cnt == rem_qty.get(sid, 0) and rigid_map.get(sid, False))
    return CompoundBlock(
        round(dx, 5), round(dy, 5), round(dz, 5), boxes, sku_counts,
        round(cargo_vol, 6), fill_ratio, is_door, round(total_weight_kg, 4), completes,
    )


def _tile_column_to_block(
    col: _Column, nx: int, ny: int, rem_qty: Dict[str, int], rigid_map: Dict[str, bool],
) -> Optional[CompoundBlock]:
    """将单个立柱按 nx * ny 阵列平铺成 CompoundBlock。"""
    sku_counts = {sid: cnt * nx * ny for sid, cnt in col.sku_counts.items()}
    if any(need > rem_qty.get(sid, 0) for sid, need in sku_counts.items()):
        return None
    boxes = [b for ix in range(nx) for iy in range(ny) for b in _offset_boxes(col.boxes, ix * col.dx, iy * col.dy, 0.0)]
    return _build_compound_block(
        nx * col.dx, ny * col.dy, col.dz, boxes, sku_counts,
        col.cargo_vol * nx * ny, col.is_door, col.total_weight_kg * nx * ny, rem_qty, rigid_map,
    )


def _combine_columns_y(
    cols_counts: List[Tuple[_Column, int]], nx: int,
    rem_qty: Dict[str, int], rigid_map: Dict[str, bool], min_fill: float = 0.80,
) -> Optional[CompoundBlock]:
    """在 Y 方向拼合 2~3 种立柱（各自可重复 ny 次）并沿 X 扩展 nx 排。"""
    sku_counts: Dict[str, int] = {}
    for col, ny in cols_counts:
        for sid, cnt in col.sku_counts.items():
            sku_counts[sid] = sku_counts.get(sid, 0) + cnt * nx * ny
    if any(need > rem_qty.get(sid, 0) for sid, need in sku_counts.items()):
        return None
    step_x = max(col.dx for col, _ in cols_counts)
    dy, dz, dx = sum(col.dy * ny for col, ny in cols_counts), max(col.dz for col, _ in cols_counts), nx * step_x
    cargo_vol = sum(col.cargo_vol * ny for col, ny in cols_counts) * nx
    if dx * dy * dz <= _EPS or cargo_vol / (dx * dy * dz) < min_fill:
        return None
    boxes: List[BlockBox] = []
    for ix in range(nx):
        off_y = 0.0
        for col, ny in cols_counts:
            for _ in range(ny):
                boxes.extend(_offset_boxes(col.boxes, ix * step_x, off_y, 0.0))
                off_y += col.dy
    return _build_compound_block(
        dx, dy, dz, boxes, sku_counts, cargo_vol, any(col.is_door for col, _ in cols_counts),
        sum(col.total_weight_kg * ny for col, ny in cols_counts) * nx, rem_qty, rigid_map,
    )


def _combine_columns_x(
    c1: _Column, c2: _Column, max_w: float,
    rem_qty: Dict[str, int], rigid_map: Dict[str, bool], min_fill: float = 0.78,
) -> Optional[CompoundBlock]:
    """在 X 方向拼合两个不同立柱并沿 Y 尽量铺满 max_w，匹配精确剩余 X 进深。"""
    ny1, ny2 = max(1, int((max_w + _EPS) // c1.dy)), max(1, int((max_w + _EPS) // c2.dy))
    sku_counts: Dict[str, int] = {}
    for col, ny in ((c1, ny1), (c2, ny2)):
        for sid, cnt in col.sku_counts.items():
            sku_counts[sid] = sku_counts.get(sid, 0) + cnt * ny
    if any(need > rem_qty.get(sid, 0) for sid, need in sku_counts.items()):
        return None
    dx, dy, dz = c1.dx + c2.dx, max(ny1 * c1.dy, ny2 * c2.dy), max(c1.dz, c2.dz)
    cargo_vol = c1.cargo_vol * ny1 + c2.cargo_vol * ny2
    if dx * dy * dz <= _EPS or cargo_vol / (dx * dy * dz) < min_fill:
        return None
    boxes = [b for iy in range(ny1) for b in _offset_boxes(c1.boxes, 0.0, iy * c1.dy, 0.0)]
    boxes.extend(b for iy in range(ny2) for b in _offset_boxes(c2.boxes, c1.dx, iy * c2.dy, 0.0))
    return _build_compound_block(
        dx, dy, dz, boxes, sku_counts, cargo_vol, c1.is_door or c2.is_door,
        c1.total_weight_kg * ny1 + c2.total_weight_kg * ny2, rem_qty, rigid_map,
    )


def generate_mixed_height_blocks(
    tensors: List[UniversalCargoTensor], rem_qty: Dict[str, int],
    target_h: float, max_w: float, max_l: float,
    allow_door: bool = False, flexible_unspecified: bool = False, limit: int = 80,
) -> List[CompoundBlock]:
    """生成满足物理约束的 Z 轴混高立柱与 XY 复合块，支持 Y 吃满、窄柱专项与精确 X 进深匹配。"""
    if target_h <= _EPS or max_w <= _EPS or max_l <= _EPS or limit <= 0:
        return []
    metas = _extract_sku_metas(tensors, rem_qty, allow_door, flexible_unspecified)
    if not metas:
        return []

    rigid_map = {m.tensor.sku_id: not m.is_elastic for m in metas}
    all_cols = _make_pure_columns(metas, target_h, max_w, max_l) + _make_mixed_columns(metas, target_h, max_w, max_l)
    if not all_cols:
        return []

    is_narrow = (max_w < 0.80 - _EPS) or (max_l < 0.80 - _EPS)
    is_tail_x = max_l <= 1.50 + _EPS
    min_fill = 0.72 if is_narrow else 0.82
    all_cols.sort(
        key=lambda c: (c.has_rigid, c.dz >= target_h - 0.08, round(c.cargo_vol / max(c.dx * c.dy * c.dz, _EPS), 3), c.dz),
        reverse=True,
    )
    top_cols = all_cols[:64]

    raw_blocks: List[CompoundBlock] = []
    for col in top_cols:
        max_nx = min(3, max(1, int((max_l + _EPS) // col.dx)))
        max_ny = max(1, int((max_w + _EPS) // col.dy))
        nx_cands = sorted({1, max_nx}) if is_tail_x or is_narrow else range(1, max_nx + 1)
        for nx in nx_cands:
            for ny in sorted({1, max_ny, max(1, max_ny - 1)}):
                if nx * col.dx <= max_l + _EPS and ny * col.dy <= max_w + _EPS:
                    blk = _tile_column_to_block(col, nx, ny, rem_qty, rigid_map)
                    if blk is not None:
                        raw_blocks.append(blk)

    pair_pool = top_cols[:24]
    for i, c1 in enumerate(pair_pool):
        max_ny1 = min(4, max(1, int((max_w + _EPS) // c1.dy)))
        for c2 in pair_pool[i + 1 :]:
            if c1.dy + c2.dy <= max_w + _EPS:
                max_nx = min(2, max(1, int((max_l + _EPS) // max(c1.dx, c2.dx))))
                for ny1 in (1, max_ny1) if max_ny1 > 1 else (1,):
                    rem_w = max_w - ny1 * c1.dy
                    if rem_w < c2.dy - _EPS:
                        continue
                    ny2 = min(4, int((rem_w + _EPS) // c2.dy))
                    for nx in range(1, max_nx + 1):
                        blk = _combine_columns_y([(c1, ny1), (c2, ny2)], nx, rem_qty, rigid_map, min_fill=min_fill)
                        if blk is not None:
                            raw_blocks.append(blk)
            if is_tail_x and c1.dx + c2.dx <= max_l + _EPS:
                blk_x = _combine_columns_x(c1, c2, max_w, rem_qty, rigid_map, min_fill=0.76)
                if blk_x is not None:
                    raw_blocks.append(blk_x)

    if max_w >= 1.20 - _EPS:
        y3_pool = [c for c in pair_pool[:14] if c.dy <= max_w * 0.6]
        for i, c1 in enumerate(y3_pool):
            for j in range(i + 1, len(y3_pool)):
                c2 = y3_pool[j]
                if c1.dy + c2.dy >= max_w - 0.12:
                    continue
                for c3 in y3_pool[j + 1 :]:
                    w_sum = c1.dy + c2.dy + c3.dy
                    if w_sum <= max_w + _EPS and (max_w - w_sum) < 0.12 + _EPS:
                        blk = _combine_columns_y([(c1, 1), (c2, 1), (c3, 1)], 1, rem_qty, rigid_map, min_fill=0.80)
                        if blk is not None:
                            raw_blocks.append(blk)

    seen, unique_blocks = set(), []
    for blk in raw_blocks:
        sig = (round(blk.dx, 3), round(blk.dy, 3), round(blk.dz, 3), tuple(sorted(blk.sku_counts.items())))
        if sig not in seen:
            seen.add(sig)
            unique_blocks.append(blk)
    def _score_key(b: CompoundBlock) -> Tuple[bool, int, bool, bool, bool, float]:
        has_rigid = any(rigid_map.get(sid, False) for sid in b.sku_counts)
        y_tight = (max_w - b.dy) < 0.12 - _EPS
        x_tight = is_tail_x and ((max_l - b.dx) < 0.12 - _EPS)
        max_rigid_ratio = max(
            (cnt / max(1, rem_qty.get(sid, 1)) for sid, cnt in b.sku_counts.items() if rigid_map.get(sid, False)),
            default=0.0,
        )
        score = (
            b.fill_ratio * 100.0 + (b.dz / target_h) * 40.0
            + max_rigid_ratio * 25.0 + b.completes_skus * 20.0
            + min(b.dy / max_w, 1.0) * 18.0 + (15.0 if y_tight else 0.0) + (15.0 if x_tight else 0.0)
        )
        return (has_rigid, b.completes_skus, y_tight or x_tight, b.fill_ratio >= 0.88 - _EPS, b.dz >= target_h - 0.08 - _EPS, score)

    unique_blocks.sort(key=_score_key, reverse=True)
    return unique_blocks[:limit]
