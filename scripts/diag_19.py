# -*- coding: utf-8 -*-
"""#19 诊断：指定参数下部分切片行为与未放置构成"""
import sys, io, copy, collections
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, 'backend')
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

kwargs = {}
for a in sys.argv[1:]:
    k, v = a.split('=')
    kwargs[k] = (True if v == 'true' else False if v == 'false' else
                 float(v) if '.' in v else int(v) if v.isdigit() else v)

packer = IndustrialSmartContainerPacker(CONTAINER, None, **kwargs)
r = packer.pack(copy.deepcopy(MANIFEST), debug=True)

print(f"\nplaced={r['totalCount']} util={r['utilization']}% flatness={r['flatness']}")
placed_by = {}
for b in r['placedBoxes']:
    placed_by[b['sku']] = placed_by.get(b['sku'], 0) + 1
print('未放置:', {s['sku']: s['quantity'] - placed_by.get(s['sku'], 0)
                  for s in MANIFEST if placed_by.get(s['sku'], 0) < s['quantity']})
tops = packer._col_tops
print(f"col_tops: n={len(tops)} min={min(tops):.2f} max={max(tops):.2f}")
lows = sorted(t for t in tops if t < 2.0)
print("低列(尾数拼装):", [round(t, 2) for t in lows])
