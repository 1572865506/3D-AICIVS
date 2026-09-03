# -*- coding: utf-8 -*-
"""
v1.7.0 全局规划层 A/B 验证：usePlan on/off 对照
用例：生产清单 40HQ 5 组（cluster/gap/mec/cogOFF/mec+gap）+ 混合尺寸压力清单
断言：安全不变（floating=0/collisions=0）；报告利用率/未放置/flatness 增量
"""
import sys, io, copy
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

# 压力清单：多尺寸混合 + 全朝向自由 + 大批量薄货（考验 vpd 全局朝向选择）
STRESS = [
    {'sku': 'P-01', 'w': 1.10, 'd': 0.75, 'h': 0.90, 'weight': 30.0, 'quantity': 60, 'requirement': '放柜子最里面', 'allowedOrientation': 'any'},
    {'sku': 'P-02', 'w': 0.62, 'd': 0.44, 'h': 0.38, 'weight': 9.0, 'quantity': 300, 'requirement': '放中间', 'allowedOrientation': 'any'},
    {'sku': 'P-03', 'w': 0.30, 'd': 0.22, 'h': 0.15, 'weight': 2.0, 'quantity': 800, 'requirement': '放中间'},
    {'sku': 'P-04', 'w': 0.86, 'd': 0.60, 'h': 0.55, 'weight': 18.0, 'quantity': 120, 'requirement': '放中间', 'allowedOrientation': 'any'},
    {'sku': 'P-05', 'w': 0.44, 'd': 0.33, 'h': 0.28, 'weight': 6.0, 'quantity': 260, 'requirement': '封柜门'},
    {'sku': 'P-06', 'w': 0.51, 'd': 0.10, 'h': 0.40, 'weight': 4.5, 'quantity': 420, 'requirement': '封柜门'},
]

CASES = [
    ('baseline cluster/gap0/cogON', MANIFEST, {}),
    ('gap=1cm', MANIFEST, {'gap': 0.01}),
    ('strategy=mec', MANIFEST, {'strategy': 'mec'}),
    ('mec+gap1cm+cogOFF', MANIFEST, {'strategy': 'mec', 'gap': 0.01, 'enableCoGBalance': False}),
    ('stress cluster', STRESS, {}),
    ('stress mec', STRESS, {'strategy': 'mec'}),
    ('stress gap1cm', STRESS, {'gap': 0.01}),
]

def run(manifest, kwargs, use_plan):
    packer = IndustrialSmartContainerPacker(CONTAINER, None, usePlan=use_plan, **kwargs)
    r = packer.pack(copy.deepcopy(manifest))
    return r

print('=' * 78)
all_safe = True
for name, manifest, kwargs in CASES:
    r_off = run(manifest, kwargs, use_plan=False)
    r_on = run(manifest, kwargs, use_plan=True)
    dp = r_on['totalCount'] - r_off['totalCount']
    du = round(r_on['utilization'] - r_off['utilization'], 2)
    f_off = r_off['flatness']['maxStepMm'] if isinstance(r_off['flatness'], dict) else r_off['flatness']
    f_on = r_on['flatness']['maxStepMm'] if isinstance(r_on['flatness'], dict) else r_on['flatness']
    safe_off = r_off['audit']['floatingCount'] == 0 and r_off['totalCollisions'] == 0
    safe_on = r_on['audit']['floatingCount'] == 0 and r_on['totalCollisions'] == 0
    all_safe = all_safe and safe_on
    print(f"--- {name} ---")
    print(f"  planOFF: placed={r_off['totalCount']} unplaced={r_off['totalUnplacedCount']} "
          f"util={r_off['utilization']}% flat={f_off}mm safe={safe_off}")
    print(f"  planON : placed={r_on['totalCount']} unplaced={r_on['totalUnplacedCount']} "
          f"util={r_on['utilization']}% flat={f_on}mm safe={safe_on} "
          f"Δplaced={dp:+d} Δutil={du:+.2f}pt segs={len(r_on['plan']['segments'])}")
print('=' * 78)
print(f"[安全] planON 全部用例 floating=0 且 collisions=0: {all_safe}")
