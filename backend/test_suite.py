"""
3D-AICIVS Automated Test Suite (Python 3 Regression & Collision Audit)
v1.2: 新增模块 1/4/5/6 约束专项测试
v1.3: 新增层优先放置顺序测试 + XYZ 多轴软审计评估器专项测试
"""

import sys
import os

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Ensure backend folder is in sys.path
sys.path.insert(0, os.path.dirname(__file__))
from industrial_packer import IndustrialSmartContainerPacker

def run_regression():
    """回归测试：原 40HQ manifest，断言 0 碰撞 + 新约束审计通过"""
    print("\n" + "=" * 65)
    print("🧪 [回归] 40HQ 原始清单")
    print("=" * 65)

    container_spec = {
        'code': '40HQ',
        'usable': {'L': 12.032, 'W': 2.352, 'H': 2.698},
        'maxPayloadTons': 26.5
    }

    PALETTE = [
        0x3b82f6, 0x10b981, 0xf59e0b, 0xef4444, 0x8b5cf6,
        0x06b6d4, 0xec4899, 0x6366f1, 0x14b8a6, 0xf97316,
        0x84cc16, 0xa855f7, 0x0ea5e9, 0xeab308
    ]

    manifest = [
        {'sku': 'SKU-01', 'name': 'WIFI蓝牙 / WIFI线 / WIFI贴', 'w': 0.50, 'd': 0.50, 'h': 0.50, 'weight': 5.0, 'quantity': 1, 'requirement': '放柜子最里面', 'color': PALETTE[0]},
        {'sku': 'SKU-02', 'name': '21.5寸 显示器 BG (DA)', 'w': 0.553, 'd': 0.08, 'h': 0.355, 'weight': 8.4, 'quantity': 500, 'requirement': '封柜门', 'color': PALETTE[1]},
        {'sku': 'SKU-03', 'name': '34寸显示器 MX340 (DA)', 'w': 0.978, 'd': 0.188, 'h': 0.488, 'weight': 4.61, 'quantity': 90, 'requirement': '封柜门', 'color': PALETTE[2]},
        {'sku': 'SKU-04', 'name': '27寸显示器 2886A (DA)', 'w': 0.68, 'd': 0.122, 'h': 0.44, 'weight': 6.7, 'quantity': 100, 'requirement': '封柜门', 'color': PALETTE[3]},
        {'sku': 'SKU-05', 'name': '32寸智能显示器 (DA)', 'w': 0.833, 'd': 0.53, 'h': 0.23, 'weight': 20.8, 'quantity': 100, 'requirement': '放中间', 'color': PALETTE[4]},
        {'sku': 'SKU-06', 'name': '15.6寸便携显示器 (14/箱)', 'w': 0.575, 'd': 0.46, 'h': 0.465, 'weight': 4.0, 'quantity': 95, 'requirement': '放中间', 'color': PALETTE[5]},
        {'sku': 'SKU-07', 'name': '15.6寸 双屏便携屏', 'w': 0.431, 'd': 0.422, 'h': 0.281, 'weight': 4.0, 'quantity': 125, 'requirement': '放中间', 'color': PALETTE[6]},
        {'sku': 'SKU-08', 'name': '21.5寸一体机整机 带键盘鼠标', 'w': 0.56, 'd': 0.145, 'h': 0.41, 'weight': 12.65, 'quantity': 53, 'requirement': '放中间', 'color': PALETTE[7]},
        {'sku': 'SKU-09', 'name': '19寸一体机整机', 'w': 0.495, 'd': 0.145, 'h': 0.41, 'weight': 10.5, 'quantity': 24, 'requirement': '放中间', 'color': PALETTE[8]},
        {'sku': 'SKU-10', 'name': '19寸液晶屏 / 19寸液晶屏玻璃', 'w': 0.49, 'd': 0.28, 'h': 0.35, 'weight': 15.5, 'quantity': 22, 'requirement': '放中间', 'color': PALETTE[9]},
        {'sku': 'SKU-11', 'name': '电源线', 'w': 0.48, 'd': 0.31, 'h': 0.34, 'weight': 25.5, 'quantity': 10, 'requirement': '放中间', 'color': PALETTE[10]},
        {'sku': 'SKU-12', 'name': '电源线 (小箱)', 'w': 0.18, 'd': 0.18, 'h': 0.34, 'weight': 5.5, 'quantity': 1, 'requirement': '放中间', 'color': PALETTE[11]},
        {'sku': 'SKU-13', 'name': '电源', 'w': 0.43, 'd': 0.41, 'h': 0.19, 'weight': 15.5, 'quantity': 50, 'requirement': '放中间', 'color': PALETTE[12]},
        {'sku': 'SKU-14', 'name': '19寸 显示器 BG (DA)', 'w': 0.488, 'd': 0.08, 'h': 0.336, 'weight': 2.15, 'quantity': 674, 'requirement': '封柜门; 可以减少点', 'color': PALETTE[13]}
    ]

    packer = IndustrialSmartContainerPacker(container_spec)
    result = packer.pack(manifest)

    print(f"📦 Total Placed Boxes: {result['totalPlaced']}")
    print(f"💥 Total Collisions: {result['totalCollisions']}")
    print(f"📊 Container Volume Utilization: {result['utilization']}%")
    print(f"⚖️ Total Cargo Weight: {result['totalMassKg']} kg (Max: {result['maxPayloadKg']} kg)")
    print(f"🎯 CoG: X={result['cog']['x']}m, Y={result['cog']['y']}m, Z={result['cog']['z']}m")
    print(f"⚖️ CoG Offsets: Lateral={result['cog']['latOffsetPercent']}%, Longitudinal={result['cog']['longOffsetPercent']}%")
    print(f"🚧 Constraints: {result['constraints']}")
    print(f"🪜 Flatness: {result['flatness']}")
    print(f"⚡ Elapsed Time: {result['elapsedMs']} ms")

    assert result['totalCollisions'] == 0, f"Collision check failed: {result['totalCollisions']} collisions found!"
    assert result['totalPlaced'] > 0, "No boxes were placed!"
    assert result['constraints']['doorZoneViolations'] == 0, "Door zone violations found!"
    print("✅ REGRESSION PASSED (0 collisions, 0 door-zone violations)")


def test_pressure():
    """模块1 承重压强：重箱压 maxStackWeight 受限的轻箱 → 必须被拦截（直接单测约束方法）"""
    print("\n" + "=" * 65)
    print("🧪 [模块1] 承重压强校验")
    print("=" * 65)
    container_spec = {'code': 'T1', 'usable': {'L': 2.0, 'W': 1.0, 'H': 2.0}, 'maxPayloadTons': 5.0}
    packer = IndustrialSmartContainerPacker(container_spec)

    # 构造已放置的轻箱（maxStackWeight=10kg），及其上方候选位置
    bottom_box = {
        'id': 'LIGHT-1', 'sku': 'LIGHT', 'name': '', 'color': 0, 'weight': 2.0,
        'requirement': '', 'isElastic': False,
        'maxStackWeight': 10.0, 'maxPressureKgM2': 0.0, 'bearing': 0.0,
        'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 0.5, 'h': 0.5, 'd': 0.5
    }
    cand = {'x': 0.0, 'y': 0.5, 'z': 0.0, 'w': 0.5, 'h': 0.5, 'd': 0.5}
    supports = packer._direct_supports(cand, [bottom_box])
    assert len(supports) == 1, "支撑箱查找失败"

    # 重箱 100kg 压在 maxStackWeight=10 的轻箱上 → 必须拦截
    heavy_sku = {'sku': 'HEAVY', 'weight': 100.0, 'w': 0.5, 'd': 0.5, 'h': 0.5, 'isElastic': False}
    assert not packer._check_pressure(heavy_sku, supports, cand), "重箱未被承重校验拦截!"
    print("  ✅ 100kg 重箱压在 10kg 限重轻箱上 → 已拦截")

    # 轻箱 2kg 压上去 → 允许
    light2_sku = {'sku': 'L2', 'weight': 2.0, 'w': 0.5, 'd': 0.5, 'h': 0.5, 'isElastic': False}
    assert packer._check_pressure(light2_sku, supports, cand), "合规轻箱被误拦截!"
    print("  ✅ 2kg 轻箱压 10kg 限重轻箱上 → 放行")

    # 压强模式：maxPressureKgM2=40，接触面积 0.25m² → 承载上限 10kg
    bottom_p = {**bottom_box, 'maxStackWeight': 0.0, 'maxPressureKgM2': 40.0, 'bearing': 0.0}
    supports_p = packer._direct_supports(cand, [bottom_p])
    heavy_sku2 = {'sku': 'H2', 'weight': 20.0, 'w': 0.5, 'd': 0.5, 'h': 0.5, 'isElastic': False}
    assert not packer._check_pressure(heavy_sku2, supports_p, cand), "压强模式未生效!"
    print("  ✅ 压强模式：20kg 箱（>40kg/m²×0.25m²=10kg 上限）→ 已拦截")

    # pack 级弱断言：任何 HEAVY 都不应位于 LIGHT 之上
    manifest = [
        {'sku': 'LIGHT', 'w': 0.5, 'd': 0.5, 'h': 0.5, 'weight': 2.0, 'quantity': 4, 'requirement': '', 'maxStackWeight': 10.0},
        {'sku': 'HEAVY', 'w': 0.5, 'd': 0.5, 'h': 0.5, 'weight': 100.0, 'quantity': 4, 'requirement': ''}
    ]
    result = packer.pack(manifest)
    for b in result['placedBoxes']:
        if b['sku'] == 'HEAVY':
            sp = packer._direct_supports({'x': b['x'], 'y': b['y'], 'z': b['z'], 'w': b['w'], 'h': b['h'], 'd': b['d']}, result['placedBoxes'])
            for s in sp:
                assert s['sku'] != 'LIGHT', "HEAVY 压在了 LIGHT 上，承重校验失效!"
    print("  ✅ pack 级：HEAVY 均未压在 LIGHT 之上")
    print("✅ PRESSURE PASSED")


def test_door_zone():
    """模块6 门区警戒：非弹性非封柜门 SKU 不得进入最后 1.2m"""
    print("\n" + "=" * 65)
    print("🧪 [模块6] 门端 1.2m 警戒区")
    print("=" * 65)
    # L=3.0 → door_zone_x = 1.8；普通 SKU 数量极大，必然想挤进门区
    container_spec = {'code': 'T2', 'usable': {'L': 3.0, 'W': 1.0, 'H': 1.0}, 'maxPayloadTons': 5.0}
    packer = IndustrialSmartContainerPacker(container_spec)
    manifest = [
        {'sku': 'NORMAL', 'w': 0.4, 'd': 0.4, 'h': 0.4, 'weight': 5.0, 'quantity': 40, 'requirement': '放中间'}
    ]
    result = packer.pack(manifest)

    print(f"doorZoneLocked={result['constraints']['doorZoneLocked']}, violations={result['constraints']['doorZoneViolations']}, packedLength={result['packedLength']}")
    assert result['constraints']['doorZoneLocked'] > 0, "门区拦截未生效!"
    assert result['constraints']['doorZoneViolations'] == 0, "门区存在违规箱!"
    # 验证所有箱子都在门区外
    for b in result['placedBoxes']:
        assert b['x'] + b['w'] <= packer.door_zone_x + 0.0015, f"箱 {b['id']} 侵入门区!"
    print(f"✅ DOOR ZONE PASSED (packed until x={result['packedLength']}m, door zone starts at {packer.door_zone_x}m)")


def test_support():
    """模块5 阶梯防倾：悬挑箱（支撑覆盖率不足 / 支撑质心偏移）必须被拦截"""
    print("\n" + "=" * 65)
    print("🧪 [模块5] 阶梯防倾（支撑校验）")
    print("=" * 65)
    container_spec = {'code': 'T3', 'usable': {'L': 2.0, 'W': 1.0, 'H': 2.0}, 'maxPayloadTons': 5.0}
    packer = IndustrialSmartContainerPacker(container_spec)

    # 单测 _check_support：底层 0.4x0.4 顶面，上层 0.8x0.4 横跨 → 支撑质心偏移
    bottom = {'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 0.4, 'h': 0.5, 'd': 0.4}
    overhang = {'x': 0.0, 'y': 0.5, 'z': 0.0, 'w': 0.4, 'h': 0.5, 'd': 0.8}  # 底面积 0.32，仅 0.16 接触
    supports = packer._direct_supports(overhang, [bottom])
    allowed = packer._check_support(overhang, supports)
    print(f"overhang cand: support_ratio_check -> allowed={allowed}")
    assert not allowed, "悬挑箱未被防倾拦截!"

    # 地面放置必须放行
    on_floor = {'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 0.4, 'h': 0.5, 'd': 0.8}
    assert packer._check_support(on_floor, []), "地面放置被误拦截!"
    # 完整贴合（100% 支撑）必须放行
    full = {'x': 0.0, 'y': 0.5, 'z': 0.0, 'w': 0.4, 'h': 0.5, 'd': 0.4}
    assert packer._check_support(full, [bottom]), "完整贴合支撑被误拦截!"
    print("✅ SUPPORT PASSED")


def test_cog_balance():
    """模块4 重心闭环：全部重箱集中一侧时，双向铺列应使横向偏载达标"""
    print("\n" + "=" * 65)
    print("🧪 [模块4] 重心闭环（双向铺列）")
    print("=" * 65)
    # 只装一个重 SKU，若不平衡则必然偏载；双向铺列应让重心回中
    container_spec = {'code': 'T4', 'usable': {'L': 6.0, 'W': 3.0, 'H': 2.0}, 'maxPayloadTons': 10.0}
    packer = IndustrialSmartContainerPacker(container_spec)
    manifest = [
        {'sku': 'W', 'w': 0.6, 'd': 0.5, 'h': 0.4, 'weight': 30.0, 'quantity': 200, 'requirement': '放中间'}
    ]
    result = packer.pack(manifest)

    print(f"latOffset={result['cog']['latOffsetPercent']}%, isLatBalanced={result['cog']['isLatBalanced']}, cogZ={result['cog']['z']}m, W={packer.W}m")
    print(f"cogSkippedCols={result['constraints']['cogSkippedCols']}, placed={result['totalPlaced']}")
    assert result['cog']['isLatBalanced'], f"横向偏载 {result['cog']['latOffsetPercent']}% 超过 5%!"
    # 重心预检跳过列数可能为 0（双向铺列已平衡），也可能 >0（硬拦截），两者都算闭环生效
    print("✅ COG PASSED")


def test_layer_first():
    """v1.3 层优先：整片结构先铺满同层 z 向再升层（而非先堆满一列）"""
    print("\n" + "=" * 65)
    print("🧪 [v1.3] 层优先放置顺序")
    print("=" * 65)
    container_spec = {'code': 'T5', 'usable': {'L': 4.0, 'W': 2.0, 'H': 2.0}, 'maxPayloadTons': 5.0}
    packer = IndustrialSmartContainerPacker(container_spec)
    manifest = [
        # allowDoorZone=True：与 40HQ 回归中"封柜门"SKU 的豁免行为一致，确保整片结构不被门区拦截回退
        {'sku': 'BOX', 'w': 0.5, 'd': 0.5, 'h': 0.5, 'weight': 5.0, 'quantity': 200, 'requirement': '', 'allowDoorZone': True}
    ]
    result = packer.pack(manifest)

    # 第一个墙切片为整片结构：前 4 箱应构成第 0 层（y=0，z=0/0.5/1.0/1.5 铺满）
    first_layer = result['placedBoxes'][:4]
    ys = {round(b['y'], 3) for b in first_layer}
    zs = sorted(round(b['z'], 3) for b in first_layer)
    print(f"first layer ys={ys}, zs={zs}, flatness={result['flatness']}")
    assert ys == {0.0}, f"层优先失效：第一层 y 坐标 {ys}（栋优先应为 y=0/0.5/1.0/1.5）"
    assert zs == [0.0, 0.5, 1.0, 1.5], f"层优先失效：第一层 z 坐标 {zs}"
    # 第 5-8 箱应构成第 1 层（y=0.5）
    second_layer = result['placedBoxes'][4:8]
    assert {round(b['y'], 3) for b in second_layer} == {0.5}, "第二层 y 坐标异常"
    # 评估器：无悬浮、0 碰撞
    assert result['audit']['floatingCount'] == 0, "评估器检出悬浮箱!"
    assert result['totalCollisions'] == 0, "存在碰撞!"
    print(f"✅ LAYER-FIRST PASSED (placed={result['totalPlaced']}, first 2 layers confirmed)")
    print(f"   audit: floating={result['audit']['floatingCount']}, hollow={result['audit']['hollowVolumeM3']}m³")


def test_xyz_audit():
    """v1.3 XYZ 多轴保底评估器：构造回字形封闭中空 + 悬浮箱，验证三项检测"""
    print("\n" + "=" * 65)
    print("🧪 [v1.3] XYZ 多轴保底评估器（软审计）")
    print("=" * 65)
    from evaluator import XYZFallbackEvaluator
    ev = XYZFallbackEvaluator(2.0, 1.5, 1.5)

    # 构造：底层+顶盖铺满，第二层回字形 → 内部 x∈[0.5,1.5) z∈[0.5,1.0) y∈[0.5,1.0) 完全封闭中空
    boxes = []
    for i in range(4):
        for j in range(3):
            boxes.append({'x': i * 0.5, 'y': 0.0, 'z': j * 0.5, 'w': 0.5, 'h': 0.5, 'd': 0.5, 'sku': 'BASE'})
    for i in range(4):
        boxes.append({'x': i * 0.5, 'y': 0.5, 'z': 0.0, 'w': 0.5, 'h': 0.5, 'd': 0.5, 'sku': 'WALL'})
        boxes.append({'x': i * 0.5, 'y': 0.5, 'z': 1.0, 'w': 0.5, 'h': 0.5, 'd': 0.5, 'sku': 'WALL'})
    boxes.append({'x': 0.0, 'y': 0.5, 'z': 0.5, 'w': 0.5, 'h': 0.5, 'd': 0.5, 'sku': 'WALL'})
    boxes.append({'x': 1.5, 'y': 0.5, 'z': 0.5, 'w': 0.5, 'h': 0.5, 'd': 0.5, 'sku': 'WALL'})
    for i in range(4):
        for j in range(3):
            boxes.append({'x': i * 0.5, 'y': 1.0, 'z': j * 0.5, 'w': 0.5, 'h': 0.5, 'd': 0.5, 'sku': 'CAP'})

    audit = ev.evaluate(boxes, [], 0.0, 2.0)
    # 中空体积期望 1.0×0.5×0.5 = 0.25 m³（20×10×10 体素 @ 5cm）
    # 顶盖中间 2 箱（x∈[0.5,1.5), z∈[0.5,1.0)）下方是中空 → 物理悬浮，评估器应准确检出
    print(f"  hollow={audit['hollowVolumeM3']}m³ (expect ~0.25), floating={audit['floatingCount']} (expect 2)")
    assert audit['floatingCount'] == 2, f"悬浮检测异常: {audit['floatingCount']}"
    assert abs(audit['hollowVolumeM3'] - 0.25) < 0.05, f"中空体积偏差过大: {audit['hollowVolumeM3']}"

    # 悬浮：单箱悬空
    audit2 = ev.evaluate([{'x': 0.0, 'y': 0.5, 'z': 0.0, 'w': 0.5, 'h': 0.5, 'd': 0.5, 'sku': 'FLOAT'}], [], 0.0, 2.0)
    assert audit2['floatingCount'] == 1, "悬浮检测失效!"
    print("  floatingCount=1 ✅")

    # 漏放：剩余小箱 0.3³ 能放入 0.25m³ 中空 → missed > 0
    audit3 = ev.evaluate(boxes, [{'sku': 'SMALL', 'w': 0.3, 'd': 0.3, 'h': 0.3, 'remQty': 5}], 0.0, 2.0)
    print(f"  missed={audit3['missedVolumeM3']}m³, regions={len(audit3['missedRegions'])}")
    assert audit3['missedVolumeM3'] > 0.1, "漏放检测失效!"
    print("✅ XYZ AUDIT PASSED")


def test_max_stack_layers():
    """v1.4 最大堆叠层数（前端 maxStackLayers 字段）：同 SKU 投影列内限层"""
    print("\n" + "=" * 65)
    print("🧪 [v1.4] 最大堆叠层数 maxStackLayers")
    print("=" * 65)
    container = {'L': 12.032, 'W': 2.352, 'H': 2.698}
    manifest = [
        {'sku': 'SKU-05', 'w': 0.833, 'd': 0.53, 'h': 0.23, 'weight': 20.8,
         'quantity': 100, 'requirement': '放中间', 'maxStackLayers': 2, 'isElastic': False},
    ]
    p = IndustrialSmartContainerPacker(container, {})
    r = p.pack(manifest)
    from collections import Counter
    cols = Counter()
    for b in r['placedBoxes']:
        cols[(round(b['x'], 3), round(b['z'], 3))] += 1
    max_col = max(cols.values())
    print(f"  placed={r['totalCount']}, 最大列内同SKU数={max_col} (期望<=2)")
    assert max_col <= 2, f"限层失效: 单列堆了 {max_col} 层!"
    print("✅ MAX STACK LAYERS PASSED")


def test_max_bearing():
    """v1.4 单箱承重上限（前端 maxBearingKg → 后端 maxStackWeight）：重箱不得压上限重箱"""
    print("\n" + "=" * 65)
    print("🧪 [v1.4] 单箱承重上限 maxBearingKg")
    print("=" * 65)
    container = {'L': 12.032, 'W': 2.352, 'H': 2.698}
    manifest = [
        {'sku': 'BASE', 'w': 1.0, 'd': 1.0, 'h': 0.3, 'weight': 5.0, 'quantity': 10,
         'requirement': '放中间', 'maxBearingKg': 10, 'isElastic': False},
        {'sku': 'HEAVY', 'w': 0.5, 'd': 0.5, 'h': 0.5, 'weight': 20.0, 'quantity': 10,
         'requirement': '放中间', 'isElastic': False},
    ]
    p = IndustrialSmartContainerPacker(container, {})
    r = p.pack(manifest)
    base_boxes = [b for b in r['placedBoxes'] if b['sku'] == 'BASE']
    heavy_on_base = 0
    for hb in [b for b in r['placedBoxes'] if b['sku'] == 'HEAVY']:
        for bb in base_boxes:
            ox = min(hb['x'] + hb['w'], bb['x'] + bb['w']) - max(hb['x'], bb['x'])
            oz = min(hb['z'] + hb['d'], bb['z'] + bb['d']) - max(hb['z'], bb['z'])
            if ox > 1e-6 and oz > 1e-6 and abs(hb['y'] - (bb['y'] + bb['h'])) < 0.01:
                heavy_on_base += 1
    print(f"  BASE placed={len(base_boxes)}, HEAVY placed={sum(1 for b in r['placedBoxes'] if b['sku'] == 'HEAVY')}, 压BASE上的HEAVY数={heavy_on_base} (期望0)")
    assert heavy_on_base == 0, "承重上限失效: 20kg 箱压在了限重 10kg 箱上!"
    print("✅ MAX BEARING PASSED")


def run_tests():
    print("=================================================================")
    print("🚀 Running 3D-AICIVS Python 3 Industrial Kernel Test Suite (v1.4)")
    print("=================================================================")
    run_regression()
    test_pressure()
    test_door_zone()
    test_support()
    test_cog_balance()
    test_layer_first()
    test_xyz_audit()
    test_max_stack_layers()
    test_max_bearing()
    print("\n" + "=" * 65)
    print("✅✅ ALL TESTS PASSED! Kernel + 6 constraints + layer-first + XYZ audit validated.")
    print("=" * 65)

if __name__ == '__main__':
    run_tests()
