"""
XYZ 多轴保底评估器（v1.3 软审计模式）
================================================================
对已放置货物做三轴视图（俯视 XZ / 侧视 XY / 正视 ZY）质量分析：

1. 悬浮 Floating : y>0 且底面无直接支撑的箱子（放置约束的全局兜底检查，正常应为 0）
2. 中空 Hollow   : 局部体素化后，空体素与"开放空间"(区域 x 两侧 / 容器壁侧 / 顶部)
                   不连通的区域 = 被货物包围的空洞
3. 漏放 Missed   : 中空连通域的外接盒能容纳某个剩余 SKU 的安全朝向，但未放入

软审计模式：只产出指标，不硬阻塞装载（是否收紧为硬约束由后续版本 weights 决定）。
输出定位信息供前端对缺陷区域着色可视化，同时是"回退重排闭环"升级的数据基础。

性能：体素化 + BFS，复杂度 O(区域体素数)。局部墙切片约 2.5万-10万 体素，
全量终检约 61万 体素（40HQ @ 5cm 网格），单次评估 < 1s。
"""

import math
from collections import deque
from typing import List, Dict, Any, Optional, Callable


class XYZFallbackEvaluator:
    def __init__(self, L: float, W: float, H: float, grid: float = 0.05, gap: float = 0.0):
        self.L, self.W, self.H = L, W, H
        self.grid = grid
        self.gap = max(0.0, float(gap or 0.0))
        self.eval_count = 0

    # ------------------------------------------------------------------
    # 悬浮检测（与 packer._direct_supports 等价，独立实现保持解耦）
    # ------------------------------------------------------------------
    @staticmethod
    def _direct_supports(cand: Dict[str, float], placed_boxes: List[Dict[str, Any]], gap: float = 0.0) -> List[Dict[str, Any]]:
        supports = []
        for b in placed_boxes:
            # gap 模式：上层箱 y = 下层箱顶面 + gap，仍视为有支撑（非悬浮）
            if abs(b['y'] + b['h'] + gap - cand['y']) > 0.0015:
                continue
            if (b['x'] + b['w'] > cand['x'] + 0.0005 and cand['x'] + cand['w'] > b['x'] + 0.0005 and
                    b['z'] + b['d'] > cand['z'] + 0.0005 and cand['z'] + cand['d'] > b['z'] + 0.0005):
                supports.append(b)
        return supports

    def _check_floating(self, placed_boxes: List[Dict[str, Any]], x0: float, x1: float) -> List[Dict[str, Any]]:
        floating = []
        for i, b in enumerate(placed_boxes):
            if b['y'] < 0.001:
                continue
            if b['x'] >= x1 - 1e-9 or b['x'] + b['w'] <= x0 + 1e-9:
                continue
            if not self._direct_supports(b, placed_boxes, self.gap):
                floating.append({
                    'index': i, 'sku': b.get('sku', '?'),
                    'x': round(b['x'], 3), 'y': round(b['y'], 3), 'z': round(b['z'], 3)
                })
        return floating

    # ------------------------------------------------------------------
    # 体素化（局部区域 [x0, x1] × [0, W] × [0, H]）
    # ------------------------------------------------------------------
    def _voxelize(self, placed_boxes: List[Dict[str, Any]], x0: float, x1: float):
        g = self.grid
        nx = max(1, int(math.ceil((x1 - x0) / g)))
        ny = max(1, int(math.ceil(self.H / g)))
        nz = max(1, int(math.ceil(self.W / g)))
        occ = bytearray(nx * ny * nz)
        for b in placed_boxes:
            bx0, bx1 = b['x'], b['x'] + b['w']
            if bx1 <= x0 - 1e-9 or bx0 >= x1 + 1e-9:
                continue
            ix0 = max(0, int(math.floor((bx0 - x0) / g)))
            ix1 = min(nx - 1, int(math.ceil((bx1 - x0) / g)) - 1)
            iy0 = max(0, int(math.floor(b['y'] / g)))
            iy1 = min(ny - 1, int(math.ceil((b['y'] + b['h']) / g)) - 1)
            iz0 = max(0, int(math.floor(b['z'] / g)))
            iz1 = min(nz - 1, int(math.ceil((b['z'] + b['d']) / g)) - 1)
            for ix in range(ix0, ix1 + 1):
                base_x = (ix * ny) * nz
                for iy in range(iy0, iy1 + 1):
                    base = base_x + iy * nz
                    for iz in range(iz0, iz1 + 1):
                        occ[base + iz] = 1
        return occ, nx, ny, nz

    # ------------------------------------------------------------------
    # 中空分析：BFS 从开放源扩散，未达的空体素 = 中空
    # ------------------------------------------------------------------
    def _hollow_analysis(self, occ: bytearray, nx: int, ny: int, nz: int):
        g = self.grid
        total = nx * ny * nz
        open_flag = bytearray(total)
        dq = deque()

        def idx(ix, iy, iz):
            return (ix * ny + iy) * nz + iz

        def try_open(ix, iy, iz):
            if 0 <= ix < nx and 0 <= iy < ny and 0 <= iz < nz:
                p = idx(ix, iy, iz)
                if occ[p] == 0 and open_flag[p] == 0:
                    open_flag[p] = 1
                    dq.append(p)

        # 开放源：顶部整面 + 区域 x 两侧 + z 两侧（容器壁 / 未装空间）
        for ix in range(nx):
            for iz in range(nz):
                try_open(ix, ny - 1, iz)
        for iy in range(ny):
            for iz in range(nz):
                try_open(0, iy, iz)
                try_open(nx - 1, iy, iz)
        for ix in range(nx):
            for iy in range(ny):
                try_open(ix, iy, 0)
                try_open(ix, iy, nz - 1)

        while dq:
            p = dq.popleft()
            ix = p // (ny * nz)
            r = p % (ny * nz)
            iy = r // nz
            iz = r % nz
            for di, dj, dk in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                nix, niy, niz = ix + di, iy + dj, iz + dk
                if 0 <= nix < nx and 0 <= niy < ny and 0 <= niz < nz:
                    np_ = idx(nix, niy, niz)
                    if occ[np_] == 0 and open_flag[np_] == 0:
                        open_flag[np_] = 1
                        dq.append(np_)

        hollow_cells = [p for p in range(total) if occ[p] == 0 and open_flag[p] == 0]
        hollow_vol = len(hollow_cells) * (g ** 3)
        return hollow_cells, hollow_vol

    # ------------------------------------------------------------------
    # 漏放检测：中空连通域外接盒能否容纳剩余 SKU
    # ------------------------------------------------------------------
    @staticmethod
    def _all_orientations(sku: Dict[str, Any], max_l: float, max_h: float, max_d: float) -> List[Dict[str, float]]:
        w, d, h = float(sku['w']), float(sku['d']), float(sku['h'])
        cands = [(w, d, h), (d, w, h), (w, h, d), (d, h, w), (h, w, d), (h, d, w)]
        return [{'l': l, 'wz': z, 'h': hh} for l, z, hh in cands
                if l <= max_l + 0.001 and z <= max_d + 0.001 and hh <= max_h + 0.001]

    def _missed(self, occ: bytearray, hollow_cells: List[int], nx: int, ny: int, nz: int,
                x0: float, remaining_skus: List[Dict[str, Any]],
                orientation_fn: Optional[Callable] = None):
        g = self.grid
        if not hollow_cells:
            return 0.0, []
        seen = set(hollow_cells)  # 先全部标记，BFS 只在 hollow 内部
        missed_vol = 0.0
        regions = []
        for start in hollow_cells:
            if start not in seen:
                continue
            seen.remove(start)
            comp = []
            dq = deque([start])
            while dq:
                p = dq.popleft()
                comp.append(p)
                ix = p // (ny * nz)
                r = p % (ny * nz)
                iy = r // nz
                iz = r % nz
                for di, dj, dk in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                    nix, niy, niz = ix + di, iy + dj, iz + dk
                    if 0 <= nix < nx and 0 <= niy < ny and 0 <= niz < nz:
                        np_ = (nix * ny + niy) * nz + niz
                        if np_ in seen:
                            seen.remove(np_)
                            dq.append(np_)
            # 外接盒
            ixs = [p // (ny * nz) for p in comp]
            rs = [p % (ny * nz) for p in comp]
            iys = [r // nz for r in rs]
            izs = [r % nz for r in rs]
            x_len = (max(ixs) - min(ixs) + 1) * g
            y_len = (max(iys) - min(iys) + 1) * g
            z_len = (max(izs) - min(izs) + 1) * g
            fit = False
            for s in remaining_skus:
                if s.get('remQty', 0) <= 0:
                    continue
                if orientation_fn:
                    oris = orientation_fn(s, x_len, y_len, z_len)
                else:
                    oris = self._all_orientations(s, x_len, y_len, z_len)
                if oris:
                    fit = True
                    break
            if fit:
                vol = len(comp) * (g ** 3)
                missed_vol += vol
                regions.append({
                    'x0': round(x0 + min(ixs) * g, 3),
                    'x1': round(x0 + (max(ixs) + 1) * g, 3),
                    'y0': round(min(iys) * g, 3),
                    'y1': round((max(iys) + 1) * g, 3),
                    'z0': round(min(izs) * g, 3),
                    'z1': round((max(izs) + 1) * g, 3),
                    'volumeM3': round(vol, 4),
                    'cells': len(comp)
                })
        return missed_vol, regions

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def evaluate(self, placed_boxes: List[Dict[str, Any]],
                 remaining_skus: List[Dict[str, Any]],
                 x0: float, x1: float,
                 orientation_fn: Optional[Callable] = None) -> Dict[str, Any]:
        """对 [x0, x1] 区域做 XYZ 三轴质量评估，返回 audit 字典（软审计，不阻塞）"""
        self.eval_count += 1
        floating = self._check_floating(placed_boxes, x0, x1)
        occ, nx, ny, nz = self._voxelize(placed_boxes, x0, x1)
        hollow_cells, hollow_vol = self._hollow_analysis(occ, nx, ny, nz)
        missed_vol, missed_regions = self._missed(occ, hollow_cells, nx, ny, nz, x0,
                                                  remaining_skus, orientation_fn)
        container_vol = self.L * self.W * self.H
        region_vol = max(1e-9, (x1 - x0) * self.W * self.H)
        return {
            'floatingCount': len(floating),
            'floatingBoxes': floating[:20],
            'hollowVolumeM3': round(hollow_vol, 4),
            'hollowRatio': round(hollow_vol / container_vol * 100.0, 3),
            'missedVolumeM3': round(missed_vol, 4),
            'missedRatio': round(missed_vol / container_vol * 100.0, 3),
            'evaluatedRegionM3': round(region_vol, 3),
            'regionX': [round(x0, 3), round(x1, 3)],
            'missedRegions': missed_regions[:20]
        }
