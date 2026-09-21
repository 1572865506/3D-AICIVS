# 🧪 测试报告 | 2026-09-21T13:00:51
**总计 115 用例 | ✅ 42 通过 | ❌ 51 失败 | ⚠️ 22 警告 | ⏱️ 2252s**

## 健康概览
| 指标 | 值 |
|:---|:---|
| 平均利用率 | **27.7%** |
| 平均刚性完成率 | **39.9%** |
| 总碰撞 | 0 |
| 总约束违规 | 0 |

## 故障聚类摘要
### CLUSTER-1: LOW_UTILIZATION (51 用例)
- **典型用例**: SINGLE-LARGE-BOX, ALL-ELASTIC-SKUS, STACK-BEARING-CONSTRAINTS, TALL-SLENDER-TIPPING (+47)
- **共性**: 平均利用率 0.0%, 平均刚性 0.0%
- **归因**: 空间利用率低于 60%，需优化墙体效率和间隙填充
- **代码位置**: `unified_solver.py 墙体构建 + gap_filler.py`
- **建议角色**: 角色 A

### CLUSTER-2: RIGID_STARVATION (22 用例)
- **典型用例**: ALL-CONSTRAINTS-COMBINED-MUT-02, ALL-CONSTRAINTS-COMBINED-MUT-04, GEN-P1-02-04, GEN-P1-03-02 (+18)
- **共性**: 平均利用率 48.3%, 平均刚性 54.0%
- **归因**: 刚性 SKU 饥饿/弃装，弹性件可能抢占了截面配额
- **代码位置**: `composite_strip.py 刚性优先分配`
- **建议角色**: 角色 A

## 历史趋势
```
趋势 (最近 10 次运行):
利用率: 41.6 → 36.4 → 34.6 → 41.6 → 34.6 → 34.6 → 34.6 → 34.2 → 41.5 → 27.7 [↓ -13.9]
通过率: 48% → 0% → 0% → 0% → 0% → 0% → 0% → 0% → 100% → 37% [↓ -11%]
```

## 用例明细表
<details><summary>点击展开全部 115 个用例</summary>

| Case ID | 利用率 | 刚性% | 违规 | 碰撞 | 状态 |
|:---|---:|---:|---:|---:|:---|
| SINGLE-LARGE-BOX | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| ALL-ELASTIC-SKUS | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| STACK-BEARING-CONSTRAINTS | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| TALL-SLENDER-TIPPING | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| OVERWEIGHT-PAYLOAD | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| EXTREME-ASPECT-RATIO | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| SINGLE-SKU-MASS | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| STRICT-SINGLE-LAYER-FLOOR | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| FLOOR-SPACE-COMPETITION | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| TWO-LAYER-FLOOR-CEILING | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| DENSE-HEAVY-FLOOR-PAD | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| LONG-BEAM-FLOOR | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| 20GP-SINGLE-LAYER | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| THREE-TIER-BEARING-CHAIN | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| LOW-BEARING-FRAGILE-MID | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| HETEROGENEOUS-BEARING-LIMITS | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| ZERO-BEARING-ELASTIC-REFILL | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| EXTREME-PAYLOAD-BEARING | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| ASYMMETRIC-BEARING-STRIPS | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| BROAD-NO-TOP-STACK-PANELS | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| CHECKERBOARD-NOTOP-ISOLATION | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| MULTI-SKU-NO-TOP-STACK | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| NOTOP-LARGE-WITH-ELASTIC-BURST | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| FLOOR-AND-NOTOP-COMBINED | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| 20GP-NOTOP-SPACE | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| STRICT-UPRIGHT-MONOLITHIC | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| FLAT-ONLY-SLABS | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| ULTRA-THIN-UPRIGHT-SCREENS | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| MAX-FLAT-LAYERS-CONSTRAINT | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| ORIENTATION-HEIGHT-CUTOFF | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| 20GP-LOCKED-ORIENTATION | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| STRICT-TWO-STACK-LAYERS | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| STRICT-THREE-STACK-LAYERS | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| STEPPED-STACK-LAYERS-CASCADE | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| INTERLEAVED-STACK-LAYERS | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| STEPPED-HEIGHT-TIPPING-SAFETY | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| 20GP-STACK-LAYERS | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| RIGID-DOMINANT-95PCT | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| ELASTIC-DOMINANT-90PCT | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| RIGID-OVERLOAD-150PCT | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| 20GP-NEAR-LIMIT | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| RANDOM-STRESS-CASE-02 | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| GEN-P1-01-01 | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| GEN-P1-01-03 | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| GEN-P1-02-03 | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| GEN-P1-08-01 | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| GEN-P1-08-02 | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| GEN-P1-11-01 | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| GEN-P1-16-01 | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| GEN-RAND-42-0006 | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| GEN-RAND-42-0007 | 0.0% | 0.0% | 0 | 0 | ❌ FAIL |
| 14-SKU-1845 | 80.7% | 98.5% | 0 | 0 | ✅ PASS |
| DOOR-DENSE-SKUS | 69.8% | 100.0% | 0 | 0 | ✅ PASS |
| MIXED-HETEROGENEOUS | 70.4% | 100.0% | 0 | 0 | ✅ PASS |
| 20GP-STANDARD | 69.1% | 100.0% | 0 | 0 | ✅ PASS |
| 45HQ-EXTENDED | 76.5% | 80.6% | 0 | 0 | ✅ PASS |
| ORIENTATION-TOPSTACK-CONSTRAINTS | 39.5% | 99.5% | 0 | 0 | ✅ PASS |
| MULTI-ZONE-CONSTRAINTS | 52.1% | 100.0% | 0 | 0 | ✅ PASS |
| ALL-CONSTRAINTS-COMBINED | 51.9% | 100.0% | 0 | 0 | ✅ PASS |
| DOOR-ZONE-SPECIALIZED | 42.3% | 100.0% | 0 | 0 | ✅ PASS |
| TWELVE-SKU-COMPLEX-MOSAIC | 54.0% | 100.0% | 0 | 0 | ✅ PASS |
| RANDOM-STRESS-CASE-01 | 47.1% | 88.5% | 0 | 0 | ✅ PASS |
| RANDOM-STRESS-CASE-03 | 30.2% | 55.2% | 0 | 0 | ✅ PASS |
| RANDOM-STRESS-CASE-04 | 46.7% | 85.1% | 0 | 0 | ✅ PASS |
| RANDOM-STRESS-CASE-05 | 34.3% | 65.4% | 0 | 0 | ✅ PASS |
| ALL-CONSTRAINTS-COMBINED-MUT-01 | 64.2% | 96.8% | 0 | 0 | ✅ PASS |
| ALL-CONSTRAINTS-COMBINED-MUT-03 | 69.9% | 89.5% | 0 | 0 | ✅ PASS |
| ALL-CONSTRAINTS-COMBINED-MUT-05 | 56.4% | 97.0% | 0 | 0 | ✅ PASS |
| GEN-P1-01-02 | 18.2% | 96.4% | 0 | 0 | ✅ PASS |
| GEN-P1-02-01 | 27.5% | 96.3% | 0 | 0 | ✅ PASS |
| GEN-P1-02-02 | 38.3% | 88.6% | 0 | 0 | ✅ PASS |
| GEN-P1-03-01 | 48.3% | 68.6% | 0 | 0 | ✅ PASS |
| GEN-P1-03-03 | 81.2% | 81.3% | 0 | 0 | ✅ PASS |
| GEN-P1-03-04 | 69.0% | 79.1% | 0 | 0 | ✅ PASS |
| GEN-P1-04-01 | 28.2% | 48.0% | 0 | 0 | ✅ PASS |
| GEN-P1-04-03 | 30.7% | 79.2% | 0 | 0 | ✅ PASS |
| GEN-P1-05-01 | 49.3% | 100.0% | 0 | 0 | ✅ PASS |
| GEN-P1-05-02 | 60.5% | 100.0% | 0 | 0 | ✅ PASS |
| GEN-P1-05-03 | 49.2% | 97.2% | 0 | 0 | ✅ PASS |
| GEN-P1-07-01 | 3.0% | 0.0% | 0 | 0 | ✅ PASS |
| GEN-P1-07-02 | 5.0% | 0.0% | 0 | 0 | ✅ PASS |
| GEN-P1-08-03 | 72.0% | 98.7% | 0 | 0 | ✅ PASS |
| GEN-P1-09-01 | 77.2% | 66.6% | 0 | 0 | ✅ PASS |
| GEN-P1-09-02 | 82.0% | 53.5% | 0 | 0 | ✅ PASS |
| GEN-P1-11-02 | 20.1% | 91.2% | 0 | 0 | ✅ PASS |
| GEN-P1-12-02 | 69.9% | 75.3% | 0 | 0 | ✅ PASS |
| GEN-P1-14-01 | 57.4% | 81.5% | 0 | 0 | ✅ PASS |
| GEN-P1-14-02 | 46.1% | 91.8% | 0 | 0 | ✅ PASS |
| GEN-P1-15-02 | 68.7% | 74.4% | 0 | 0 | ✅ PASS |
| GEN-RAND-42-0001 | 31.7% | 100.0% | 0 | 0 | ✅ PASS |
| GEN-RAND-42-0002 | 58.3% | 84.2% | 0 | 0 | ✅ PASS |
| GEN-RAND-42-0004 | 66.0% | 89.0% | 0 | 0 | ✅ PASS |
| GEN-RAND-42-0008 | 8.5% | 0.0% | 0 | 0 | ✅ PASS |
| ALL-CONSTRAINTS-COMBINED-MUT-02 | 63.3% | 50.0% | 0 | 0 | ⚠️ WARN |
| ALL-CONSTRAINTS-COMBINED-MUT-04 | 71.3% | 47.9% | 0 | 0 | ⚠️ WARN |
| GEN-P1-02-04 | 32.5% | 74.7% | 0 | 0 | ⚠️ WARN |
| GEN-P1-03-02 | 67.0% | 67.1% | 0 | 0 | ⚠️ WARN |
| GEN-P1-04-02 | 24.4% | 58.7% | 0 | 0 | ⚠️ WARN |
| GEN-P1-06-01 | 20.9% | 31.9% | 0 | 0 | ⚠️ WARN |
| GEN-P1-06-02 | 37.4% | 36.5% | 0 | 0 | ⚠️ WARN |
| GEN-P1-06-03 | 27.2% | 49.1% | 0 | 0 | ⚠️ WARN |
| GEN-P1-09-03 | 61.6% | 67.8% | 0 | 0 | ⚠️ WARN |
| GEN-P1-10-01 | 36.4% | 29.8% | 0 | 0 | ⚠️ WARN |
| GEN-P1-10-02 | 46.6% | 38.5% | 0 | 0 | ⚠️ WARN |
| GEN-P1-12-01 | 72.5% | 84.9% | 0 | 0 | ⚠️ WARN |
| GEN-P1-12-03 | 69.6% | 56.5% | 0 | 0 | ⚠️ WARN |
| GEN-P1-13-01 | 30.3% | 24.8% | 0 | 0 | ⚠️ WARN |
| GEN-P1-13-02 | 33.4% | 35.6% | 0 | 0 | ⚠️ WARN |
| GEN-P1-15-01 | 43.2% | 79.8% | 0 | 0 | ⚠️ WARN |
| GEN-P1-16-02 | 58.0% | 78.6% | 0 | 0 | ⚠️ WARN |
| GEN-P1-17-01 | 35.5% | 40.4% | 0 | 0 | ⚠️ WARN |
| GEN-RAND-42-0003 | 78.2% | 61.6% | 0 | 0 | ⚠️ WARN |
| GEN-RAND-42-0005 | 85.5% | 70.1% | 0 | 0 | ⚠️ WARN |
| GEN-RAND-42-0009 | 55.1% | 72.6% | 0 | 0 | ⚠️ WARN |
| GEN-RAND-42-0010 | 12.3% | 31.7% | 0 | 0 | ⚠️ WARN |

</details>

## 行动建议
### 角色 A
- [LOW_UTILIZATION] 空间利用率低于 60%，需优化墙体效率和间隙填充 → `unified_solver.py 墙体构建 + gap_filler.py`
- [RIGID_STARVATION] 刚性 SKU 饥饿/弃装，弹性件可能抢占了截面配额 → `composite_strip.py 刚性优先分配`
