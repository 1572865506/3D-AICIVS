# BLK-008A Test Report

## Result

`PASS`

- new BLK-008A tests: 9/9 PASS
- full suite: 265/265 PASS
- full-suite runtime: 101.949 s
- existing BLK-007 tests: PASS
- existing tests modified to hide failures: no

## Required cases

- CARGO-001: SKU-02 → DISPLAY + HIGH fragility — PASS
- CARGO-002: display SIDE orientation rejected — PASS
- CARGO-003: SKU-02/SKU-14 top flat allowed; SKU-03 top flat rejected — PASS
- CARGO-004: excessive load over fragile display rejected — PASS
- CARGO-005: SKU-14 three top layers pass, fourth layer fails — PASS
- CARGO-006: canonical 14-SKU result does not regress BLK-007F-3 — PASS

Additional tests:

- actual Top Fill placements obey CILPE orientation policy — PASS
- LoadingResult contains all intelligence fields — PASS
- existing solver CargoProfile objects remain unchanged — PASS

## Real-case gates

| Gate | Result |
|---|---:|
| GlobalValidator | VALID |
| utilization | 71.3574% |
| overlap | 0 |
| penetration | 0.0 m³ |
| OOB | 0 |
| hard violations | 0 |
| enclosed cavity | 0 |
| sequence feasible | true |
| solver constraints mutated | false |
