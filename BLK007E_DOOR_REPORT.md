# BLK-007E-1 — Door Safety Constraint Engine Report

## Outcome

BLK-007E-1 implements a deterministic pre-packing Door Safety Constraint Engine under `src/constraints/door/`. It classifies declared door cargo, reserves a configurable door zone, forces short-edge-forward wall orientation, builds a continuous anchored wall plan, validates wall physics/continuity, and emits a solver hand-off constraint bundle.

```text
BLK007E_STATUS = PASS
DOOR_WALL_ENGINE_READY = true
NEXT_STAGE = BLK007E-2
```

BLK007E-1 does not mutate or replace the frozen Packing Solver. Production consumption/commit of the prepared wall is intentionally the BLK007E-2 boundary; this block proves the pre-packing engine and immutable hand-off contract.

## Architecture

The new layer contains:

- `DoorSafetyEngine`: orchestration, failure contract, immutable solver-input hand-off.
- `DoorZoneDetector`: configurable reservation and dual-coordinate representation.
- `CargoRiskClassifier`: geometry/policy risk classification without names or SKU-specific branches.
- `DoorOrientationRules`: `SHORT_EDGE_FORWARD` allow and `LONG_EDGE_FORWARD` deny.
- `DoorWallBuilder`: deterministic bounded wall layout.
- `DoorWallValidator` / `DoorWallStabilityValidator`: orientation, zone, continuity, support, neighbor contact, stack alignment, and anchor checks.
- `DoorSafetyScore`: explainable coverage/continuity/orientation/stability score with gap penalty.
- Typed `DoorZone`, `DoorWall`, `DoorConstraint`, and `DoorValidationResult` models.

No file in Packing Solver Core, Search, Beam Search, Candidate Generator, Top Fill, BLK007B Repair, BLK007C, or Three.js was modified by BLK007E-1.

## Coordinate semantics

The business definition uses distance from the door:

```text
Door-relative: startX=0.0, endX=1.2
```

The existing canonical solver uses `x=0` at the inner/rear wall and `x=Lx` at the doors. For 40HQ:

```text
Solver reserved range: [10.832, 12.032]
```

Both ranges are present in `DoorZone`, preventing a silent axis reversal.

## Cargo classification

Door eligibility requires an explicit existing door policy (`DOOR_SEAL` role or required Door zone), geometry capable of forming a wall, available inventory, and unit weight below the configured safety limit. Names and SKU ids are not used.

Current declared door candidates:

| SKU | Thin ratio | Thin | Door candidate | Forced concrete orientation |
|---|---:|---|---|---|
| SKU-02 | 0.225352 | yes | yes | UPRIGHT_ROTATED |
| SKU-03 | 0.385246 | no | yes | UPRIGHT_ROTATED |
| SKU-04 | 0.277273 | yes | yes | UPRIGHT_ROTATED |
| SKU-14 | 0.238095 | yes | yes | UPRIGHT_ROTATED |

SKU-03 is correctly not labelled thin at the configured `0.35` threshold, but remains an eligible declared door-wall carton. The engine does not falsify classification to match a product category.

## Current 14-SKU wall result

- Door zone: 1.2m, configurable.
- Selected inventory: SKU-02 × 28.
- Structure: 4 columns × 7 layers.
- Direction: `SHORT_EDGE_FORWARD` only (`dx=0.08m`, wall-face width `dy=0.553m`).
- Wall height: 2.485m.
- Door-face coverage: 0.866228.
- Gap count: 1.
- Maximum gap: 0.14m.
- Continuity score: 94.0476.
- Upper-layer support: 1.0.
- Neighbor-contact ratio: 1.0.
- Stack-alignment ratio: 1.0.
- Forbidden orientation count: 0.
- Door Safety Score: 91.97/100.

Thin cartons are not claimed to be independently safe: `individual_stable_ratio=0`. The plan explicitly requires the wall anchor, continuous neighbor support, and aligned layers; aggregate wall stability validates as LOW risk.

## Reservation and failure behavior

`getDoorConstraints()` returns the reserved absolute/door-relative zone, forced orientations, priority cargo, blocked ordinary-cargo range, and reserved inventory. When no safe wall can be proved it returns:

```json
{
  "status": "FAILED",
  "reason": "NO_VALID_DOOR_WALL",
  "detail": "explicit diagnostic"
}
```

There is no silent relaxation.

## Stage boundary

The immutable `PreparedPackingInput` is ready for BLK007E-2 to make the production orchestration commit/reserve the planned wall while preserving existing collision/support/compression/stability validators. BLK007E-1 stops here and does not enter BLK008.
