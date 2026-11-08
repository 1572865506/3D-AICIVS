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
TOP_CAVITY_LIMIT = 5


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
    eps = 1e-4
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
        if z > 1e-3 and ratio < 0.999 and side_contacts == 0:
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

    return {
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
