# BLK-007C Frontend Contract

Base path: `/api/v1/loading/{job_id}`. Endpoints: `layout`, `container`, `cargo`, `walls`, `sequence`, `repair`, `scene`, `animation`, `camera`, `highlight?type=sku|wall|step|object&id=...`, and `export`.

## Coordinates

The backend is authoritative. Origin is the container back-bottom-left. X increases from back to the door plane (`x=L`), Y increases left-to-right, and Z increases floor-to-roof. Cargo `position` is its minimum corner. SceneObject `position` is its box center in the same axes. Dimensions and positions are meters; rotations are radians. Frontends must not mirror or swap axes.

## Playback

Consume `animation.frames` in ascending `step`. A `PLACE_GROUP` frame is atomic from the operator's perspective; its `movements` retain per-object paths. Repair groups are available in both `repair.groups` and the repaired target sequence step.

## Versioning

`version = BLK007C`. This product contract is frozen for BLK-007C; additive fields require a later version and existing fields may not change semantics. Solver search states, candidates, graph pointers, and beam internals are intentionally absent.
