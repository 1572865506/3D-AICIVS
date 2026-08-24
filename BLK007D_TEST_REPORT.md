# BLK-007D Test Report

## Automated tests

- Node frontend tests: **7/7 PASS**.
- Python BLK007D tests: **7/7 PASS**.
- Full Python regression suite: **213/213 PASS** in 86.273s.
- `git diff --check`: **PASS**.
- Browser runtime syntax check: **PASS**.

FEAPI coverage:

- FEAPI-001 health check: PASS.
- FEAPI-002 loading fetch: PASS.
- FEAPI-003 schema validation/version rejection: PASS.
- FEAPI-004 network error normalization: PASS.
- FEAPI-005 missing job 404: PASS.

Integration assertions preserve cargo count, object identity, position, size, rotation, animation movements, and sequence-to-scene references.

## Real browser smoke

| Scenario | Evidence | Result |
|---|---|---|
| Default Backend Mode | Online badge, BLK007C job/result, WebGL canvas, 187 backend cargo objects, 27.43% backend metric | PASS |
| Mock Mode | Exact `?mode=mock`, WebGL canvas, 2 mock cargo objects, purple mode badge | PASS |
| Backend Offline | Red offline badge, three diagnostic actions, KPI cleared, no fallback text | PASS |
| Removed legacy UI | Exact “前端计算” count = 0; “降级为内置内核” count = 0 | PASS |

The browser smoke used the real local HTTP server and did not replace the Three.js renderer with a test renderer.

## Regression and frozen components

Packing Solver, loading-sequence logic, repair-engine logic, BLK007C schemas, and Three.js rendering core were not weakened or replaced. Existing tests were not changed to convert a failure into a pass.

```text
BLK007D_STATUS = PASS
BACKEND_RENDERING_READY = true
NEXT_STAGE = BLK008
```
