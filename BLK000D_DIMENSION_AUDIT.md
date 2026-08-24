# BLK-000D — Cargo Dimension Schema Normalization & Axis Mapping Audit

## Status

`BLK000D_STATUS = PASS`

`DIMENSION_SCHEMA_READY = true`

`OPTIMIZATION_RECALC_REQUIRED = true`

## Finding

The canonical 14-SKU manifest currently stores SKU-14 as `w=0.488, d=0.080, h=0.336`, so that source row is already in correct product-axis order. The defect was structural: the ingest adapter mapped `w/d/h` directly to `x/y/z`, and downstream optimizers read `sku.box.x/y/z` without an authoritative declaration that the first horizontal field was Length.

The new normalization layer makes the mapping explicit:

```json
{
  "dimensions": {
    "length": 0.488,
    "width": 0.080,
    "height": 0.336
  },
  "axisDefinition": {
    "lengthAxis": "X",
    "widthAxis": "Y",
    "heightAxis": "Z"
  },
  "thicknessAxis": "WIDTH"
}
```

If legacy input supplies SKU-14 as `80×488×336 mm`, the adapter emits `AXIS_SWAP_WARNING`, normalizes it to `488×80×336 mm`, and records `FIXED_AXIS_MAPPING` before constructing the canonical CargoSKU.

## Normalization rules

- Length: larger horizontal product dimension
- Width: secondary horizontal product dimension
- Height: declared standing vertical dimension
- Canonical placement mapping: `Length→X`, `Width→Y`, `Height→Z`
- Thickness: smallest dimension divided by largest dimension `<0.25`
- Display validation: standing height must exceed width; width must be thin relative to length

## 14-SKU audit

| SKU | Original L/W/H (m) | Normalized L/W/H (m) | Thickness | Status |
|---|---|---|---|---|
| SKU-01 | 0.500 / 0.500 / 0.500 | 0.500 / 0.500 / 0.500 | — | NORMALIZED |
| SKU-02 | 0.553 / 0.080 / 0.355 | 0.553 / 0.080 / 0.355 | WIDTH | NORMALIZED |
| SKU-03 | 0.978 / 0.188 / 0.488 | 0.978 / 0.188 / 0.488 | WIDTH | NORMALIZED |
| SKU-04 | 0.680 / 0.122 / 0.440 | 0.680 / 0.122 / 0.440 | WIDTH | NORMALIZED |
| SKU-05 | 0.833 / 0.530 / 0.230 | 0.833 / 0.530 / 0.230 | — | NORMALIZED, DISPLAY_GEOMETRY_WARNING |
| SKU-06 | 0.575 / 0.460 / 0.465 | 0.575 / 0.460 / 0.465 | — | NORMALIZED, DISPLAY_GEOMETRY_WARNING |
| SKU-07 | 0.431 / 0.422 / 0.281 | 0.431 / 0.422 / 0.281 | — | NORMALIZED, DISPLAY_GEOMETRY_WARNING |
| SKU-08 | 0.560 / 0.145 / 0.410 | 0.560 / 0.145 / 0.410 | — | NORMALIZED |
| SKU-09 | 0.495 / 0.145 / 0.410 | 0.495 / 0.145 / 0.410 | — | NORMALIZED |
| SKU-10 | 0.490 / 0.280 / 0.350 | 0.490 / 0.280 / 0.350 | — | NORMALIZED, DISPLAY_GEOMETRY_WARNING |
| SKU-11 | 0.480 / 0.310 / 0.340 | 0.480 / 0.310 / 0.340 | — | NORMALIZED |
| SKU-12 | 0.180 / 0.180 / 0.340 | 0.180 / 0.180 / 0.340 | — | NORMALIZED |
| SKU-13 | 0.430 / 0.410 / 0.190 | 0.430 / 0.410 / 0.190 | — | NORMALIZED |
| SKU-14 | 0.488 / 0.080 / 0.336 | **0.488 / 0.080 / 0.336** | **WIDTH** | **NORMALIZED** |

Display geometry warnings are audit findings, not automatic policy changes. They do not grant orientations or alter USER_DEFINED cargo rules.

## Migration

The following paths now consume `NormalizedDimension`:

- InputAdapter: normalizes every manifest row before creating `BoxDim`
- BLK-007F-4 OrientationOptimizer: records and passes normalized product dimensions into orientation simulation
- BLK-007F-5 LoadingDirectionEngine and TransportStabilityAnalyzer: use `length/width/height`, never ambiguous box XYZ
- BLK-007F-6 GlobalLayoutRebuildEngine: constructs a normalized dimension registry for every search run
- BLK-007F-7.5 CargoPoolExtractor and OrientationMutationSearch: output declared dimensions/axes and generate legal rotations from normalized dimensions
- Cargo intelligence and frontend projection: thickness/facing calculations use normalized dimensions

TCRS no longer emits ambiguous `size:[x,y,z]`. It emits product `dimensions`, `axisDefinition`, and separate `occupiedDimensions` whose axes are explicitly container axes.

## Regression evidence

- DIM-001 SKU normalization: PASS
- DIM-002 display thickness detection: PASS
- DIM-003 swapped-axis detection and repair: PASS
- DIM-004 complete 14-SKU audit: PASS
- Optimizer ambiguous-axis source audit: PASS
- SKU-14: L=488 mm, W=80 mm, H=336 mm: PASS
- Full regression suite: **306/306 PASS** in 146.935 seconds; all prior 301 tests remain passing

`OPTIMIZATION_RECALC_REQUIRED` remains true because BLK-007F optimization artifacts created before this schema did not carry authoritative axis metadata. The current canonical 14-SKU source happens to be correctly ordered, but external/legacy manifests and prior audit evidence must be rerun through BLK-000D before being treated as authoritative.

This stage stops after normalization and audit. No packing, collision, validation, Three.js, or BLK007C schema semantics were changed.
