# BLK-007F-8A — Door-open Stability & Mixed Cargo Wall Correction

## Status

`BLK007F8A_STATUS = PASS`

`DOOR_WALL_FORMATION_V2_READY = true`

`DOOR_OPEN_STABILITY_READY = true`

`MIXED_SKU_WALL_FORMATION_READY = true`

`NEXT_STAGE = BLK007F8B`

BLK-007F-8B has not been started.

## View-aware diagnosis

The supplied first screenshot is the container side view (X-Z), and the second is the axial view. The side view proved that the former door wall had only about `0.122m` of base depth while standing about `2.64m` high. It could be restrained by a closed door, but was not self-stable after the doors opened. The axial view showed genuine wall-transition gaps; SKU diversity is audited from backend wall membership rather than inferred from colors.

## Door-open hard gate

Canonical X runs from the rear toward the doors. Door cargo is now checked in two distinct states:

- Doors closed: `+X/-X`, lateral, vertical, door restraint, and main-wall rear anchoring remain mandatory.
- Doors open: every door column must remain self-stable without using the door leaf as support.

The conservative open-door perturbation is `0.15g`. A column is accepted only when:

`base_depth / (0.15 * stack_height) >= 1.0`

The former shallow SKU-04 example gives approximately `0.308` and is hard rejected with `DOOR_OPEN_UNRESTRAINED_TIPPING_RISK`. The selected corrected columns have minimum margin `1.2103`.

## Corrected 14-SKU door wall

- Anchor X: `11.429m`
- Door plane: `12.032m`
- Maximum door clearance: `0.115m`
- Door orientation: `LONG_EDGE_FORWARD`, concrete `UPRIGHT_NORMAL`
- SKU mix: `SKU-02 × 7`, `SKU-14 × 224`
- Total placements: `231`
- Width coverage: `98.6395%`
- Height coverage: `99.6294%`
- Y-Z area coverage: `98.0179%`
- Largest lateral gap: `0.032m`
- Door-open minimum tipping margin: `1.2103`
- Actual rear anchor coverage: `86.43%`

This differs deliberately from MAIN display-wall semantics. MAIN display walls retain thin-edge-forward orientation; the door wall uses a deeper base because it must remain standing after the doors open.

## Mixed-SKU cargo-wall formation

The former homogeneous-only WallBuilder now performs deterministic bounded mixed-column composition. It groups policy-legal columns by compatible depth, aligns total column height before rewarding SKU diversity, consumes exact tail inventory, and validates the wall through the existing hard validator. Continuity is measured over the actual Y-Z wall surface.

14-SKU structural result before residual/rebuild stages:

- Cargo walls: `15`
- Cargo-wall placements: `480`
- Multi-SKU walls: `10`
- Diversity: `1 SKU: 5`, `2 SKU: 6`, `3 SKU: 2`, `4 SKU: 1`, `5 SKU: 1`
- Placement-weighted continuity: `82.1692`
- Global physical validation: `VALID`

## Exact Top Fill support correction

Mixed walls expose stepped top surfaces. Top Fill now checks contact against actual cartons at the candidate Z plane rather than trusting only a coarse region envelope. Unsupported candidates are rejected as `INSUFFICIENT_EXACT_TOP_SUPPORT`; final GlobalValidator remains mandatory.

## Full-pipeline result

- Placements: `1597`
- Utilization: `75.703747%`
- Top Fill placements: `52`
- Collision/overlap/OOB/hard violations: `0`
- Door wall membership/geometry: locked
- Door-open stability: `PASS`
- GlobalValidator: `VALID`

The prior `78.7869%` layout is not retained because it contained door-open instability and coarse-region Top Fill placements that fail exact support. Residual-space recovery is intentionally deferred to BLK-007F-8B; safety gates were not relaxed.
