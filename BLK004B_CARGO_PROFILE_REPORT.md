# BLK-004B — Cargo Constraint Profile & Real Benchmark Activation

## Outcome

The canonical 14-SKU benchmark now uses explicit CargoProfile references. Profile-backed inputs bypass natural-language requirement parsing. Conditional flat is activated by declared context rules only; no SKU name or dimension inference was added.

## Real benchmark proof

| metric | BALANCED | OPTIMIZE |
| --- | ---: | ---: |
| placed | 349 | 329 |
| utilization | 37.1585% | 36.3022% |
| conditional flat | 12 | 16 |
| max Top Fill layer | 3 | 3 |
| MAIN_BODY conditional flat | 0 | 0 |
| door_ready | true | true |

The real benchmark produced CONDITIONAL_FLAT and genuine 2-layer / 3-layer stacks on LogicalWall TopSurface. Layer coordinates and eligibility-stage diagnostics are recorded in `BLK004B_BENCHMARK_RESULT.json`.

## Policy migration and enforcement

- CargoProfile contains Geometry, Orientation, Placement, Stack, Compression, Stability, TopFill, Zone, and Handling policies.
- 14/14 SKUs resolve an explicit profile; field provenance totals: DEFAULT=381, USER_DEFINED=81.
- Region eligibility is recorded separately as geometry, policy, physics, inventory, and final eligibility, with rejection reasons.
- Stack self/category constraints and max top load/pressure continue through LoadPropagationEngine; Top Fill continues through existing hard validation and full stability evaluation.
- Search Objective, Door, Collision, Support thresholds, Compression thresholds, and Stability thresholds were not weakened.

## Regression

| gate | BALANCED | OPTIMIZE |
| --- | ---: | ---: |
| overlap | 0 | 0 |
| penetration | 0.0 | 0.0 |
| OOB | 0 | 0 |
| hard violations | 0 | 0 |
| door_ready | true | true |
| enclosed cavity | 0 | 0 |
| bridge void | 0 | 0 |

- TOP-001~012: PASS
- WALL-001~010: PASS
- full suite: 140/140 PASS

## Stop condition

BLK-004B is complete. Search Optimization was not started.
