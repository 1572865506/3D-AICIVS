# -*- coding: utf-8 -*-
"""#18 诊断：孤儿列抑制后的未放置分布 + 低列清单（cluster 基线）"""
import sys, os, io, copy
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backend'))
from industrial_packer import IndustrialSmartContainerPacker

CONTAINER = {'code': '40HQ', 'usable': {'L': 12.032, 'W': 2.352, 'H': 2.698}, 'maxPayloadTons': 28.6}
MANIFEST = [
    {'sku': 'SKU-01', 'w': 0.50, 'd': 0.50, 'h': 0.50, 'weight': 5.0, 'quantity': 1, 'requirement': '放柜子最里面'},
    {'sku': 'SKU-02', 'w': 0.553, 'd': 0.08, 'h': 0.355, 'weight': 8.4, 'quantity': 500, 'requirement': '封柜门'},
    {'sku': 'SKU-03', 'w': 0.978, 'd': 0.188, 'h': 0.488, 'weight': 4.61, 'quantity': 90, 'requirement': '封柜门'},
    {'sku': 'SKU-04', 'w': 0.68, 'd': 0.122, 'h': 0.44, 'weight': 6.7, 'quantity': 100, 'requirement': '封柜门'},
    {'sku': 'SKU-05', 'w': 0.833, 'd': 0.53, 'h': 0.23, 'weight': 20.8, 'quantity': 100, 'requirement': '放中间'},
    {'sku': 'SKU-06', 'w': 0.575, 'd': 0.46, 'h': 0.465, 'weight': 4.0, 'quantity': 95, 'requirement': '放中间'},
    {'sku': 'SKU-07', 'w': 0.431, 'd': 0.422, 'h': 0.281, 'weight': 4.0, 'quantity': 125, 'requirement': '放中间'},
    {'sku': 'SKU-08', 'w': 0.56, 'd': 0.145, 'h': 0.41, 'weight': 12.65, 'quantity': 53, 'requirement': '放中间'},
    {'sku': 'SKU-09', 'w': 0.495, 'd': 0.145, 'h': 0.41, 'weight': 10.5, 'quantity': 24, 'requirement': '放中间'},
    {'sku': 'SKU-10', 'w': 0.49, 'd': 0.28, 'h': 0.35, 'weight': 15.5, 'quantity': 22, 'requirement': '放中间'},
    {'sku': 'SKU-11', 'w': 0.48, 'd': 0.31, 'h': 0.34, 'weight': 25.5, 'quantity': 10, 'requirement': '放中间'},
    {'sku': 'SKU-12', 'w': 0.18, 'd': 0.18, 'h': 0.34, 'weight': 5.5, 'quantity': 1, 'requirement': '放中间'},
    {'sku': 'SKU-13', 'w': 0.43, 'd': 0.41, 'h': 0.19, 'weight': 15.5, 'quantity': 50, 'requirement': '放中间'},
    {'sku': 'SKU-14', 'w': 0.488, 'd': 0.08, 'h': 0.336, 'weight': 2.15, 'quantity': 674, 'requirement': '封柜门; 可以减少点'},
]

import sys
DISABLE = '--no-penalty' in sys.argv
TRACE = '--trace' in sys.argv
MEC = '--mec' in sys.argv
packer = IndustrialSmartContainerPacker(CONTAINER,
                                        {'minColHeightRatio': 0.0} if DISABLE else None,
                                        strategy='mec' if MEC else 'cluster')
r = packer.pack(copy.deepcopy(MANIFEST), debug=TRACE)

print(f"placed={r['totalCount']} util={r['utilization']}% flatness={r['flatness']}")
print("\n=== 每SKU 放置情况 ===")
placed_by = {}
for b in r['placedBoxes']:
    placed_by[b['sku']] = placed_by.get(b['sku'], 0) + 1
for s in MANIFEST:
    sku = s['sku']
    p = placed_by.get(sku, 0)
    flag = '  <-- 未放完' if p < s['quantity'] else ''
    print(f"  {sku}: qty={s['quantity']} placed={p}{flag}")

print("\n=== 低列清单（top < 2.0m） ===")
cols_map = {}
for b in r['placedBoxes']:
    k = (round(b['x'], 3), round(b['z'], 3))
    if k not in cols_map or b['y'] + b['h'] > cols_map[k][0]:
        cols_map[k] = (b['y'] + b['h'], b['sku'])
lows = sorted(((v[0], k, v[1]) for k, v in cols_map.items() if v[0] < 2.0))
for top, (x, z), sku in lows:
    n = sum(1 for b in r['placedBoxes'] if round(b['x'],3)==x and round(b['z'],3)==z)
    print(f"  x={x} z={z} sku={sku} top={top:.2f} boxes={n}")
print(f"\n低列总数: {len(lows)}")

print("\n=== 列顶分布 ===")
tops = packer._col_tops
print(f"cols={len(tops)} max={max(tops):.3f} min={min(tops):.3f}")
import collections
bucket = collections.Counter(round(t, 1) for t in tops)
for k in sorted(bucket):
    print(f"  top~{k:.1f}m: {bucket[k]} 列")

print("\n=== SKU-14 空间分布（按x分桶） ===")
xb = collections.Counter(round(b['x'], 0) for b in r['placedBoxes'] if b['sku'] == 'SKU-14')
for k in sorted(xb):
    print(f"  x~{k}m: {xb[k]} 箱")
print("\n=== 全部箱子按x分桶 ===")
xb2 = collections.Counter(round(b['x'], 0) for b in r['placedBoxes'])
for k in sorted(xb2):
    print(f"  x~{k}m: {xb2[k]} 箱")
ys = [b['y'] for b in r['placedBoxes'] if b['sku'] == 'SKU-14']
if ys:
    print(f"SKU-14 y范围: {min(ys):.2f}~{max(ys):.2f}")
