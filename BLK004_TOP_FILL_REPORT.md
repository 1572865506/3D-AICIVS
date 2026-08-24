# BLK-004 — Conditional Top Fill Planner Report

## Outcome

Conditional Top Fill is implemented on top of BLK-003B LogicalWall.TopSurface. Flat orientation remains forbidden in MAIN_BODY unless an explicit rule allows it, and conditional flat is activated only inside a real TopFillRegion. No SKU identifier or display dimension is hard-coded in solver logic.

## Model and execution

- `OrientationPolicy.rules[]` provides region-bound `OrientationRule` conditions.
- `TopFillRegion` is extracted from continuous coplanar TopSurface cells, not `container_height - carton.max_z`.
- Height capacity computes `floor(available_height / orientation_height)` and applies rule/stack limits.
- Region candidates reuse HardValidationPipeline, SupportGraph, LoadPropagationEngine, ItemStabilityEvaluator, ClusterStabilityEvaluator, and WallStabilityEvaluator.
- Search order is main construction, bounded conditional top fill while the door reservation remains active, then unchanged Door Closure.

## 14-SKU benchmark

| metric | BALANCED | OPTIMIZE |
| --- | ---: | ---: |
| placed | 349 | 329 |
| utilization | 37.1992% | 36.3565% |
| door_ready | true | true |
| top_fill_region_count | 28 | 27 |
| top_fill_usable_volume | 39.43731 m³ | 39.208 m³ |
| top_fill_placed_count | 12 | 16 |
| top_fill_placed_volume | 0.18846 m³ | 0.25128 m³ |
| top_fill_utilization | 0.004779 | 0.006409 |
| residual_top_volume | 39.18171 m³ | 38.8672 m³ |

The canonical 14-SKU manifest declares upright-only policies, so the benchmark does not infer conditional-flat permission from SKU names or thin dimensions. Its Top Fill placements are upright. TOP-002/003/004 prove declarative conditional-flat 1/2/3-layer activation.

## Regression gates

| gate | BALANCED | OPTIMIZE | result |
| --- | ---: | ---: | --- |
| overlap | 0 | 0 | PASS |
| penetration | 0.0 | 0.0 | PASS |
| OOB | 0 | 0 | PASS |
| hard violations | 0 | 0 | PASS |
| door_ready | true | true | PASS |
| enclosed cavity | 0 | 0 | PASS |
| bridge void | 0 | 0 | PASS |

- TOP-001 through TOP-012: 12/12 PASS
- WALL-001 through WALL-010: 10/10 PASS
- full test suite: 136/136 PASS (`python3 -m unittest discover -s tests`, 97.315s)

## Stop condition

BLK-004 is complete. No next BLK was started.
