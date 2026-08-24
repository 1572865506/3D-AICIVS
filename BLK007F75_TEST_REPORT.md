# BLK-007F-7.5 Test Report

## Focused TCRS tests

Command: `python3 -m unittest tests.test_blk007f75_cargo_recomposition -v`

Result: **8/8 PASS** in 22.762 seconds.

| Test | Result |
|---|---|
| TCRS-001 all wall cargo extracted into independent pool | PASS |
| TCRS-002 real coordinate recomposition >=30% | PASS — 98.0848% |
| TCRS-003 continuous same-direction Display Wall | PASS — 100% / 100% |
| TCRS-004 stable locked Door first layer | PASS |
| TCRS-005 14-SKU structure score and physical validation | PASS |
| Bounded 10-candidate hard-valid search | PASS |
| At most six policy-legal rotation candidates | PASS |
| BLK007C LoadingResult audit projection | PASS |

## Full regression

Command: `python3 -m unittest discover -s tests -v`

Result: **301/301 PASS** in 148.187 seconds. The prior 293 tests remain passing; eight TCRS tests are additive.

## Hard gates

| Gate | Result |
|---|---:|
| GlobalValidator | VALID |
| overlap | 0 |
| penetration | 0 |
| out_of_bounds | 0 |
| hard_constraint_violations | 0 |
| locked Door Wall changed | 0 |
| display continuity | 100% |
| same display orientation | 100% |
| BLK007C schema version | unchanged (`BLK007C`) |

`BLK007F75_STATUS = PASS`

`TRUE_RECOMPOSITION_READY = true`

`VISIBLE_LAYOUT_CHANGE = true`

`NEXT_STAGE = BLK007F8`
