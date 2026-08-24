# BLK-007F-7.5 — True Cargo Recomposition Solver

## Status

`BLK007F75_STATUS = PASS`

`TRUE_RECOMPOSITION_READY = true`

`VISIBLE_LAYOUT_CHANGE = true`

`NEXT_STAGE = BLK007F8`

## Implementation

TCRS is implemented as an independent layer in `src/optimization/cargo_recomposition/`. It runs after the accepted BLK-007F-6 global candidate and before the existing BLK-007F-7 WIRE/final validation interface:

`GLRS → Cargo Pool Extraction → Cargo Grouping → Wall/Layer Recomposition → Orientation Search → Cargo Swap → WIRE → GlobalValidator`

Packing Solver Core, Collision Engine, GlobalValidator, Door Safety Engine, BLK-007F-6, BLK-007F-7 validation, Three.js, and the BLK007C schema were not replaced or weakened.

## True recomposition result

The complete 1462-placement layout was detached from its wall membership and placed in a cargo pool. Cargo was classified into four operational groups and sequenced as:

`HEAVY_BASE → MAIN_WALL → DISPLAY_WALL → FRAGILE`

Ten deterministic candidates were generated under a bounded search (`beam_width=20`, `max_candidates=50`). All ten passed the full validator. The selected candidate was:

- Candidate: `candidate_08`
- Strategy: `HEAVY_FIRST_MIRROR`
- Relocated placements: 1434 / 1462
- Coordinate-change ratio: 98.0848%
- Wall membership changes: 1434
- Locked Door Wall placements moved: 0
- Orientation mutations committed: 0; no unsafe free rotation was needed

This is a physical reconstruction: wall slabs are reordered by cargo group and non-door geometry is laterally reconstructed. The changed coordinates are recorded per cargo in the swap log and frontend cargo metadata; this is not an ID-only or label-only change.

## Score and benchmark

| Metric | BLK-007F-7 baseline | TCRS selected |
|---|---:|---:|
| Wall continuity | 84.0000 | 88.0000 |
| Direction compliance | 100.0000 | 100.0000 |
| Transport safety | 92.0000 | 92.0000 |
| Space efficiency | 71.5044 | 71.5044 |
| Door safety | 100.0000 | 100.0000 |
| Layer balance | 99.6610 | 99.6610 |
| Weighted global score | 90.0918 | 91.0918 |

The score uses the requested generic weights: wall continuity 25%, direction 20%, transport safety 20%, space efficiency 15%, door safety 10%, and layer balance 10%. There is no SKU-ID or benchmark-specific bonus.

## Display and door

- 856 MAIN display placements were checked.
- Display continuity: 100%
- Same-orientation ratio: 100%
- Display direction: `SHORT_EDGE_FORWARD`
- Door first-layer short-edge ratio: 100%
- Door first-layer stability: PASS
- All 28 locked Door Wall anchors retain their original coordinates.

The display wall was already direction-valid before TCRS, so the improvement is wall-level grouping/adjacency and visible placement reconstruction rather than inventing a different orientation. The Door Wall was already optimal and locked; TCRS validates and preserves it instead of moving a safety anchor merely to claim improvement.

## Physical validation

- Utilization: 71.5044% → 71.5044%
- Placement count: 1462
- Overlap: 0
- Penetration: 0
- Out of bounds: 0
- Hard constraint violations: 0
- GlobalValidator: VALID
- Top Fill and WIRE compatibility: PASS

## Required answers

1. **是否真正拆散原货墙？** 是。1462 件货物全部进入无 wall 绑定的 CargoPool，再按 cargo group 重建 blueprint。
2. **多少货物发生重新定位？** 1434 件，占 98.0848%，均有 original/new position 审计记录。
3. **显示器是否形成真正连续墙？** 是。856 件主体 Display 的连续率和同向率均为 100%。
4. **柜门第一层是否符合防倾倒原则？** 是。短边朝柜深比例 100%，稳定验证通过；28 个锁定门墙锚点未移动。
5. **是否出现新的人工装柜结构？** 是。选中 Heavy-first wall composition，并按人工序列组织 Heavy Base、Main、Display、Fragile。
6. **14 SKU评分变化？** 全局结构分 90.0918 → 91.0918，提升 1.0000；利用率保持 71.5044%。

本阶段到此停止，未进入 BLK-007F-8 或 BLK-008B。
