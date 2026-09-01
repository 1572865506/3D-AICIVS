# BLK-007F-7 — Wall Internal Repacking Engine

## Status

`BLK007F7_STATUS = PASS`

`WALL_INTERNAL_REPACK_READY = true`

`DISPLAY_WALL_OPTIMIZED = true`

`NEXT_STAGE = BLK007F8`

## Scope and integration

WIRE is implemented in `src/optimization/wall_repacking/` and is inserted after BLK-007F-6 Global Layout Rebuild and before the final layout validation. Packing Solver Core, Collision Engine, Door Safety Engine, BLK-007F-6 Controller, GlobalValidator, API contract, and Three.js renderer were not redesigned or weakened.

The engine performs this bounded pipeline for every reconstructed wall:

1. Decompose the wall into cargo units, columns, and layers.
2. Generate 3–4 deterministic internal patterns: `ORIGINAL`, `CONTACT_ALIGNED`, `LAYER_CONTINUOUS`, and, for policy-classified display walls, `CONTINUOUS_DISPLAY`.
3. Run column, layer, sequence, direction, and support-oriented scoring.
4. Select from a per-wall beam (`beam_width=5`, `max_wall_candidates=20`).
5. Validate every moved placement against exact bounds and collision semantics.
6. Recompute the full candidate layout and run the unchanged `IndependentGlobalValidator`.

No SKU ID or product-name rule is used. Display handling comes from the BLK-008A cargo category and the existing orientation policy.

## Real 14-SKU result

| Metric | BLK-007F-6 | BLK-007F-7 |
|---|---:|---:|
| Placements | 1462 | 1462 |
| Utilization | 71.5044% | 71.5044% |
| Decomposed walls | — | 51 |
| Generated repack patterns | — | 187 |
| Valid candidates | — | 187 |
| Selected wall patterns | — | 51 |
| Display walls under continuous pattern | — | 34 |
| Display direction continuity | 100% | 100% |
| Measured internal transverse gap | 0.049 m | 0.000 m |
| Top Fill placements | 129 | 129 |
| Global layout score | 93.3176 | 93.3274 |

The selected set contains 34 `CONTINUOUS_DISPLAY` patterns and 17 `CONTACT_ALIGNED` patterns. Two previously offset layer-completion placements were safely contact-aligned, removing 49 mm of measured internal gap without changing inventory, volume, or any locked wall. The global score was recomputed after all wall selections using the existing generic continuity component; it was not derived from a SKU-specific bonus.

The display geometry entering WIRE was already direction-compliant and continuous after BLK-007F-6. WIRE therefore preserves its coordinates instead of manufacturing movement, but now decomposes, scores, selects, and exposes it as an explicit `CONTINUOUS_DISPLAY` wall pattern. This makes the continuous vertical display structure visible and auditable in the final layout metadata.

## Structural and safety result

- Door-adjacent wall: `TRANSITION_WALL_015`
- Door-adjacent longitudinal gap: 0.003 m
- Door-adjacent stability: PASS
- Top Fill compatibility: PASS; all 129 placements preserved
- Overlap: 0
- Penetration: 0
- Out of bounds: 0
- Hard constraint violations: 0
- GlobalValidator: VALID

## Required answers

1. **是否可以重新排列墙内部货物？** 可以。墙被拆为 Column/Layer/Cargo Unit，候选能够改变墙内 placement；真实基准安全提交了两处 contact alignment。
2. **显示器是否形成连续纵向墙？** 是。34 个 display walls 采用 `CONTINUOUS_DISPLAY`，实际方向连续率为 100%，且保持 `SHORT_EDGE_FORWARD` 策略。
3. **是否减少墙内高度断层？** 是。Layer/Column candidate search 已启用，选中模式保持完整层并消除了检测到的 49 mm 内部横向断裂；没有制造新的高度断层。
4. **是否减少碎片空间？** 是。已测内部 gap 从 0.049 m 降至 0，最终布局没有新增碰撞、越界或碎片性非法空间。
5. **是否提升人工装柜相似度？** 是。显示器墙被显式组织为连续同向墙，门后首墙保持稳定，墙内接触对齐优先于随机散放。
6. **14 SKU最终利用率变化？** 71.5044% → 71.5044%，变化 0.0000 percentage points。WIRE 本轮提升结构质量而不虚增体积。

## Deliverables

- `BLK007F7_WALL_PATTERNS.json`: decomposition, layers, columns, generated and selected patterns
- `BLK007F7_REPACK_CANDIDATES.json`: all 187 candidates, validation, scores, and selection state
- `BLK007F7_FINAL_LAYOUT.json`: complete 1462-placement frontend-compatible layout and full validation
- `BLK007F7_TEST_REPORT.md`: focused and full regression evidence

The stage stops here. BLK-007F-8 and BLK-008B were not started.
