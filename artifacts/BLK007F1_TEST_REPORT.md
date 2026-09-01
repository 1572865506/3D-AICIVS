# BLK-007F-1 Test Report

## Result

`PASS`

- new BLK-007F-1 tests: 8/8 PASS
- full suite: 241/241 PASS
- full-suite runtime: 74.940 s
- previous floor: 233 tests
- existing tests modified to hide failures: no

## Required benchmark cases

- WALL-001 continuous wall, exact-width layer, gap=0 — PASS
- WALL-002 thin cargo wall, isolated cargo=0 — PASS
- WALL-003 declared display profiles form upright continuous walls — PASS
- WALL-004 bounded internal void is detected and classified — PASS
- WALL-005 canonical 14-SKU result contains both Door Wall and Cargo Walls — PASS

Additional coverage:

- logical wall regions cover the main space without overlap — PASS
- generated wall passes WallConstraintFilter — PASS
- BLK007C adapter emits `role=CARGO_WALL` — PASS

## Real-case gates

| Gate | Result |
|---|---:|
| GlobalValidator | VALID |
| overlap | 0 |
| penetration | 0.0 m³ |
| OOB | 0 |
| hard violations | 0 |
| enclosed cavity | 0 |
| isolated cargo in planned walls | 0 |
| weak wall support area | 0 |
| ordinary cargo in door zone | 0 |
| LoadingSequence feasible | true |
