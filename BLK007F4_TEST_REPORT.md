# BLK-007F-4 Test Report

Status: **PASS**

## Specialized acceptance tests

| Test | Result | Evidence |
|---|---:|---|
| LAYER-001 Layer analysis | PASS | Six 0.5 m bands, with final roof band 2.5–2.698 m |
| LAYER-002 Layer discontinuity repair | PASS | Layer 0 occupancy 0.874317 → 0.881148 |
| LAYER-003 Dynamic orientation | PASS | SKU-14 selects the highest-scoring legal orientation by context |
| LAYER-004 Display top orientation | PASS | MAIN=VERTICAL; eligible TOP_FILL=FLAT_HORIZONTAL |
| LAYER-005 Door seal | PASS | Longitudinal seal coverage 99.75%, frozen Door Wall unchanged |
| LAYER-006 Wall bridge safety | PASS | support <0.8 and compression failures are rejected |
| LAYER-007 14-SKU benchmark | PASS | 71.5044%, GlobalValidator VALID |
| LoadingResult metadata | PASS | `layer_id`, `orientation_used`, `optimization_reason`, `structural_role` present |

## Full regression

- Command: `python3 -m unittest discover -s tests -v`
- Result: **273 / 273 PASS**
- Runtime: **99.232 s**
- Previous suite: 265 tests; 8 new LOOE tests added.

## Physical gates

| Gate | Result |
|---|---:|
| overlap pairs | 0 |
| penetration volume | 0.0 m³ |
| OOB | 0 |
| hard/constraint violations | 0 |
| stability violations | 0 |
| enclosed cavities | 0 |
| quantity violations | 0 |
| GlobalValidator | VALID |
| Door Wall fingerprint | unchanged |
| Cargo/Transition Wall fingerprint | unchanged |
| MAIN_BODY flat added by LOOE | 0 |

No existing test was modified to turn a failure into a pass.
