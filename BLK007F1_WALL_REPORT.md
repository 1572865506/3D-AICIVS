# BLK-007F-1 — Cargo Wall Formation Report

## Status

`BLK007F1_STATUS = PASS`

`CARGO_WALL_ENGINE_READY = true`

`VOID_ANALYSIS_READY = true`

`NEXT_STAGE = BLK007F2`

Work stopped at BLK-007F-1. BLK-008 was not started.

## Architecture

The new `src/constraints/wall` layer executes after the BLK-007E door anchor and before the frozen main solver. It generates deterministic complete-layer wall anchors, reserves their inventory, and delegates only the translated residual container to the unchanged solver.

Pipeline:

1. Cargo classification and Door Wall anchor.
2. WallRegionPlanner partitions the non-door volume into 1.2 m logical regions.
3. CargoWallBuilder enumerates legal MAIN_WALL upright orientations.
4. Complete transverse layers are created and validated for continuity, support, compression-compatible layer limits, stability and voids.
5. Wall placements and inventory are frozen.
6. The original solver runs unchanged in the remaining x-range.
7. Door Wall, Cargo Walls and residual placements are merged in the original container.
8. Full IndependentGlobalValidator and LoadingSequencePlanner run on the result.

The thin-wall rule uses geometry and existing CargoRisk/CargoProfile policy. It contains no SKU-ID or product-name branch.

## Real 14-SKU result

| Metric | BLK-007E-2 FAST baseline | BLK-007F-1 | Change |
|---|---:|---:|---:|
| Final placements | 265 | 877 | +612 |
| Utilization | 31.8190% | 60.3716% | +28.5526 pp |
| Reachable residual volume | 49.137444 m³ | 26.341472 m³ | -22.795972 m³ (-46.39%) |
| Floor-level share of non-door cargo | 26.16% | 20.02% | -6.14 pp |
| Elevated non-door placements | 175 | 679 | +504 |
| Door-wall placements | 28 | 28 | unchanged |
| Ordinary cargo inside reserved door zone | 0 | 0 | unchanged |

Wall-specific result:

- cargo walls: 17
- structural wall placements: 474
- planned wall x-range: 0–7.227 m
- average wall coverage: 90.7888%
- average continuity score: 88.0255/100
- average wall score: 95.8089/100
- average constructed height: 2.0521 m
- isolated wall cargo: 0
- weak support areas: 0
- support/contact links: 839
- internal structural void volume: 0 m³
- available top regions exported for BLK-007F-3: 17

## Safety and compatibility

- GlobalValidator: VALID
- overlap pairs: 0
- penetration volume: 0
- out of bounds: 0
- hard violations: 0
- enclosed cavity count: 0
- LoadingSequence: feasible
- Door Wall: 28 × SKU-02, `SHORT_EDGE_FORWARD`, locked
- BLK007B Repair Engine: unchanged
- BLK007C schema: existing fields unchanged; additive `cargo.role=CARGO_WALL` is emitted
- Door Wall Engine and reserved-zone semantics: unchanged
- Top Fill implementation: unchanged; only `available_top_regions` is exported

## Required answers

1. **主体货物是否形成连续货墙？** 是。474 件主货形成 17 堵完整横向层货墙，平均覆盖率 90.79%，孤岛数为 0。
2. **是否减少底层堆积？** 是。非门墙货物的地板层占比由 26.16% 降至 20.02%，高于地板的 placement 增加到 679。
3. **是否减少中空区域？** 是。结构墙内部 void 为 0；最终 reachable residual volume 相对 007E-2 验证基线减少 46.39%。
4. **是否保持 Door Wall 安全？** 是。28 件锁定门墙、方向、预留范围和零侵入全部保持。
5. **是否影响 BLK007B/007E？** 未修改 Repair 或 Door Engine；完整回归和可执行 Loading Sequence 均通过。
6. **14 SKU 案例改善多少？** 同一 FAST 验证配置下利用率提高 28.5526 个百分点，placement 增加 612，且全部硬安全指标仍为零。

## Frozen-core evidence

No Beam Search, Candidate Generator core, Collision Engine, Compression Validator, Door Wall Engine, Repair Engine, BLK007C contract, or Three.js renderer implementation was changed. Server orchestration enables the new constraint layer explicitly; legacy `DoorIntegratedSolver` behavior remains available with Cargo Walls disabled.
