# BLK-005B — Default Policy Calibration & Safe TopFill Admission

## Outcome

Default Top Fill policy now has explicit ALLOW / DENY / AUTO semantics. DEFAULT/AUTO is not permission: it admits only an orientation already declared by OrientationPolicy and every committed placement still passes the existing hard, support/load, stability, collision, bounds, zone, and cavity gates. Search Objective, Beam Search, and Local Search were not changed.

## Admission result

| metric | BALANCED | OPTIMIZE |
| --- | ---: | ---: |
| policy pass rate before | 2.30% | 2.12% |
| policy pass rate after | 88.01% | 87.83% |
| policy compatible | 345 | 332 |
| safe admitted | 160 | 167 |
| AUTO pass | 154 | 162 |
| AUTO rejected | 182 | 162 |
| actual AUTO Top Fill placements | 12 | 16 |
| AUTO flat placements | 0 | 0 |

At least one formerly default-disabled SKU was admitted and placed in both modes. AUTO rejections also occur, proving it is not unconditional. Full per-Region×SKU gate results and rejection codes are in `BLK005B_ADMISSION_DIAGNOSTIC.json`.

## User-rule precedence

- SKU-02 minBaseHeight remains 2.5m.
- SKU-14 minBaseHeight remains 1.3m.
- Their conditional orientation and max-layer rules are byte-for-byte equivalent at the normalized policy level: true.
- AUTO SKUs inherit only their declared UPRIGHT orientations; AUTO flat placement count is zero.

## Safety regression

| gate | BALANCED | OPTIMIZE |
| --- | ---: | ---: |
| overlap | 0 | 0 |
| penetration | 0.0 | 0.0 |
| OOB | 0 | 0 |
| hard violations | 0 | 0 |
| enclosed cavity | 0 | 0 |
| bridge void | 0 | 0 |
| door_ready | true | true |
| MAIN_BODY conditional-flat | 0 | 0 |

- TOP-001~012: PASS
- WALL-001~010: PASS
- full suite: 143/143 PASS

## Stop condition

BLK-005B is complete. No Search Optimization or next BLK was started.
