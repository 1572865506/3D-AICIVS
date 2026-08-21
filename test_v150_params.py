# -*- coding: utf-8 -*-
"""v1.5.0 参数贯通离线回归：gap / strategy(mec) / enableCoGBalance 四组对照"""
import sys, os, io, json
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

CASES = [
    ('baseline cluster/gap0/cogON', {}),
    ('gap=1cm', {'gap': 0.01}),
    ('strategy=mec', {'strategy': 'mec'}),
    ('cog=OFF', {'enableCoGBalance': False}),
    ('mec+gap1cm+cogOFF', {'strategy': 'mec', 'gap': 0.01, 'enableCoGBalance': False}),
]

def signature(boxes):
    """布局指纹：首个与中位箱坐标（用于判断布局是否真的变化）"""
    if not boxes:
        return 'EMPTY'
    pts = [(round(b['x'], 3), round(b['y'], 3), round(b['z'], 3)) for b in boxes[:200]]
    mid = pts[len(pts) // 2]
    return f"first={pts[0]} mid={mid}"

results = {}
for name, kwargs in CASES:
    import copy
    manifest = copy.deepcopy(MANIFEST)
    packer = IndustrialSmartContainerPacker(CONTAINER, None, **kwargs)
    r = packer.pack(manifest)
    results[name] = r
    print(f"--- {name} ---")
    print(f"  placed={r['totalCount']} unplaced={r['totalUnplacedCount']} util={r['utilization']}% "
          f"collisions={r['totalCollisions']} mass={r['totalMassKg']}kg elapsed={r['elapsedMs']}ms")
    print(f"  audit: floating={r['audit']['floatingCount']} hollow={r['audit']['hollowVolumeM3']}m3 "
          f"missed={r['audit']['missedVolumeM3']}m3")
    print(f"  cog.lat={r['cog']['latOffsetPercent']}% flatness.maxStep={r['flatness']['maxStepMm']}mm "
          f"cogSkippedCols={r['constraints']['cogSkippedCols']}")
    print(f"  layout: {signature(r['placedBoxes'])}")

# 差异断言
base = results['baseline cluster/gap0/cogON']
g = results['gap=1cm']
m = results['strategy=mec']
c = results['cog=OFF']
print("\n=== 断言 ===")
print(f"[gap] 布局变化: {signature(base['placedBoxes']) != signature(g['placedBoxes'])} "
      f"(placed {base['totalCount']} -> {g['totalCount']}, util {base['utilization']}% -> {g['utilization']}%)")
print(f"[mec] 布局变化: {signature(base['placedBoxes']) != signature(m['placedBoxes'])} "
      f"(placed {base['totalCount']} -> {m['totalCount']}, util {base['utilization']}% -> {m['utilization']}%)")
print(f"[cog off] 布局变化: {signature(base['placedBoxes']) != signature(c['placedBoxes'])} "
      f"(cogSkippedCols {base['constraints']['cogSkippedCols']} -> {c['constraints']['cogSkippedCols']})")
ok = all(r['audit']['floatingCount'] == 0 and r['totalCollisions'] == 0 for r in results.values())
print(f"[安全] 全部用例 floating=0 且 collisions=0: {ok}")

# === 配平开关专项：构造横向偏载清单（宽幅重货集中左侧 z∈[0,1.7]，随后轻货从左侧续铺会被拦截）===
print("\n=== enableCoGBalance 专项（偏载触发清单） ===")
COG_MANIFEST = [
    {'sku': 'HEAVY-W', 'w': 0.6, 'd': 1.7, 'h': 0.6, 'weight': 800.0, 'quantity': 24, 'requirement': '放柜子最里面'},
    {'sku': 'LIGHT-N', 'w': 0.6, 'd': 0.5, 'h': 0.6, 'weight': 5.0, 'quantity': 300, 'requirement': '放中间'},
]
for label, cog in (('cog=ON', True), ('cog=OFF', False)):
    import copy
    manifest = copy.deepcopy(COG_MANIFEST)
    packer = IndustrialSmartContainerPacker(CONTAINER, None, enableCoGBalance=cog)
    r = packer.pack(manifest)
    zs = [round(b['z'], 3) for b in r['placedBoxes'] if b['sku'] == 'LIGHT-N']
    print(f"--- {label} ---")
    print(f"  placed={r['totalCount']} util={r['utilization']}% lat={r['cog']['latOffsetPercent']}% "
          f"cogSkippedCols={r['constraints']['cogSkippedCols']} collisions={r['totalCollisions']} "
          f"floating={r['audit']['floatingCount']}")
    print(f"  LIGHT-N z 分布: min={min(zs) if zs else '-'} max={max(zs) if zs else '-'}")

