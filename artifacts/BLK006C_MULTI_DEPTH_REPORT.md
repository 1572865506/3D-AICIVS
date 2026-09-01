# BLK-006C — Multi-depth Beam Search + Budgeted State Pruning

## Outcome

GLOBAL_SEARCH now returns a complete legal solution through `MAIN → TRANSITION → DOOR → TOP_FILL → COMPLETE`; incomplete branches can never replace production output and fall back to the preserved LEGACY_GREEDY path. Search remains opt-in and the production incumbent was not changed.

| run | depth | generated / expanded states | complete | utilization | Top Fill utilization | solver runtime |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| beam=2 | 4 | 32 / 9 | 1 | 40.5038% | 8.26% | 105.112s |
| beam=4 | 4 | 54 / 14 | 1 | 40.5038% | 8.26% | 139.959s |

Both runs use candidate cap 6, depth 4, runtime expansion budget 90s, 96 generated-state budget, and 32 expanded-state budget. Beam selection preserves distinct recent SKU composition, wall width/height, layer structure, orientation-derived structure, and top surface. Exact structural state deduplication and conservative dominance are active; canonical counters may remain zero when no equivalent/comparable states occur, while the included pruning proof removes both an exact duplicate and a genuinely dominated state.

The production-default verification run (beam=2) completes within the 120s target. The requested beam=4 architecture probe remains complete and legal but takes 139.959s; its extra 5 state expansions are fully profiled rather than hidden by disabling safety checks.

## Objective and performance

Every candidate trace records raw physical units, normalized values, and weighted values. Hard-invalid candidates are rejected before objective scoring. Intermediate branches use the cheap Top Fill estimator (32 calls for beam=2); complete candidates alone run full BLK-005C (1 call).

For beam=2, average candidate generation / hard validation / clone / objective / Top Fill estimate / state expansion costs are 191.826 / 73.168 / 1.320 / 0.024 / 0.079 / 6103.518 ms. The primary instrumented hotspot is `state_expansion_ms`. Solver runtime excludes the report-only postsolve re-extraction performed by this benchmark.

## Safety and regression

Both complete solutions have door_ready=true and GlobalValidator=VALID, with zero overlap, penetration, OOB, hard violations, enclosed cavities, bridge voids, AUTO flat, and MAIN_BODY conditional-flat placements. USER_DEFINED CargoProfile fingerprint is unchanged.

- deterministic replay: PASS
- branch isolation / pruning contracts: PASS
- TOP-001~012: PASS
- WALL-001~010: PASS
- BLK-005B / 005C / 006A / 006B: PASS / PASS / PASS / PASS
- full suite: 156/156 PASS

## Stop condition

BLK-006C is complete. LEGACY_GREEDY remains the production incumbent, GLOBAL_SEARCH remains opt-in, and BLK-006D was not started.
