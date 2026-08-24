# BLK-006F — Global Quality Consolidation & Benchmark Generalization

## Decision

`SOLVER_V1_CORE_FROZEN = true`

The 12-benchmark deterministic suite, three-profile matrix, adversarial/edge cases, metric, inventory, Door, plan-diversity, runtime and source-code audits are complete. No packing algorithm, candidate family, repair operator, CargoProfile rule, Door rule, Orientation rule, hard threshold, or benchmark-specific scoring branch was added.

## Required answers

1. GLOBAL/Repair is **not limited to BENCH-001**.
2. It won **2 / 12** normal benchmarks; source counts: `{'GLOBAL_TOPFILL_REPAIR': 1, 'LEGACY_INCUMBENT': 10, 'GLOBAL_SEARCH': 1}`.
3. Median delta vs Legacy: **0.000000 pp**.
4. Worst regression: **0.000000 pp**.
5. Catastrophic regressions (>3pp): **0**.
6. On BENCH-001, eight TopFill families produced **5 independent plans (62.5%)**. Across the suite, the three benchmarks with extracted TopFill plans produced **7 benchmark-scoped independent signatures from 24 family plans**; BENCH-010 and BENCH-012 each collapsed to one unique plan, and are not overstated as eight strategies.
7. Stage B/C status: **NOT_YET_PROVEN_USEFUL / NOT_YET_PROVEN_USEFUL**.
8. `beam=2/cap=6/depth=4` is **a stable default**; FAST and depth-5 sensitivity did not require benchmark-specific tuning.
9. Runtime outliers: **0**; runaway state growth: **False**.
10. Inventory / metric / Door audit issues: **0**.
11. Benchmark-specific code or SKU-specific scoring found: **False**.
12. Solver V1 can be frozen: **True**. Blockers: `[]`.

## Freeze reference

The repository is dirty and Solver V2 is largely untracked, so no misleading Git tag was created at old HEAD. The authoritative local baseline is the worktree manifest SHA-256 `2dced693b65d976e4f72eee70474e2c81b6e8c1009716b009aff05f860231f53` plus this eight-file delivery. Recommended tag after a clean scoped commit: `solver-v1-core-blk006f`.

BLK-007 was not started.
