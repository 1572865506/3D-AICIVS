# BLK-007F-6 — Global Layout Rebuild Solver

## Status

`BLK007F6_STATUS = PASS`

`GLOBAL_REBUILD_READY = true`

`DIRECTION_EFFECTIVE = true`

`NEXT_STAGE = BLK008B`

## Implementation

GLRS is a new outer optimization layer. It does not modify Packing Solver Core, Beam Search, collision/validation engines, Cargo Intelligence, Door Safety, BLK007B/007C or Three.js.

The controller defaults to `NORMAL`; `REBUILD` is explicit. In rebuild mode it:

1. accepts the complete legal Door/Wall/Layer/TopFill layout as an incumbent;
2. destroys the incumbent wall order as a planning decision;
3. reconstructs whole Cargo and Transition wall slabs, carrying their dependent Top Fill/Layer placements with them;
4. generates five bounded strategy candidates;
5. runs full GlobalValidator independently for every candidate;
6. compares only complete legal layouts with the declared industrial objective;
7. returns the highest-scoring candidate.

Wall slabs are atomic reconstruction units. GLRS does not move individual supported cartons independently, so support relationships within a wall remain intact.

## Candidate competition

| Candidate | Strategy | Valid | Global score | Layer balance |
|---|---|---:|---:|---:|
| candidate_01 | INCUMBENT | yes | 93.3050 | 98.4163 |
| candidate_02 | DISPLAY_FIRST | yes | 93.3050 | 98.4163 |
| candidate_03 | HEAVY_FIRST | yes | 93.1974 | 97.3405 |
| candidate_04 | LAYER_BALANCED | yes | **93.3176** | **98.5423** |
| candidate_05 | DOOR_SAFE | yes | 93.2668 | 98.0344 |

Selected layout: **candidate_04**. Its 51 Cargo/Transition wall slabs use a different order from the incumbent. The old layout is not returned.

## Visible direction effect

The selected reconstruction changes the X positions of 448 out of 476 SKU-02 placements while preserving their `SHORT_EDGE_FORWARD` facing. Thus the DirectionPlan now affects real Three.js coordinates rather than only adding JSON labels.

All 856 non-top Display placements remain narrow-edge-forward, and the 129 profile-authorized SKU-14 Top Fill placements remain context-specific flat placements. MAIN_BODY flat count stays zero.

## Door and layer result

- Door Wall is re-instantiated inside every complete candidate and revalidated by the unchanged Door Safety/Global validation stack.
- Its safe 28-placement geometry is preserved; no independent single-box Door mutation is allowed.
- Transition-to-Door longitudinal seal coverage remains 99.75%.
- Frozen Door Wall cross-sectional coverage remains 86.6228%; this is not misreported as 95%.
- Layer balance improves from 98.4163 to 98.5423.

## Benchmark comparison

| Metric | BLK007F5 | BLK007F6 |
|---|---:|---:|
| placements | 1462 | 1462 |
| utilization | 71.5044% | 71.5044% |
| global layout score | 93.3050 | 93.3176 |
| layer balance | 98.4163 | 98.5423 |
| wall order changed | no | yes |
| visible SKU-02 positions changed | 0 | 448 |
| GlobalValidator | VALID | VALID |

The utilization delta is 0.0000 percentage points, safely inside the allowed 0.5-point regression budget. Improvement is structural rather than volume-only.

## Required answers

1. **是否真正重新生成布局？** 是。51 个完整 Cargo/Transition 墙段被重新排序，最终返回 candidate_04 而不是 incumbent。
2. **方向策略是否影响最终3D结果？** 是。448 个 SKU-02 placement 的真实 X 坐标改变，LoadingResult/Three.js 会读取新坐标。
3. **显示器是否形成窄面朝柜深结构？** 是。856/856 个非顶部 Display placement 均为 SHORT_EDGE_FORWARD。
4. **货墙是否重新组织？** 是。墙序发生变化，且墙内 placement/support 结构作为原子单元保留。
5. **柜门区域是否重新优化？** Door Wall 被重新实例化和验证，Transition 顺序参与候选重建；安全门墙几何未被擅自破坏。
6. **是否比BLK007F5更接近人工装柜？** 是。方向策略从标签变成实际墙序和坐标决策，层高连续性提高。
7. **14 SKU利用率变化？** 71.5044% → 71.5044%，无下降；Global Score 提升 0.0126。

## Validation

All five candidates are complete and legal. Final overlap=0, penetration=0, OOB=0, physical violations=0; GlobalValidator **VALID**. Full suite: **286/286 PASS**.

BLK-007F-6 到此停止；未进入 BLK008B 或 BLK009。
