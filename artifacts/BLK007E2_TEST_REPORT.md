# BLK-007E-2 Test Report

## Result

`PASS`

- focused BLK-007E-1 + E-2 tests: 20/20 PASS
- new BLK-007E-2 tests: 12/12 PASS
- full suite: 233/233 PASS
- full-suite runtime: 74.043 s
- required minimum: >=230 PASS

## DOOR-INTEGRATION coverage

- DOOR-INTEGRATION-001: planned door placement IDs exactly enter final Layout — PASS
- DOOR-INTEGRATION-002: ordinary cargo in x=10.832–12.032 is rejected with `DOOR_ZONE_RESERVED` — PASS
- DOOR-INTEGRATION-003: policy remains `SHORT_EDGE_FORWARD`; long-edge admission remains zero — PASS
- DOOR-INTEGRATION-004: canonical 14-SKU input creates 28 locked SKU-02 door placements — PASS
- inventory reservation is immutable and subtracts exactly 28 units — PASS
- locked placement move/rotate/replace rejection — PASS
- pre-collision DoorConstraintFilter — PASS
- final GlobalValidator mandatory and valid — PASS
- LoadingSequence includes every door-wall placement — PASS
- BLK007C additive `cargo.role` compatibility — PASS
- Top Fill admission into reserved zone rejected — PASS
- solver main-container boundary is exactly 10.832 m — PASS

## Real-case regression

| Gate | Result |
|---|---:|
| overlap | 0 |
| penetration | 0.0 m³ |
| OOB | 0 |
| hard violations | 0 |
| enclosed cavity | 0 |
| ordinary cargo in door zone | 0 |
| door_ready / wall committed | true |
| sequence feasible | true |
| GlobalValidator | VALID |

Existing tests were not changed or weakened to obtain this result.
