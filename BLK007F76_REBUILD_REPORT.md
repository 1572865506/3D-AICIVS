# BLK-007F-7.6 — Dimension Corrected Global Recomposition Rebuild

## Status

`BLK007F76_STATUS = PASS`

`DIMENSION_CORRECTED_LAYOUT_READY = true`

`NEXT_STAGE = BLK007F8`

## Authoritative pipeline

The layout was rebuilt from the normalized 14-SKU manifest. No BLK-007F-7.5 placement JSON, wall membership, or orientation decision was loaded by the solver.

`BLK000D normalization → Cargo Intelligence → Direction Strategy → fresh Main/Wall layout → GLRS → TCRS → refreshed wall geometry → Layer Optimization → Top Fill → WIRE → GlobalValidator`

BLK-007F-7.6 uses the new opt-in `with_dimension_corrected_rebuild()` path. In this path GLRS and TCRS receive the newly generated main layout before any Layer or Top Fill placement exists. After recomposition, wall objects are rebound to the new placement geometry; Layer and Top Fill are then regenerated.

## SKU-14 verification

| Property | Corrected result |
|---|---:|
| Product length | 0.488 m |
| Product width/thickness | 0.080 m |
| Standing height | 0.336 m |
| Thickness axis | WIDTH |
| Axis mapping | Length→X, Width→Y, Height→Z |
| Selected facing | SHORT_EDGE_FORWARD |
| Forward depth | 0.080 m |
| Wall-face width | 0.488 m |
| Orientation | UPRIGHT_ROTATED |
| SKU-14 transport score | 79.5410 |

The old frontend projection exposed only occupied scene size `w=.080, d=.488, h=.336`. That is a valid rotated AABB, but it was ambiguous and could be misread as product L/W/H. The corrected result separately exposes:

- product dimensions: `length=.488, width=.080, height=.336`
- product axis definition
- occupied Three.js size: `.080 × .488 × .336`

This proves the display is loaded with its 80 mm thickness along container depth and its 488 mm face forming the wall—not as a false 488 mm deep wide-side load.

## Regeneration result

- Fresh GLRS candidate: `candidate_04`
- Fresh TCRS candidate: `candidate_08`
- TCRS main-layout placements relocated during its own search: 1302
- Layer completion regenerated after TCRS: 3 placements
- Top Fill regenerated after TCRS: 129 placements, 1.69215 m³
- Display MAIN placements: 856
- Display continuity: 100%
- Display same-orientation ratio: 100%
- Door first-layer short-edge ratio: 100%
- Door stability: PASS
- WIRE validation: PASS

Comparison against the previous artifact uses common placement IDs only: 126 of 1461 common IDs have different final coordinates (8.6242%). The remaining deterministic coordinates coincide because the canonical manifest already contained the correct SKU-14 dimensions. Coordinate equality is not reuse: the new TCRS input contains neither the old Layer nor old Top Fill placements, and all six requested structures were regenerated.

## BLK-007F-7.5 comparison

| Metric | BLK-007F-7.5 | BLK-007F-7.6 corrected |
|---|---:|---:|
| Wall continuity | 88.0000 | 88.0000 |
| Display continuity | 100% | 100% |
| Display same orientation | 100% | 100% |
| Door stability | PASS | PASS |
| Layer balance | 99.6610 | 99.6610 |
| Utilization | 71.5044% | 71.5044% |
| Overall transport score | 92.0000 | 92.0000 |

The numerical result is unchanged because the canonical source axes were already ordered correctly. BLK-007F-7.6 is nevertheless the first authoritative result: its product dimensions and occupied scene axes are explicitly separated, and Layer/Top Fill are proven to run after the corrected recomposition.

## Physical gates

- Placements: 1462
- Utilization: 71.5044%
- Overlap: 0
- Penetration: 0
- Out of bounds: 0
- Hard constraint violations: 0
- GlobalValidator: VALID

Packing Solver Core, collision semantics, GlobalValidator, Door Safety, Three.js, and BLK007C schema were not modified.

This stage stops here and does not enter BLK-007F-8.
