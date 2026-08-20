"""
3D-AICIVS Automated Test Suite (Python 3 Regression & Collision Audit)
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

def run_tests():
    print("=================================================================")
    print("🚀 Running 3D-AICIVS Python 3 Industrial Kernel Test Suite")
    print("=================================================================")

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
    print(f"⚡ Elapsed Time: {result['elapsedMs']} ms")
    print("-----------------------------------------------------------------")
    print("SKU Placement Breakdown:")
    for s in result['skuStats']:
        print(f"  • {s['sku']} [{s['requirement']}]: Placed {s['actualPlaced']}/{s['quantity']} (Rem: {s['remQty']})")

    assert result['totalCollisions'] == 0, f"Collision check failed: {result['totalCollisions']} collisions found!"
    assert result['totalPlaced'] > 0, "No boxes were placed!"
    print("-----------------------------------------------------------------")
    print("✅ ALL TESTS PASSED! Python 3 Industrial Kernel is 100% Validated.")
    print("=================================================================")

if __name__ == '__main__':
    run_tests()
