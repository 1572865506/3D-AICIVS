"""
几何观感体检（Geometry QA）——把"3D 视图里看起来的空洞/狗牙/悬空"变成可计算、可对比的指标。

用途：求解结果的数值 KPI（利用率/违规数）无法表达肉眼可见的摆放质量问题：
装载体内部空腔、顶面台阶落差、半悬空箱、孤立箱、大竖井。本模块用纯几何
统计给出"观感评分卡"，供 API 输出、前端叠加渲染与优化目标使用。

输入：ContainerSpec、List[Placement]（或等效 dict）、可选空洞诊断列表。
输出：dict，字段见 compute_geometry_qa 文档。

被谁调用：UnifiedSolver.solve()（写入 telemetry.geometry_qa）、
backend/api/service.py（透出到 metrics.geometry_qa）。
"""
from typing import Any, Dict, List, Optional

GRID_M = 0.2  # 柱高采样网格（米）
STAIRCASE_BAD_DIFF = 0.30  # 相邻列高差"硬台阶"阈值（米）
LOW_SUPPORT_RATIO = 0.85  # 支撑面积比"明显不足"阈值
TOP_CAVITY_LIMIT = 20


def _box_of(p: Any):
    """兼容 Placement 对象与 dict 两种输入，返回 (x,y,z,dx,dy,dz)。"""
    if isinstance(p, dict):
        return p["x"], p["y"], p["z"], p["dx"], p["dy"], p["dz"]
    return (p.position.x, p.position.y, p.position.z,
            p.orientation.dx, p.orientation.dy, p.orientation.dz)


def compute_geometry_qa(
    container: Any,
    placements: List[Any],
    cavity_diagnostics: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    计算几何观感指标。

    核心字段：
    - bbox_void_ratio_pct：装载体包围盒内空洞率 = 1 - 货体 / 包围盒（肉眼"内部空掉多少"）
    - top_surface: 顶面平齐度（柱高分布的台阶统计）
    - support: 支撑充分度分布（半悬空/悬挑箱比例）
    - islands：四面无侧邻且非满支撑的孤立箱数
    - cavities：空洞清单（内部封闭 vs 开口可达）+ 合计体积
    - verdict：按阈值给出 GOOD / FAIR / POOR 总评（便于业务方直接看）
    """
    if not placements:
        return {
            "bbox_void_ratio_pct": 0.0, "cargo_volume_m3": 0.0, "bbox_volume_m3": 0.0,
            "top_surface": {}, "support": {}, "islands": 0,
            "cavities": {}, "verdict": "EMPTY",
        }

    boxes = [_box_of(p) for p in placements]
    cargo_vol = sum(dx * dy * dz for _, _, _, dx, dy, dz in boxes)
    max_x = max(x + dx for x, _, _, dx, _, _ in boxes)
    max_y = max(y + dy for _, y, _, _, dy, _ in boxes)
    max_z = max(z + dz for _, _, z, _, _, dz in boxes)
    bbox_vol = max(1e-9, max_x * max_y * max_z)
    bbox_void_ratio = max(0.0, 1.0 - cargo_vol / bbox_vol)

    # ---- 顶面平齐度：0.2m 网格列高 + 相邻列高差 ----
    grid: Dict[tuple, float] = {}
    for x, y, z, dx, dy, dz in boxes:
        top = z + dz
        # 覆盖填充：逐网格记录该位置的最高点（此前只采样最小角点，统计失真）
        cx0, cx1 = int(x / GRID_M), int(-(-(x + dx) // GRID_M))
        cy0, cy1 = int(y / GRID_M), int(-(-(y + dy) // GRID_M))
        for cx in range(cx0, max(cx0 + 1, cx1)):
            for cy in range(cy0, max(cy0 + 1, cy1)):
                key = (cx, cy)
                if top > grid.get(key, 0.0):
                    grid[key] = top
    heights = list(grid.values())
    diffs: List[float] = []
    for (cx, cy), h in grid.items():
        for nb in ((cx + 1, cy), (cx, cy + 1)):
            oh = grid.get(nb)
            if oh is not None:
                diffs.append(abs(h - oh))
    diffs.sort()
    heights_sorted = sorted(heights)

    def _pct(arr: List[float], q: float) -> float:
        if not arr:
            return 0.0
        idx = min(len(arr) - 1, max(0, int(round(q * (len(arr) - 1)))))
        return arr[idx]

    top_band = sum(
        dx * dy * dz for x, y, z, dx, dy, dz in boxes
        if z + dz >= container.Lz - 0.15
    )
    top_surface = {
        "column_count": len(grid),
        "column_height_median_m": round(_pct(heights_sorted, 0.5), 3),
        "column_height_min_m": round(heights_sorted[0], 3) if heights_sorted else 0.0,
        "adjacent_diff_median_m": round(_pct(diffs, 0.5), 3),
        "adjacent_diff_p90_m": round(_pct(diffs, 0.9), 3),
        "adjacent_diff_max_m": round(diffs[-1], 3) if diffs else 0.0,
        "steep_step_ratio_pct": round(
            100.0 * sum(1 for d in diffs if d > STAIRCASE_BAD_DIFF) / max(1, len(diffs)), 2
        ),
        "near_ceiling_volume_pct": round(100.0 * top_band / max(1e-9, container.volume), 2),
        "top_headroom_volume_m3": round(max(0.0, (container.Lz - max_z) * max_x * max_y), 3),
    }

    # ---- 支撑充分度 + 孤立箱 ----
    ratios: List[float] = []
    islands = 0
    flat_cover_count = 0
    eps = 1e-4
    # 平放覆盖层（orientation 名含 FLAT）是业务允许的顶层覆盖结构：
    # 它们天然只与下方有接触、无侧邻，不应计入"孤立箱"
    cover_flags = []
    for p in placements:
        if isinstance(p, dict):
            cover_flags.append("FLAT" in str(p.get("orientation", "")).upper())
        else:
            cover_flags.append("FLAT" in str(getattr(p.orientation, "name", "")).upper())
    for i, (x, y, z, dx, dy, dz) in enumerate(boxes):
        area = max(1e-9, dx * dy)
        support = 0.0
        side_contacts = 0
        for j, (ox, oy, oz, odx, ody, odz) in enumerate(boxes):
            if i == j:
                continue
            ix = min(x + dx, ox + odx) - max(x, ox)
            iy = min(y + dy, oy + ody) - max(y, oy)
            iz = min(z + dz, oz + odz) - max(z, oz)
            if ix > eps and iy > eps and abs((oz + odz) - z) < 1e-3:
                support += ix * iy
            if iz > eps:
                if (ix > eps and iy > eps) or (ix > eps and abs(oy - (y + dy)) < 0.01) \
                        or (ix > eps and abs(oy + ody - y) < 0.01) \
                        or (iy > eps and abs(ox - (x + dx)) < 0.01) \
                        or (iy > eps and abs(ox + odx - x) < 0.01):
                    side_contacts += 1
        ratio = 1.0 if z <= 1e-3 else min(1.0, support / area)
        ratios.append(ratio)
        is_cover = cover_flags[i] if i < len(cover_flags) else False
        if is_cover:
            flat_cover_count += 1
        elif z > 1e-3 and ratio < 0.999 and side_contacts == 0:
            islands += 1
    ratios.sort()
    support_stats = {
        "min_ratio": round(ratios[0], 4) if ratios else 1.0,
        "p10_ratio": round(_pct(ratios, 0.1), 4),
        "median_ratio": round(_pct(ratios, 0.5), 4),
        "partial_support_ratio_pct": round(
            100.0 * sum(1 for r in ratios if r < 0.999) / max(1, len(ratios)), 2
        ),
        "low_support_count": sum(1 for r in ratios if r < LOW_SUPPORT_RATIO),
        "island_count": islands,
        "flat_cover_count": flat_cover_count,
    }

    # ---- 体素级"隐蔽空洞"：肉眼看到的洞 = 低于本地柱顶的自由空间 ----
    # 人看 3D 图时，柱顶以上是"顶面不齐"，柱顶以下被四周货挡住的是"洞"。
    # 用 0.1m 体素：每 XY 列取最高占有 z（本地天窗线），其下的自由格即隐蔽空洞。
    vox = 0.1
    nxv = max(1, int(round(container.Lx / vox)))
    nyv = max(1, int(round(container.Ly / vox)))
    nzv = max(1, int(round(container.Lz / vox)))
    occupied = bytearray(nxv * nyv * nzv)

    def _mark(x0, y0, z0, x1, y1, z1):
        cx0 = max(0, int(x0 / vox)); cx1 = min(nxv, int(-(-x1 // vox)))
        cy0 = max(0, int(y0 / vox)); cy1 = min(nyv, int(-(-y1 // vox)))
        cz0 = max(0, int(z0 / vox)); cz1 = min(nzv, int(-(-z1 // vox)))
        for ix in range(cx0, cx1):
            for iy in range(cy0, cy1):
                base = (ix * nyv + iy) * nzv
                for iz in range(cz0, cz1):
                    occupied[base + iz] = 1

    for x, y, z, dx, dy, dz in boxes:
        _mark(x, y, z, x + dx, y + dy, z + dz)

    cell = vox ** 3
    # skyline：每 XY 列的最高占有高度（无货则为 0）
    skyline = [0] * (nxv * nyv)
    for ix in range(nxv):
        for iy in range(nyv):
            base = (ix * nyv + iy) * nzv
            top = 0
            for iz in range(nzv - 1, -1, -1):
                if occupied[base + iz]:
                    top = iz + 1
                    break
            skyline[ix * nyv + iy] = top

    hidden = 0
    skyline_void = 0
    for ix in range(nxv):
        for iy in range(nyv):
            base = (ix * nyv + iy) * nzv
            top = skyline[ix * nyv + iy]
            if top == 0:
                continue  # 无货的整列属于"未使用面积"，不计入空洞（口径与肉眼一致）
            for iz in range(nzv):
                if occupied[base + iz]:
                    continue
                if iz < top:
                    hidden += 1
                else:
                    skyline_void += 1
    hidden_vol = hidden * cell
    skyline_vol = skyline_void * cell

    # ---- 空洞：内部封闭（肉眼可见"洞"）vs 开口可达 ----
    cavs = [c for c in (cavity_diagnostics or []) if c.get("box")]
    enclosed_vol = 0.0
    open_vol = 0.0
    top_list = []
    for c in cavs:
        bx0, by0, bz0, bx1, by1, bz1 = c["box"]
        touches_door = bx1 >= container.Lx - 0.05
        touches_roof = bz1 >= container.Lz - 0.05
        vol = float(c.get("volume", 0.0))
        if touches_door or touches_roof:
            open_vol += vol
        else:
            enclosed_vol += vol
        top_list.append({
            "box": list(c["box"]),
            "volume_m3": round(vol, 3),
            "dims": [round(bx1 - bx0, 3), round(by1 - by0, 3), round(bz1 - bz0, 3)],
            "category": c.get("exclusion_category"),
            "constraint": c.get("excluded_by_constraint"),
            "open": bool(touches_door or touches_roof),
        })
    top_list.sort(key=lambda c: -c["volume_m3"])
    cavities = {
        "count": len(cavs),
        "total_volume_m3": round(enclosed_vol + open_vol, 3),
        "enclosed_volume_m3": round(enclosed_vol, 3),
        "enclosed_volume_pct_of_bbox": round(100.0 * enclosed_vol / bbox_vol, 2),
        "open_volume_m3": round(open_vol, 3),
        "largest_volume_m3": round(top_list[0]["volume_m3"], 3) if top_list else 0.0,
        "hidden_void_volume_m3": round(hidden_vol, 3),
        "hidden_void_pct_of_bbox": round(100.0 * hidden_vol / bbox_vol, 2),
        "skyline_void_volume_m3": round(skyline_vol, 3),
        "skyline_void_pct_of_bbox": round(100.0 * skyline_vol / bbox_vol, 2),
        "top": top_list[:TOP_CAVITY_LIMIT],
    }

    # ---- 总评（业务方可直接读）----
    score_penalty = (
        (bbox_void_ratio * 100.0) * 0.6
        + cavities["hidden_void_pct_of_bbox"] * 1.4
        + top_surface["steep_step_ratio_pct"] * 0.3
        + support_stats["partial_support_ratio_pct"] * 0.2
        + support_stats["island_count"] * 2.0
    )
    if score_penalty <= 15:
        verdict = "GOOD"
    elif score_penalty <= 30:
        verdict = "FAIR"
    else:
        verdict = "POOR"

    plan_quality = _plan_quality(boxes, placements, container)

    return {
        "plan_quality": plan_quality,
        "bbox_void_ratio_pct": round(bbox_void_ratio * 100.0, 2),
        "cargo_volume_m3": round(cargo_vol, 3),
        "bbox_volume_m3": round(bbox_vol, 3),
        "container_utilization_pct": round(100.0 * cargo_vol / max(1e-9, container.volume), 2),
        "top_surface": top_surface,
        "support": support_stats,
        "islands": islands,
        "cavities": cavities,
        "penalty_score": round(score_penalty, 2),
        "verdict": verdict,
    }


# ===================================================================
# 方案质量评分卡（Plan Quality Scorecard）
# 目的：补足"看得见但说不清"的观感/结构问题，给出可解释分项与总分。
# 所有分量都是纯几何统计，不依赖外部数据；分值越高越好（0~100）。
# ===================================================================

def _plan_quality(boxes, placements, container) -> Dict[str, Any]:
    """计算方案质量评分卡（墙体连续性/层平面度/聚集度/重心高度/门面平整/碎片化）。"""
    n = len(boxes)
    if n == 0:
        return {"score": 0.0, "grade": "D", "components": {}}

    # --- 1) 墙体连续性：同尺寸 + 同朝向 的侧向邻接率 ---
    lateral_contacts = 0
    lateral_same = 0
    for i, (x, y, z, dx, dy, dz) in enumerate(boxes):
        ori_i = _orientation_name(placements[i])
        for j, (ox, oy, oz, odx, ody, odz) in enumerate(boxes):
            if i == j:
                continue
            same_dims = (abs(dx - odx) < 0.02 and abs(dy - ody) < 0.02 and abs(dz - odz) < 0.02)
            z_ov = min(z + dz, oz + odz) - max(z, oz)
            y_touch = (abs(oy - (y + dy)) < 0.02) or (abs(oy + ody - y) < 0.02)
            x_touch = (abs(ox - (x + dx)) < 0.02) or (abs(ox + odx - x) < 0.02)
            if z_ov <= 1e-4:
                continue
            if y_touch and min(x + dx, ox + odx) - max(x, ox) > 1e-4:
                lateral_contacts += 1
                if same_dims and ori_i == _orientation_name(placements[j]):
                    lateral_same += 1
            elif x_touch and min(y + dy, oy + ody) - max(y, oy) > 1e-4:
                lateral_contacts += 1
                if same_dims and ori_i == _orientation_name(placements[j]):
                    lateral_same += 1
    wall_continuity_pct = round(100.0 * lateral_same / max(1, lateral_contacts), 1)

    # --- 2) 层平面度：顶面高度落在"主平面 ±5cm"内的箱体面积占比 ---
    import collections
    heights = [z + dz for (_, _, z, _, _, dz) in boxes]
    buckets = collections.Counter(round(h / 0.05) * 0.05 for h in heights)
    top_planes = [h for h, _ in buckets.most_common(3)]
    in_plane_area = 0.0
    total_area = 0.0
    for (_, _, z, dx, dy, dz) in boxes:
        area = dx * dy
        total_area += area
        top = z + dz
        if any(abs(top - h) <= 0.05 for h in top_planes):
            in_plane_area += area
    layer_planarity_pct = round(100.0 * in_plane_area / max(1e-9, total_area), 1)

    # --- 3) 同 SKU 聚集度：相邻接触中同 SKU 比例 ---
    contact_pairs = 0
    same_sku_pairs = 0
    skus = [p.get("sku_id") if isinstance(p, dict) else p.sku_id for p in placements]
    for i, (x, y, z, dx, dy, dz) in enumerate(boxes):
        for j, (ox, oy, oz, odx, ody, odz) in enumerate(boxes):
            if i >= j:
                continue
            y_ov = min(y + dy, oy + ody) - max(y, oy)
            z_ov = min(z + dz, oz + odz) - max(z, oz)
            x_ov = min(x + dx, ox + odx) - max(x, ox)
            touching = (
                (abs(ox - (x + dx)) < 0.02 or abs(ox + odx - x) < 0.02) and y_ov > -0.02 and z_ov > -0.02
            ) or (
                (abs(oy - (y + dy)) < 0.02 or abs(oy + ody - y) < 0.02) and x_ov > -0.02 and z_ov > -0.02
            )
            if touching:
                contact_pairs += 1
                if skus[i] == skus[j]:
                    same_sku_pairs += 1
    sku_clustering_pct = round(100.0 * same_sku_pairs / max(1, contact_pairs), 1)

    # --- 4) 重心高度（按体积加权，越低越稳）---
    total_vol = sum(dx * dy * dz for (_, _, _, dx, dy, dz) in boxes) or 1e-9
    cog_z = sum((z + dz / 2) * dx * dy * dz for (_, _, z, dx, dy, dz) in boxes) / total_vol
    cog_height_pct = round(100.0 * cog_z / max(1e-9, container.Lz), 1)

    # --- 5) 门面平整度：最外层（门侧 0.3m 内）箱体前沿 x 的变异系数 ---
    max_x = max(x + dx for (x, _, _, dx, _, _) in boxes)
    front_xs = [x + dx for (x, _, _, dx, _, _) in boxes if x + dx >= max_x - 0.3]
    if len(front_xs) >= 2:
        mean = sum(front_xs) / len(front_xs)
        var = sum((v - mean) ** 2 for v in front_xs) / len(front_xs)
        cv = (var ** 0.5) / max(1e-9, mean)
        door_flatness_cv_pct = round(100.0 * cv, 1)
    else:
        door_flatness_cv_pct = 0.0

    # --- 6) 碎片化：每 0.3m 高度层内的 SKU 切换指数（不同 SKU 数 / 箱数）---
    layer_skus = collections.defaultdict(set)
    layer_counts = collections.Counter()
    for i, (_, _, z, _, _, dz) in enumerate(boxes):
        key = round(z / 0.3)
        layer_skus[key].add(skus[i])
        layer_counts[key] += 1
    frag = sum(len(layer_skus[k]) / max(1, layer_counts[k]) for k in layer_skus) / max(1, len(layer_skus))
    fragmentation_pct = round(100.0 * frag, 1)

    # --- 综合评分（权重显式、可解释）---
    def _score_high(v, floor, ceil):
        return max(0.0, min(100.0, 100.0 * (v - floor) / max(1e-9, ceil - floor)))

    def _score_low(v, good, bad):
        return max(0.0, min(100.0, 100.0 * (bad - v) / max(1e-9, bad - good)))

    parts = {
        "wall_continuity": (_score_high(wall_continuity_pct, 20.0, 85.0), 0.25),
        "layer_planarity": (_score_high(layer_planarity_pct, 30.0, 90.0), 0.25),
        "sku_clustering": (_score_high(sku_clustering_pct, 20.0, 85.0), 0.15),
        "cog_height": (_score_low(cog_height_pct, 30.0, 65.0), 0.15),
        "door_flatness": (_score_low(door_flatness_cv_pct, 0.0, 8.0), 0.10),
        "fragmentation": (_score_low(fragmentation_pct, 5.0, 40.0), 0.10),
    }
    score = round(sum(v * w for v, w in parts.values()), 1)
    grade = "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 50 else "D"

    return {
        "score": score,
        "grade": grade,
        "components": {
            "wall_continuity_pct": wall_continuity_pct,
            "layer_planarity_pct": layer_planarity_pct,
            "sku_clustering_pct": sku_clustering_pct,
            "cog_height_pct": cog_height_pct,
            "door_flatness_cv_pct": door_flatness_cv_pct,
            "fragmentation_pct": fragmentation_pct,
        },
        "component_scores": {k: round(v, 1) for k, (v, _) in parts.items()},
        "weights": {k: w for k, (_, w) in parts.items()},
    }


def _orientation_name(p) -> str:
    if isinstance(p, dict):
        return str(p.get("orientation", ""))
    return str(getattr(getattr(p, "orientation", None), "name", ""))
