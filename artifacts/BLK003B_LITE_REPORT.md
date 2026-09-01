# BLK-003B Lite Report

## Scope

BLK-003B Lite was implemented as a compatibility-preserving extension of the accepted Clean-Room Solver V2. The search objective, Elastic Door Frontier, Door Reserve / Door Seal, collision semantics, SupportGraph, stability, Three.js, and existing regression gates were not redesigned or modified. Top Fill was not entered.

Git baseline:

- branch: `feature/v2-cleanroom-solver`
- commit: `05586dbe1e56a490b2dd761ce4c792c6cef2f66e`
- pre-existing dirty worktree preserved

## Implementation

- Added atomic `WallSlice` structural metadata while preserving the original slice API.
- Added `LogicalWall`, grouping cartons that share a longitudinal band and merging only adjacent micro-slices with verified Y-Z structural continuity.
- Added an X-Y `TopSurface` with area-bearing cells, covered/usable area, weighted elevation statistics, flatness, and availability.
- Retained the accepted Y-Z `WallSurfaceMap` as the LogicalWall `frontier_surface`.
- Changed aggregate wall flatness to frontier-area weighting so micro-walls cannot dominate the result.
- Added explicit `FUTURE_FREE_SPACE` semantics. Reachable voxels at/ahead of the local Y-Z frontier are normal future capacity; reachable voxels behind an existing or bounded/interpolated frontier are `WALL_OPEN_NOTCH` (`OPEN_NOTCH` in the compatibility enum/API).

## Required Metrics

The primary comparison uses the deterministic BALANCED seed-42 benchmark. OPTIMIZE is included because it is an explicit regression gate.

| metric | before BALANCED | after BALANCED | after OPTIMIZE |
| --- | ---: | ---: | ---: |
| before_wall_count | 112 | 112 | 112 |
| logical_wall_count | — | 19 | 18 |
| wall_slice_count | — | 22 | 22 |
| avg_items_per_logical_wall | 3.0089 items/legacy wall | 17.736842 | 17.388889 |
| weighted_wall_flatness | legacy unweighted 1.0000 | 0.983499 | 0.982984 |
| wall_open_notch_volume | 48.71475 m³ mixed semantic volume | 3.34080 m³ | 3.98285 m³ |
| future_free_space_volume | not distinguished | 45.37395 m³ | 45.50298 m³ |
| top_surface_available | not available | 19 / 19 LogicalWalls | 18 / 18 LogicalWalls |

The BALANCED semantic split is volume-conserving relative to the previous mixed metric:

`3.34080 + 45.37395 = 48.71475 m³`.

## Root Cause Resolution

The legacy wall extractor cut whenever `p.min_x >= current_x_max - 0.02` or when one carton's depth exceeded the fixed `0.80m` span limit. In the BALANCED layout, 96 SKU-05 cartons are `0.833m` deep, so each carton tripped the span condition even when 16 cartons occupied the same structural X band. This produced 96 one-item walls, 112 walls overall, and artificially perfect per-wall flatness.

The new segmentation first groups cartons with the same overlapping longitudinal band into an atomic WallSlice, then performs conservative structural merging. On the unchanged 337-placement solution this reduces 112 legacy fragments to 22 WallSlices and 19 LogicalWalls without changing any placement.

## Regression Results

| gate | BALANCED | OPTIMIZE | required | result |
| --- | ---: | ---: | ---: | --- |
| placed | 337 | 313 | informational | PASS |
| utilization | 36.9524% | 36.0274% | >= 34% | PASS |
| max_x | 11.978m | 11.978m | retained baseline | PASS |
| door_ready | true | true | true | PASS |
| overlap | 0 | 0 | 0 | PASS |
| penetration | 0.0m³ | 0.0m³ | 0 | PASS |
| out_of_bounds | 0 | 0 | 0 | PASS |
| hard_constraint_violations | 0 | 0 | 0 | PASS |
| enclosed_cavity_volume | 0.0m³ | 0.0m³ | 0 | PASS |
| bridge_void_count | 0 | 0 | 0 | PASS |

Test results:

- `WALL-001` through `WALL-010`: 10 / 10 PASS
- BLK-003B targeted LogicalWall / TopSurface / future-space tests: 3 / 3 PASS
- full suite: 124 / 124 PASS (`python3 -m unittest discover -s tests`, 117.305s)

## Stop Condition

BLK-003B Lite is complete. No Top Fill work was started.
