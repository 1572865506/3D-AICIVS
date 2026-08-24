# BLK-007F-2 Test Report

## Result

`PASS`

- new WALL-OPT tests: 7/7 PASS
- BLK-007F-1 + BLK-007F-2 focused tests: 15/15 PASS
- full suite: 248/248 PASS
- full-suite runtime: 77.502 s
- previous suite floor: 241 tests
- existing tests modified to hide failures: no

## Required cases

- WALL-OPT-001: wall end advances beyond 7.227 m — PASS (10.829 m)
- WALL-OPT-002: Cargo → Transition → Door WallChain is valid — PASS
- WALL-OPT-003: adjacent wall merge reduces fragmentation — PASS (51 → 16)
- WALL-OPT-004: lateral imbalance is detected and scored — PASS
- WALL-OPT-005: canonical 14-SKU utilization exceeds BLK-007F-1 — PASS (69.1412%)

Additional cases:

- transition covers more than 99% of the available longitudinal interval — PASS
- transition inventory is reserved before residual solver execution — PASS

## Real-case regression gates

| Gate | Result |
|---|---:|
| GlobalValidator | VALID |
| overlap pairs | 0 |
| penetration volume | 0.0 m³ |
| OOB | 0 |
| hard violations | 0 |
| enclosed cavity | 0 |
| ordinary cargo in reserved door zone | 0 |
| WallChain broken points | 0 |
| WallChain weak links | 0 |
| LoadingSequence feasible | true |
| Door Wall locked count | 28 |
