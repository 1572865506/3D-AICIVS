"""
自由空间审计工具（体素级）。

用途：回答"柜内空着多少、能不能放货、为什么放不进去"。
- 按高度/纵深分层统计自由空间分布
- 对剩余未装 SKU 做体素贪心试放（含支撑规则），给出"物理可放上限"
用于诊断"算法是否漏掉可用空间"与"空间是否真的不可用"。

用法：python scripts/audit_free_space.py tests/fixtures/production_15sku.json
"""
import argparse
import json
import math
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.solver.unified_solver import UnifiedSolver


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture")
    ap.add_argument("--res", type=float, default=0.05, help="体素边长（米）")
    args = ap.parse_args()

    case = json.load(open(args.fixture, encoding="utf-8"))
    c = InputAdapter.parse_container(case["container"])
    cargo = InputAdapter.parse_cargo_list(case["cargo"])
    sol = UnifiedSolver(c).solve(cargo)
    RES = args.res
    nx = int(math.ceil(c.Lx / RES)); ny = int(math.ceil(c.Ly / RES)); nz = int(math.ceil(c.Lz / RES))
    occ = bytearray(nx * ny * nz)

    def mark(x0, y0, z0, dx, dy, dz):
        ix0 = max(0, int(x0 / RES)); ix1 = min(nx, int(math.ceil((x0 + dx) / RES)))
        iy0 = max(0, int(y0 / RES)); iy1 = min(ny, int(math.ceil((y0 + dy) / RES)))
        iz0 = max(0, int(z0 / RES)); iz1 = min(nz, int(math.ceil((z0 + dz) / RES)))
        for ix in range(ix0, ix1):
            for iy in range(iy0, iy1):
                b = (ix * ny + iy) * nz
                for iz in range(iz0, iz1):
                    occ[b + iz] = 1

    for p in sol.placements:
        mark(p.position.x, p.position.y, p.position.z,
             p.orientation.dx, p.orientation.dy, p.orientation.dz)

    cell = RES ** 3
    zband = [0.0] * (int(c.Lz / 0.3) + 1)
    for ix in range(nx):
        for iy in range(ny):
            b = (ix * ny + iy) * nz
            for iz in range(nz):
                if not occ[b + iz]:
                    zband[min(len(zband) - 1, int(iz * RES / 0.3))] += cell
    free_total = sum(zband)
    print(f"利用率 {sol.volume_utilization_pct:.2f}% | 自由空间 {free_total:.2f} m3 "
          f"({100*free_total/c.volume:.1f}%) | 体素 {RES*100:.0f}cm")
    print("按高度分布:", " | ".join(f"{i*0.3:.1f}-{(i+1)*0.3:.1f}m:{v:.2f}"
                                 for i, v in enumerate(zband) if v > 0.05))

    placed_cnt = {}
    for p in sol.placements:
        placed_cnt[p.sku_id] = placed_cnt.get(p.sku_id, 0) + 1
    remaining = [(s.sku_id, s.quantity.required - placed_cnt.get(s.sku_id, 0),
                  (s.box.x, s.box.y, s.box.z), s.orientation_policy.allow_flat)
                 for s in cargo if s.quantity.required - placed_cnt.get(s.sku_id, 0) > 0]
    print("剩余未装:", [(sid, rem) for sid, rem, _, _ in remaining])

    for sid, rem, dims, allow_flat in remaining:
        l, w, h = dims
        oris = [(l, w, h), (w, l, h)]
        if allow_flat:
            oris += [(l, h, w), (h, l, w)]
        placed = 0
        for iz in range(nz - 1, -1, -1):
            for ix in range(nx):
                for iy in range(ny):
                    b = (ix * ny + iy) * nz
                    if occ[b + iz]:
                        continue
                    x0, y0, z0 = ix * RES, iy * RES, iz * RES
                    for dx, dy, dz in oris:
                        if x0 + dx > c.Lx + 1e-6 or y0 + dy > c.Ly + 1e-6 or z0 + dz > c.Lz + 1e-6:
                            continue
                        if z0 > 1e-6:
                            bz = int(round(z0 / RES)) - 1
                            if bz < 0 or not occ[(ix * ny + iy) * nz + bz]:
                                continue
                        ok = True
                        for jx in range(ix, int(math.ceil((x0 + dx) / RES))):
                            for jy in range(iy, int(math.ceil((y0 + dy) / RES))):
                                bb = (jx * ny + jy) * nz
                                for jz in range(iz, int(math.ceil((z0 + dz) / RES))):
                                    if occ[bb + jz]:
                                        ok = False
                                        break
                                if not ok:
                                    break
                            if not ok:
                                break
                        if ok:
                            mark(x0, y0, z0, dx, dy, dz)
                            placed += 1
                            break
                    if placed >= rem:
                        break
                if placed >= rem:
                    break
            if placed >= rem:
                break
        print(f"  {sid}: 剩余 {rem} | 体素贪心可再放 {placed} 件 "
              f"(≈{placed*dims[0]*dims[1]*dims[2]:.2f} m3)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
