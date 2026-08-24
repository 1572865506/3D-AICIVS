# BLK-007F-8B — Residual Space Filling Engine

> **SUPERSEDED:** 本报告记录的逐箱残余填充结果已被
> `BLK007F8B_REPAIR_REPORT.md` 取代。`1626 / 77.664761%` 虽通过基础物理
> 验证，但产生棋盘式、孤立式货物排列，不再作为有效生产结果或验收基线。

## Status

`BLK007F8B_STATUS = PASS`

`RESIDUAL_SPACE_FILLING_READY = true`

`SIDE_ALIGNED_WALLS_READY = true`

`NEXT_STAGE = BLK007F8C`

BLK-007F-8C has not been started.

## Screenshot coordinate interpretation

The screenshot is a top view. Its UI axis is mirrored from the canonical solver axis:

- UI left / `0m`: doors.
- UI right / `12m`: deepest interior.
- Canonical solver X: deepest interior toward doors.

The reported loose `7–11m` UI interval therefore maps to the corresponding mirrored canonical interval. Diagnostics use both representations and do not mistake the view for a side elevation.

## Root causes corrected

1. `WallContinuityOptimizer` centered every incomplete wall and split one usable side residual into two narrow strips.
2. `WallExpansionEngine` independently repeated the same centering for transition walls.
3. Top Fill searched only coarse wall regions and did not enumerate every exposed physical carton top.
4. No final pass reconsidered remaining inventory for floor-side gaps and policy-legal cross-SKU stacking.

Incomplete walls are now aligned to a container side. Later global mirroring may choose the opposite side, but a wall must remain side-aligned; it may no longer float in the center with gaps on both sides.

## Residual candidate flow

The bounded filler engine runs after WIRE and before final validation:

`final structural layout → floor edge frontier → exposed top faces → policy-legal orientations → spatial collision → exact support/stack policy → inventory → commit → GlobalValidator`

It adds no orientation rights. AUTO does not obtain FLAT or SIDE. Door-reserved geometry is excluded. Every accepted placement continues through the authoritative final GlobalValidator.

## 14-SKU result

- Safe aligned pre-fill layout: `1593` placements, `75.651930%` utilization.
- Residual additions: `33` placements.
- Added volume: `1.536825m³`.
- Floor residual additions: `7`.
- Exposed-top additions: `26`.
- UI `7–11m` interval additions: `17` (`3` floor, `14` top).
- SKU mix: `SKU-03 × 8`, `SKU-04 × 21`, `SKU-14 × 4`.
- Minimum support ratio: `0.705882`.
- Average support ratio: `0.968676`.
- Final placements: `1626`.
- Final utilization: `77.664761%`.
- Utilization gain over aligned pre-fill layout: `+2.012831 percentage points`.

## Safety result

- Collision overlap: `0`.
- Penetration: `0`.
- OOB: `0`.
- Hard violations: `0`.
- Door wall unchanged and locked.
- Door-open transport stability: `PASS`.
- MAIN display direction: `PASS`.
- GlobalValidator: `VALID`.

The remaining inventory is primarily display cartons that do not fit any currently reachable floor/top frontier under existing orientation, support, zone, compression, and collision rules. No hard threshold was lowered to force them into fragmented spaces.
