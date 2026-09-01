# BLK-007F-7.7 — Frontend Dimension Display Schema Fix

## Result

`BLK007F77_STATUS = PASS`

Product dimensions and scene occupied dimensions are now separate throughout the BLK007C backend/frontend boundary. No solver, placement, orientation, collision, validation, or layout-generation code was changed.

Repository state used for verification:

- Branch: `feature/v2-cleanroom-solver`
- Base commit: `05586dbe1e56a490b2dd761ce4c792c6cef2f66e`

## Root cause

The backend already exposed normalized product dimensions under the generic `dimensions` key and placed AABB dimensions under `size`. The backend Three.js scene correctly converted `size` into `scene.objects[].scale`, but the frontend detail path copied `scene.objects[].scale` into a generic `mesh.userData.dimensions` value. The detail tooltip then rendered that value as product specifications.

For a rotated SKU-14 placement this produced the incorrect UI value `80 × 488 × 336 mm`, even though the normalized product definition remained `488 × 80 × 336 mm`.

## API DTO

Every cargo item now exposes explicit fields:

```json
{
  "productDimensions": {
    "length": 0.488,
    "width": 0.080,
    "height": 0.336
  },
  "occupiedDimensions": {
    "width": 0.080,
    "depth": 0.488,
    "height": 0.336
  },
  "axisDefinition": {
    "lengthAxis": "X",
    "widthAxis": "Y",
    "heightAxis": "Z"
  }
}
```

The BLK007C `size` and `dimensions` aliases remain present for backward compatibility. New consumers are schema-validated against the explicit fields. Scene generation reads `occupiedDimensions` and uses legacy `size` only as a compatibility fallback.

## Frontend behavior

- The SKU detail card displays `productDimensions` under `规格尺寸(长×宽×高)`.
- A separate `占用空间` row displays `occupiedDimensions`.
- Cargo export projection uses product length/width/height for product specification columns and explicitly named occupied-space columns for the placement AABB.
- Three.js mesh scale continues to come exclusively from authoritative `LoadingResult.scene.objects[].scale`.
- Collision, bounding-box, position, and placement visualization inputs remain occupied-space data.

## SKU-14 regression evidence

| Consumer | Value | Result |
|---|---:|---|
| Product detail — 长 | 488 mm | PASS |
| Product detail — 宽 | 80 mm | PASS |
| Product detail — 高 | 336 mm | PASS |
| Renderer occupied AABB | 80 × 488 × 336 mm | PASS |
| Product and occupied schemas coexist | Yes | PASS |
| Scene scale unchanged | `[0.080, 0.488, 0.336]` | PASS |

## Files changed

- `backend/api/adapters/layout_adapter.py`
- `backend/api/adapters/scene_adapter.py`
- `backend/api/schemas/cargo_schema.py`
- `frontend/src/api/types/Cargo.ts`
- `frontend/src/adapters/loadingResultAdapter.ts`
- `frontend/src/backendSwitch.js`
- `frontend/mock/demo_loading_result.json`
- `frontend/tests/backendSwitch.test.cjs`
- `index.html`
- `tests/test_blk007f77_frontend_dimension_schema.py`

## Verification

- BLK-007F-7.7 targeted Python/API tests: `11/11 PASS` (including BLK007C compatibility tests)
- Frontend Node tests: `8/8 PASS`
- Full Python regression suite: `316/316 PASS`
- Total executed regression checks: `324 PASS`, `0 FAIL`
- Backend health after restart: `status = ok`, service version `2.0.0`, port `8091`

No layout was regenerated for this change. The SKU-14 regression uses an isolated DTO/scene fixture with normalized physical dimensions and a rotated occupied AABB.

## Acceptance

- Backend normalized data unchanged: **PASS**
- Frontend displays product dimensions: **PASS**
- Renderer still uses occupied AABB: **PASS**
- Product/scene labels are distinct: **PASS**
- Export dimension projection uses product dimensions: **PASS**
- No solver modification: **PASS**
- No layout regeneration: **PASS**

`FRONTEND_PRODUCT_DIMENSION_READY = true`

