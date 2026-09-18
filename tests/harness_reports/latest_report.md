# 🧪 测试报告 | 2026-09-18T15:33:05
**总计 56 用例 | ✅ 50 通过 | ❌ 1 失败 | ⚠️ 5 警告 | ⏱️ 665s**

## 健康概览
| 指标 | 值 |
|:---|:---|
| 平均利用率 | **38.6%** |
| 平均刚性完成率 | **90.7%** |
| 总碰撞 | 0 |
| 总约束违规 | 0 |

## 故障聚类摘要
### CLUSTER-1: PRIORITY_INVERSION (3 用例)
- **典型用例**: FLOOR-SPACE-COMPETITION, EXTREME-PAYLOAD-BEARING, RANDOM-STRESS-CASE-01
- **共性**: 平均利用率 33.1%, 平均刚性 81.6%
- **归因**: 刚性未满 99% 时弹性件已被放入，存在优先级倒挂
- **代码位置**: `composite_strip.py 排序逻辑`
- **建议角色**: 角色 A

### CLUSTER-2: RIGID_STARVATION (2 用例)
- **典型用例**: 14-SKU-1845, RANDOM-STRESS-CASE-05
- **共性**: 平均利用率 53.2%, 平均刚性 79.5%
- **归因**: 刚性 SKU 饥饿/弃装，弹性件可能抢占了截面配额
- **代码位置**: `composite_strip.py 刚性优先分配`
- **建议角色**: 角色 A

### CLUSTER-3: LOW_UTILIZATION (1 用例)
- **典型用例**: SINGLE-SKU-MASS
- **共性**: 平均利用率 0.0%, 平均刚性 0.0%
- **归因**: 空间利用率低于 60%，需优化墙体效率和间隙填充
- **代码位置**: `unified_solver.py 墙体构建 + gap_filler.py`
- **建议角色**: 角色 A

## 历史趋势
```
趋势 (最近 6 次运行):
利用率: 89.1 → 87.9 → 40.7 → 47.8 → 47.8 → 38.6 [↓ -50.5]
通过率: 100% → 100% → 88% → 50% → 100% → 89% [↓ -11%]
```

## 用例明细表
<details><summary>点击展开全部 56 个用例</summary>

| Case ID | 利用率 | 刚性% | 违规 | 碰撞 | 状态 |
|:---|---:|---:|---:|---:|:---|
| SINGLE-SKU-MASS | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| SINGLE-LARGE-BOX | 91.5% | 85.7% | 0 | 0 | ✅ PASS |
| ALL-ELASTIC-SKUS | 89.5% | 0.0% | 0 | 0 | ✅ PASS |
| DOOR-DENSE-SKUS | 69.8% | 100.0% | 0 | 0 | ✅ PASS |
| MIXED-HETEROGENEOUS | 57.8% | 88.4% | 0 | 0 | ✅ PASS |
| 20GP-STANDARD | 69.1% | 100.0% | 0 | 0 | ✅ PASS |
| 45HQ-EXTENDED | 79.0% | 86.5% | 0 | 0 | ✅ PASS |
| STACK-BEARING-CONSTRAINTS | 43.6% | 100.0% | 0 | 0 | ✅ PASS |
| ORIENTATION-TOPSTACK-CONSTRAINTS | 40.1% | 100.0% | 0 | 0 | ✅ PASS |
| TALL-SLENDER-TIPPING | 36.9% | 100.0% | 0 | 0 | ✅ PASS |
| OVERWEIGHT-PAYLOAD | 9.4% | 32.0% | 0 | 0 | ✅ PASS |
| MULTI-ZONE-CONSTRAINTS | 52.1% | 100.0% | 0 | 0 | ✅ PASS |
| EXTREME-ASPECT-RATIO | 34.9% | 100.0% | 0 | 0 | ✅ PASS |
| ALL-CONSTRAINTS-COMBINED | 51.9% | 100.0% | 0 | 0 | ✅ PASS |
| STRICT-SINGLE-LAYER-FLOOR | 40.5% | 100.0% | 0 | 0 | ✅ PASS |
| TWO-LAYER-FLOOR-CEILING | 32.0% | 100.0% | 0 | 0 | ✅ PASS |
| DENSE-HEAVY-FLOOR-PAD | 20.2% | 100.0% | 0 | 0 | ✅ PASS |
| LONG-BEAM-FLOOR | 24.4% | 100.0% | 0 | 0 | ✅ PASS |
| 20GP-SINGLE-LAYER | 36.2% | 100.0% | 0 | 0 | ✅ PASS |
| THREE-TIER-BEARING-CHAIN | 28.1% | 100.0% | 0 | 0 | ✅ PASS |
| LOW-BEARING-FRAGILE-MID | 24.3% | 100.0% | 0 | 0 | ✅ PASS |
| HETEROGENEOUS-BEARING-LIMITS | 23.9% | 100.0% | 0 | 0 | ✅ PASS |
| ZERO-BEARING-ELASTIC-REFILL | 17.9% | 100.0% | 0 | 0 | ✅ PASS |
| ASYMMETRIC-BEARING-STRIPS | 22.1% | 100.0% | 0 | 0 | ✅ PASS |
| BROAD-NO-TOP-STACK-PANELS | 30.0% | 100.0% | 0 | 0 | ✅ PASS |
| CHECKERBOARD-NOTOP-ISOLATION | 23.9% | 100.0% | 0 | 0 | ✅ PASS |
| MULTI-SKU-NO-TOP-STACK | 21.0% | 93.5% | 0 | 0 | ✅ PASS |
| NOTOP-LARGE-WITH-ELASTIC-BURST | 34.5% | 100.0% | 0 | 0 | ✅ PASS |
| FLOOR-AND-NOTOP-COMBINED | 30.1% | 100.0% | 0 | 0 | ✅ PASS |
| 20GP-NOTOP-SPACE | 26.1% | 100.0% | 0 | 0 | ✅ PASS |
| STRICT-UPRIGHT-MONOLITHIC | 39.1% | 100.0% | 0 | 0 | ✅ PASS |
| FLAT-ONLY-SLABS | 29.2% | 100.0% | 0 | 0 | ✅ PASS |
| ULTRA-THIN-UPRIGHT-SCREENS | 25.3% | 100.0% | 0 | 0 | ✅ PASS |
| MAX-FLAT-LAYERS-CONSTRAINT | 25.1% | 100.0% | 0 | 0 | ✅ PASS |
| ORIENTATION-HEIGHT-CUTOFF | 28.4% | 100.0% | 0 | 0 | ✅ PASS |
| 20GP-LOCKED-ORIENTATION | 38.5% | 100.0% | 0 | 0 | ✅ PASS |
| STRICT-TWO-STACK-LAYERS | 30.5% | 100.0% | 0 | 0 | ✅ PASS |
| STRICT-THREE-STACK-LAYERS | 23.1% | 100.0% | 0 | 0 | ✅ PASS |
| STEPPED-STACK-LAYERS-CASCADE | 23.4% | 100.0% | 0 | 0 | ✅ PASS |
| INTERLEAVED-STACK-LAYERS | 19.6% | 100.0% | 0 | 0 | ✅ PASS |
| STEPPED-HEIGHT-TIPPING-SAFETY | 25.6% | 100.0% | 0 | 0 | ✅ PASS |
| 20GP-STACK-LAYERS | 27.0% | 100.0% | 0 | 0 | ✅ PASS |
| RIGID-DOMINANT-95PCT | 57.8% | 100.0% | 0 | 0 | ✅ PASS |
| ELASTIC-DOMINANT-90PCT | 44.4% | 100.0% | 0 | 0 | ✅ PASS |
| RIGID-OVERLOAD-150PCT | 86.0% | 74.0% | 0 | 0 | ✅ PASS |
| DOOR-ZONE-SPECIALIZED | 42.3% | 100.0% | 0 | 0 | ✅ PASS |
| TWELVE-SKU-COMPLEX-MOSAIC | 52.1% | 99.8% | 0 | 0 | ✅ PASS |
| 20GP-NEAR-LIMIT | 59.5% | 100.0% | 0 | 0 | ✅ PASS |
| RANDOM-STRESS-CASE-02 | 48.4% | 76.2% | 0 | 0 | ✅ PASS |
| RANDOM-STRESS-CASE-03 | 24.5% | 45.0% | 0 | 0 | ✅ PASS |
| RANDOM-STRESS-CASE-04 | 47.7% | 91.4% | 0 | 0 | ✅ PASS |
| 14-SKU-1845 | 82.3% | 98.7% | 0 | 0 | ⚠️ WARN |
| FLOOR-SPACE-COMPETITION | 27.4% | 69.3% | 0 | 0 | ⚠️ WARN |
| EXTREME-PAYLOAD-BEARING | 24.0% | 86.0% | 0 | 0 | ⚠️ WARN |
| RANDOM-STRESS-CASE-01 | 47.8% | 89.5% | 0 | 0 | ⚠️ WARN |
| RANDOM-STRESS-CASE-05 | 24.0% | 60.3% | 0 | 0 | ⚠️ WARN |

</details>

## 行动建议
### 角色 A
- [PRIORITY_INVERSION] 刚性未满 99% 时弹性件已被放入，存在优先级倒挂 → `composite_strip.py 排序逻辑`
- [RIGID_STARVATION] 刚性 SKU 饥饿/弃装，弹性件可能抢占了截面配额 → `composite_strip.py 刚性优先分配`
- [LOW_UTILIZATION] 空间利用率低于 60%，需优化墙体效率和间隙填充 → `unified_solver.py 墙体构建 + gap_filler.py`
