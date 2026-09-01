# BLK-006A — Global Wall-Plan Search State & Objective

## Outcome

BLK-006A establishes an opt-in `GLOBAL_SEARCH` wall-plan architecture while preserving `LEGACY_GREEDY` as the production incumbent. SearchState owns independent placement, inventory, support/load/stability, residual-space, Top Fill potential, door, hard-state, score, parent, and depth data. WallCandidate proposals reuse the existing aggregate generator and become searchable branches only after HardValidator plus existing load, item, cluster, and wall stability evaluators pass.

Hard-invalid proposals are rejected immediately and never enter the soft objective. The explainable objective contains main-body gain, future Top Fill estimate, residual quality, compactness, inventory fit, fragmentation, unstable-geometry, and door-risk components.

## A/B architecture verification

| plan | states generated | expanded | proposals | rejected | selected depth | utilization | Top Fill utilization |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| GLOBAL beam=1 | 1 | 2 | 2 | 1 | 1 | 19.1666% | 24.7363% |
| GLOBAL beam=2 | 1 | 2 | 2 | 1 | 1 | 19.1666% | 24.7363% |

Beam width 2 has real competition: proposals generated (2) exceed selected path entries (1). The raw bounded contenders stop early because strict partial-wall stability rejects unsafe/incomplete alternatives. No threshold was lowered. Incumbent selection therefore retains the accepted BLK-005C complete plan: BALANCED 41.4627% and OPTIMIZE 41.7456% overall utilization. This prevents an incomplete 006A architecture probe from replacing a stronger feasible plan.

## Replay and isolation

- Same seed/input/mode beam=2 replay: TRUE.
- Deep branch isolation: PASS; mutable inventory, placement lists, wall sequences, and state maps are not shared.
- Objective explainability: PASS; every valid WallCandidate trace includes all score components and final score.
- Legacy default preserved: PASS; GLOBAL_SEARCH remains opt-in.
- USER_DEFINED profile fingerprint unchanged: TRUE.

## Safety and regression

Both bounded GLOBAL contenders pass zero overlap, penetration, OOB, and hard-violation candidate gates; AUTO flat and MAIN_BODY conditional-flat remain zero. Because depth-1 contenders are intentionally incomplete, Door Closure and final cavity gates are not used to promote them. The retained complete legacy incumbent passes zero enclosed cavity/bridge void and `door_ready=true` in both BALANCED and OPTIMIZE.

- TOP-001~012: PASS
- WALL-001~010: PASS
- BLK-005B: PASS
- BLK-005C: PASS
- Full suite: 150/150 PASS

## Stop condition

BLK-006A is complete. No parameter tuning, large-scale beam search, or BLK-006B work was started.
