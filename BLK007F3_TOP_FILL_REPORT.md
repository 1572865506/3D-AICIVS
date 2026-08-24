# BLK-007F-3 — Top Fill Space Optimization Report

## Status

`BLK007F3_STATUS = PASS`

`TOP_FILL_ENGINE_READY = true`

`TOP_ORIENTATION_READY = true`

`NEXT_STAGE = BLK007G`

Work stopped at BLK-007F-3. BLK-007G and BLK-008 were not started.

## Architecture

The new `src/constraints/topfill` layer runs after the main/transition wall result and before final validation:

1. `TopSpaceDetector` extracts only real continuous top surfaces from locked Cargo Walls.
2. `TopRegionClassifier` separates `AVAILABLE_TOP`, `WEAK_SUPPORT_TOP` and `NO_FILL`.
3. `TopCandidateGenerator` considers remaining inventory and declared CargoProfile policy.
4. `TopOrientationOptimizer` maps an explicitly permitted flat orientation to `TOP_HORIZONTAL`.
5. `TopSupportAnalyzer` calculates contact area, support ratio and projected top load.
6. `TopPlacementValidator` applies support, collision and bounds gates.
7. `TopLayerBuilder` creates region-local layers capped at three.
8. `TopFillScore` evaluates volume, height usage, support, load safety, orientation fit and risk.
9. The full `IndependentGlobalValidator` validates the unchanged walls plus committed Top Fill placements.

The engine does not infer FLAT for AUTO cargo. Only SKU-02 and SKU-14 have explicit USER_DEFINED conditional-flat permission in the canonical manifest. Existing min-base-height and maximum three-layer rules remain authoritative.

## Real 14-SKU result

| Metric | BLK-007F-2 | BLK-007F-3 | Change |
|---|---:|---:|---:|
| Final placements | 1330 | 1459 | +129 |
| Utilization | 69.1412% | 71.3574% | +2.2162 pp |
| Reachable residual volume | 20.177503 m³ | 18.444191 m³ | -1.733312 m³ (-8.59%) |
| Cargo volume | 52.790262 m³ | 54.482412 m³ | +1.692150 m³ |

Top Fill diagnostics:

- detected top regions: 17
- available top regions: 17
- total available top-region volume: 7.994691 m³
- placed Top Fill volume: 1.692150 m³
- local top-space utilization: 21.1659%
- Top Fill placements: 129
- selected SKU: SKU-14 ×129
- selected orientation: `FLAT_ZX` / `TOP_HORIZONTAL`
- layer 1 placements: 51
- layer 2 placements: 51
- layer 3 placements: 27
- maximum layers in any region: 3
- Top Fill score: 93.0602/100
- remaining unused top-region volume: 6.302541 m³

SKU-02's explicit `TOP_HORIZONTAL` path is covered by TOP-002 and passes at base z=2.53m. In the real benchmark, the generic ranking selected lighter SKU-14 because it provided the better safe inventory/geometry fit. No SKU-specific bonus was used.

## Structural and safety result

- structural wall fingerprint preserved: true
- Cargo Wall placements moved or rotated: 0
- Transition Wall placements moved or rotated: 0
- Door Wall placements moved or rotated: 0
- support rejection threshold: 0.8
- actual committed support ratio: 1.0
- GlobalValidator: VALID
- overlap pairs: 0
- penetration volume: 0
- OOB: 0
- hard violations: 0
- enclosed cavities: 0
- ordinary cargo in reserved door zone: 0
- LoadingSequence: feasible; Top Fill depends on completed supporting walls
- Door Wall: 28 locked SKU-02 placements, unchanged

Packing Solver Core, Beam Search, Candidate Generator core, Collision Engine, Compression Validator, Door/Cargo Wall/Wall Optimization engines, Repair, BLK007C and Three.js were not modified.

## Required answers

1. **是否成功识别顶部空间？** 是，识别 17 个真实墙顶区域，全部具有连续支撑面。
2. **是否支持显示器顶部横放？** 是。SKU-02 和 SKU-14 的 USER_DEFINED conditional-flat 可映射为 `TOP_HORIZONTAL`；真实方案使用 SKU-14 `FLAT_ZX`。
3. **是否支持 1–3 层顶部填充？** 是，真实结果同时包含第1、2、3层，任何区域不超过3层。
4. **是否提升空间利用率？** 是，整体利用率提升 2.2162 个百分点。
5. **是否保持货墙稳定？** 是，墙体指纹不变、实际支撑率1.0、最终物理验证通过。
6. **是否保持 Door Wall 安全？** 是，28件锁定门墙及零门区侵入保持。
7. **14 SKU 最终提升多少？** 从69.1412%提升至71.3574%，增加1.69215m³货物体积和129件货物。
