# BLK-007F-6 Test Report

Status: **PASS**

## Specialized tests

| Test | Result | Evidence |
|---|---:|---|
| Rebuild controller | PASS | Default NORMAL; explicit REBUILD activates GLRS |
| Multiple layouts | PASS | Five structurally distinct complete candidates generated |
| DISPLAY-WALL-001 | PASS | Every non-top Display placement remains SHORT_EDGE_FORWARD |
| DISPLAY-WALL-002 | PASS | 448 SKU-02 placements receive changed X positions in selected rebuild |
| GLOBAL-LAYER-001 | PASS | Layer balance 98.4163 → 98.5423 |
| Door rebuild | PASS | Door Wall re-instantiated and fully revalidated; 28 anchors remain safe |
| 14-SKU rebuild | PASS | candidate_04 COMPLETE_LEGAL, utilization 71.5044% |

## Candidate validation

All five candidates passed the complete `IndependentGlobalValidator`. Invalid or incomplete candidates cannot be selected by `GlobalPlacementSearch`.

## Full regression

- Command: `python3 -m unittest discover -s tests -v`
- Result: **286 / 286 PASS**
- Runtime: **110.960 s**
- New GLRS tests: 7

## Safety gates

- overlap pairs: 0
- penetration volume: 0.0 m³
- OOB: 0
- hard/constraint violations: 0
- stability violations: 0
- enclosed cavities: 0
- MAIN_BODY flat introduced: 0
- final GlobalValidator: **VALID**

No existing test was weakened or changed to hide a regression.
