# BLK-007F-4 — Layer & Orientation Optimization Report

## Status

`BLK007F4_STATUS = PASS`

`LAYER_OPTIMIZATION_READY = true`

`ORIENTATION_OPTIMIZATION_READY = true`

`NEXT_STAGE = BLK008B`

## Delivered architecture

LOOE is an opt-in outer layer between Wall Optimization and Top Fill:

`Door/Cargo/Transition Walls (frozen) → LayerAnalyzer → OrientationOptimizer → LayerCompletionEngine → WallBridgeEngine → Top Fill → full GlobalValidator`

The implementation adds the requested layer types, occupancy map, simulation-based orientation selection, bounded layer completion, conservative bridge evaluation, Door Seal analysis, score engine, and solver adapter. Packing Solver Core, Beam Search, collision/compression engines, Door Wall, Cargo Wall, Top Fill, Cargo Intelligence, BLK007B/007C and Three.js were not redesigned.

## 14-SKU before/after

| Metric | BLK007F3 | BLK007F4 |
|---|---:|---:|
| placements | 1459 | 1462 |
| utilization | 71.3574% | 71.5044% |
| improvement | — | **+0.1470 percentage points** |
| LOOE added volume | — | 0.1122 m³ |
| Top Fill placements | 129 | 129 |
| Top Fill volume | 1.69215 m³ | 1.69215 m³ |
| detected layer void | 16.356896 m³ | 16.260246 m³ |
| mean raster occupancy | 0.738160 | 0.739299 |

The three committed completion placements are SKU-12 ×1 and SKU-11 ×2, all legal upright placements in floor-supported wall-side gaps. Thin display cargo with `NEIGHBOR_SUPPORT_REQUIRED` is not admitted as an isolated one-box filler.

## Dynamic orientation semantics

Orientation is now selected from the intersection of:

1. existing Solver V2 `OrientationPolicy` legality;
2. BLK008A Cargo Intelligence context policy;
3. current available geometry;
4. support and stability state;
5. simulated layer-completion score.

The optimizer never manufactures an orientation. In the acceptance probes, SKU-14 selects VERTICAL in MAIN_WALL and FLAT_HORIZONTAL in a 0.2 m TOP_FILL space above its 1.3 m minimum base height. SKU-02 behaves equivalently but retains its 2.5 m user-defined minimum. Actual LOOE MAIN placements contain zero flat orientations.

## Layer, bridge, and Door Seal results

- Layer 0 occupancy increased from 87.4317% to 88.1148%; its detected void fell by 0.09665 m³.
- Higher unsupported raster gaps were not force-filled. Sixteen wall-interface bridge opportunities were audited, but no bridge was committed merely from an estimated score. A bridge candidate is valid only with support ≥0.8, compression PASS, and Profile permission; any real commit must still pass the full physical stack.
- Door/Cargo/Transition structural fingerprints remained unchanged.
- The Transition-to-Door longitudinal interface gap is 3 mm, yielding 99.75% longitudinal seal coverage (target ≥95%).
- The frozen Door Wall cross-sectional coverage remains 86.6228%. This is reported separately and was not relabeled as 95%; changing it would require modifying the frozen Door Wall, which this block explicitly forbids.

## Required answers

1. **货物方向是否由空间动态决定？** 是。方向由当前 Context、空间、支撑、稳定性和双重 Policy 共同模拟评分决定；禁止方向不会进入候选。
2. **是否减少高度断层？** 是，合法可达的 Layer 0 断层被补齐；无支撑的高层断层保持未填，避免悬空。
3. **是否提升柜门覆盖？** Transition-to-Door 的纵向封口覆盖为 99.75%。冻结门墙的横截面覆盖仍为 86.6228%，未伪造提升。
4. **是否提高货墙顶部利用率？** Top Fill 保持 129 件/1.69215 m³，未回退；本轮新增收益来自 Top Fill 前的层补齐。
5. **是否减少碎片空间？** 是。栅格检测的层空隙减少 0.09665 m³，且没有通过不安全桥接制造新洞。
6. **14 SKU结果是否改善？** 是，利用率从 71.3574% 提升到 71.5044%，增加 0.1470 个百分点。

## Validation

Final GlobalValidator: **VALID**. Overlap=0, penetration=0, OOB=0, hard violations=0, stability violations=0, enclosed cavities=0. Full suite: **273/273 PASS**.

BLK-007F-4 到此停止；未进入 BLK008B 或 BLK009。
