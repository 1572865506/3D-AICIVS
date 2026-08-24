# BLK-006B — Diverse Wall Candidate Generation

## Outcome

Root candidate diversity is no longer collapsed. The deterministic family sampler canonicalizes the existing general aggregate space and retains bounded homogeneous, alternate-orientation, alternate-width, alternate-height, mixed-SKU, and residual-aware proposals. Partial 6×5×3-style blocks are represented by bounded variants already produced by the generic PatternGenerator; the sampler selects structurally meaningful variants without enumerating every combination.

| root metric | BLK-006A | BLK-006B |
| --- | ---: | ---: |
| proposals generated | 2 | 12 |
| hard-valid candidates | 1 | 12 |
| hard rejected | 1 | 0 |
| structurally distinct valid | 1 | 12 |

BLK-006B root produced 567 raw aggregates, removed 493 equivalent generation paths, cheaply rejected 30 impossible proposals, formally evaluated 12 searchable proposals, and retained 12 hard-valid candidates. Every searchable candidate passed HardValidator, support/load propagation, compression, item/cluster/wall stability, collision, bounds, zone/handling, and cavity/bridge checks.

## Objective-driven valid competition

- Candidate A: `agg_SKU-05_0.500_0.000_0.000_6x4x4` (RESIDUAL_AWARE_WALL)
- Candidate A score: 13538.891904
- Candidate B: `agg_SKU-06_0.500_0.000_0.000_6x5x3` (ALTERNATE_HEIGHT_WALL)
- Candidate B score: 12974.002468
- Winner: `agg_SKU-05_0.500_0.000_0.000_6x4x4`
- Winning components: topfill_estimate, residual_quality, compactness, inventory_fit, fragmentation_penalty, unstable_geometry_penalty

Both candidates were hard-valid; ranking was decided by the explainable objective, not candidate ID or SKU-specific scoring.

## Search boundaries

Beam width remains limited to 1/2 verification and search depth remains 1. No Beam parameter tuning or multi-depth optimization was performed. `LEGACY_GREEDY` remains the production incumbent and `GLOBAL_SEARCH` remains opt-in.

## Regression

- deterministic candidate replay: PASS
- branch isolation: PASS
- TOP-001~012: PASS
- WALL-001~010: PASS
- BLK-005B: PASS
- BLK-005C: PASS
- BLK-006A: PASS
- Full suite: 152/152 PASS

## Stop condition

BLK-006B is complete. Multi-depth Beam Search and BLK-006C were not started.
