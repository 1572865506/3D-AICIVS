# BLK-007F-5 Test Report

Status: **PASS**

## Direction tests

| Test | Result | Evidence |
|---|---:|---|
| DIRECTION-001 Display facing | PASS | SKU-02/03/04/14 prefer SHORT_EDGE_FORWARD |
| DIRECTION-002 Display wall continuity | PASS | 856/856 non-top Display placements use SHORT_EDGE_FORWARD |
| DIRECTION-003 Door direction | PASS | Display/fragile LONG_EDGE_FORWARD rejected; 28 anchors remain valid |
| DIRECTION-004 Transport risk | PASS | SKU-02 short-edge score 80.6908 > long-edge 62.7288 |
| DIRECTION-005 14-SKU benchmark | PASS | 71.5044%, unchanged from BLK007F4, GlobalValidator VALID |
| LoadingResult projection | PASS | `facing`, `direction_reason`, `transport_score`, `wall_score` present |

## Full regression

- Command: `python3 -m unittest discover -s tests -v`
- Result: **279 / 279 PASS**
- Runtime: **104.913 s**
- Added tests: 6

## Safety and compatibility

- overlap pairs: 0
- penetration: 0
- OOB: 0
- constraint/stability violations: 0
- enclosed cavities: 0
- MAIN_BODY flat introduced by LDSE: 0
- Door/Cargo/Transition/Layer placement geometry: unchanged
- BLK007B/BLK007C schema compatibility: PASS
- final GlobalValidator: VALID

No existing test was weakened or modified to conceal a failure.
