# BLK-007F-7.6 Test Report

## Focused tests

Command: `python3 -m unittest tests.test_blk007f76_dimension_corrected_rebuild -v`

Result: **6/6 PASS** in 12.716 seconds.

| Verification | Result |
|---|---|
| SKU-14 = 488×80×336 mm | PASS |
| 80 mm short thickness faces container depth | PASS |
| Display wall regenerated and continuous | PASS — 100% |
| Fresh coordinates generated without loading F7.5 | PASS |
| Layer regenerated after TCRS | PASS — 3 placements |
| Top Fill regenerated after TCRS | PASS — 129 placements |
| Door-adjacent/first-layer stability | PASS |
| GlobalValidator | VALID |

## Full regression

Command: `python3 -m unittest discover -s tests -v`

Result: **312/312 PASS** in 161.916 seconds. All previous 306 tests remain passing; the six BLK-007F-7.6 tests are additive.

## Hard gates

| Gate | Result |
|---|---:|
| overlap | 0 |
| penetration | 0 |
| out_of_bounds | 0 |
| hard_constraint_violations | 0 |
| placement_count | 1462 |
| utilization | 71.5044% |

`BLK007F76_STATUS = PASS`

`DIMENSION_CORRECTED_LAYOUT_READY = true`

`NEXT_STAGE = BLK007F8`
