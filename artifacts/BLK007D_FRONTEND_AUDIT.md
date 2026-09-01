# BLK-007D Frontend Audit

## Scope

Audit completed before implementation. Packing Solver V1, loading sequence, repair engine, BLK007C schemas, and the Three.js rendering core are treated as frozen dependencies.

## Current entry and call chain

- Frontend entry: `index.html` (single-page, non-bundled application; Three.js r128 loaded from CDN).
- User entry: `#btn-run-packing` calls `runSmartPackingAlgorithm(true)`.
- Automatic entry: `init()` calls `runSmartPackingAlgorithm(true)` after container and UI initialization.
- Container, manifest, strategy, gap, CoG, import, and quantity changes also call the same function.
- Current backend probe: `requestPackingFromBackend()` posts to hard-coded `/api/v2/pack` (or `http://localhost:8081/api/v2/pack` under `file:`).
- Current fallback: when the probe fails, `runSmartPackingAlgorithm()` constructs `IndustrialSmartContainerPacker` and calls `.pack(activeManifest)`.
- Current scene hand-off: `applyPackingSolution()` consumes legacy `placedBoxes`, converts canonical/legacy coordinates, creates Three.js meshes, and updates KPI/UI state.

```text
click / init / parameter change
  -> runSmartPackingAlgorithm
  -> requestPackingFromBackend (/api/v2/pack)
  -> on failure: IndustrialSmartContainerPacker.pack
  -> activePackingResult.placedBoxes
  -> applyPackingSolution
  -> Three.js cargoGroup
```

## Current calculation function

- Default orchestration: `window.runSmartPackingAlgorithm`.
- Local calculation implementation: `IndustrialSmartContainerPacker` in `index.html`.
- Backend transport: `requestPackingFromBackend` in `index.html`.
- Legacy coordinate bridge: `convertCanonicalToThree`.
- Scene commit: `applyPackingSolution`.
- Local animation: `window.startPackingAnimation`, which derives a drop path from each mesh's `originY` instead of consuming backend animation frames.

## Current data structures

- Input manifest uses `{sku,name,w,d,h,weight,quantity,requirement,color}`.
- Local/backend-v2 legacy result uses `placedBoxes`, `skuStats`, `utilization`, `usedVol`, `totalCount`, `totalWeightTons`, and `cog`.
- Cargo mesh metadata stores SKU, local display position, raw dimensions, and slicing bounds.
- BLK007C `LoadingResult` is already available through `/api/v1/loading/{job_id}/...`, but is not the current frontend source.

## Current Three.js data source

Three.js currently receives `activePackingResult.placedBoxes`. It does not consume `LoadingResult.scene.objects`, `animation.frames`, `camera`, `repair.groups`, or highlight data directly.

## Current fallback logic

The frontend catches backend errors, displays “后端算柜服务不可用，本次已降级为内置内核计算”, and runs the local packer. This is an automatic solver fallback and is the primary behavior that BLK-007D must remove. Local storage also contains legacy packing-result caches.

## Switch plan

- Default `BACKEND` mode: health check, create BLK007C job, fetch complete `LoadingResult`, validate schema, adapt scene/animation/camera, render.
- Explicit `MOCK` mode: only `?mode=mock`, loading `frontend/mock/demo_loading_result.json`.
- Backend failure: typed error and actionable offline UI; no local calculation.
- `IndustrialSmartContainerPacker`, old request helper, and local result cache remain deprecated compatibility code but are removed from the default call graph.
- Three.js mesh/material/container implementation remains in place; a BLK007C adapter supplies its authoritative object transforms and backend animation frames.
