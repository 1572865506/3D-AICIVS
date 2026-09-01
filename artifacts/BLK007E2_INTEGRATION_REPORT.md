# BLK-007E-2 — Door Wall Solver Integration Report

## Status

`BLK007E2_STATUS = PASS`

`DOOR_WALL_INTEGRATED = true`

`FINAL_LAYOUT_DOOR_SAFE = true`

`NEXT_STAGE = BLK007F`

Implementation stopped at BLK-007E-2. BLK-008 was not started.

## Integration result

The BLK-007E-1 plan is now consumed before the frozen packing solver. The integration envelope reserves 28 SKU-02 units, converts `DOOR_WALL_001` into authoritative `Placement` objects, restricts the unchanged main solver to x=0–10.832 m, and commits the door anchors plus main-solver output into the original 40HQ `WorldState`. The merged solution always runs the full `IndependentGlobalValidator`.

Solver-state order:

1. Create original container state.
2. Inject and commit the door wall.
3. freeze all door placement IDs as `LOCKED_DOOR_WALL`.
4. reserve x=10.832–12.032 m.
5. run the unchanged solver in the non-reserved main area.
6. merge placements and run the complete GlobalValidator.

No packing/search/candidate/collision/compression/repair/Three.js core algorithm was changed. The server only wraps `HierarchicalSearchSolver` with the new pre/commit integration layer.

## Real 14-SKU result

| Metric | Result |
|---|---:|
| Final placements | 265 |
| Door-wall placements | 28 |
| Door-wall SKU | SKU-02 |
| Door-wall orientation policy | SHORT_EDGE_FORWARD |
| Concrete orientation | UPRIGHT_ROTATED |
| Door range | 10.832–12.032 m |
| Door state | LOCKED_DOOR_WALL |
| Door-wall safety score | 91.97 |
| Ordinary placements in reserved range | 0 |
| Utilization (FAST verification run) | 31.8190% |
| GlobalValidator | VALID |
| Sequence feasible | true |

The utilization run is a bounded FAST integration verification, not a replacement for the accepted production incumbent and not a search-quality benchmark.

## Safety result

- overlap pairs: 0
- penetration volume: 0
- out of bounds: 0
- hard rejection reasons: 0
- enclosed cavity count: 0
- ordinary cargo crossing x=10.832: 0
- door orientation valid: true
- door-zone reservation active: true
- full final validation: PASS

Top Fill uses the cropped main-solver container, so it cannot create candidates over or inside the locked door zone. The adapter records `DOOR_WALL_SUPPORT` contacts as non-pushable metadata; the normal exact physics and final validator remain authoritative.

## Loading sequence semantics

There are two different orders and they must not be conflated:

- Solver commit order: door wall first, so packing and validation always see the reserved anchor.
- Physical loading order: main cargo first, door wall build last, preserving BLK-007A's door-access and `DOOR_SEAL_LAST` safety rule.

The real plan is feasible and contains all 28 door-wall placements in the `DOOR_SEAL` build phase (grouped into physical steps 226–239). Loading a complete wall as physical steps 1–28 would close the only insertion aperture before main cargo is loaded; that literal ordering was therefore not introduced.

## Required answers

1. **Door Wall 是否真正进入最终 Layout？** 是。28 个 `door_pre_SKU-02_*` placement 位于 authoritative final placement list。
2. **Packing Solver 是否绕开 Door Zone？** 是。主求解空间截止于 x=10.832 m；另外有 `DOOR_ZONE_RESERVED` 预过滤。
3. **普通货物是否无法覆盖门墙区域？** 是。真实结果计数为 0，越界候选返回 `DOOR_ZONE_RESERVED`。
4. **最终 3D 显示是否来自新的 Layout？** 是。服务已重启，BLK007C cargo 输出新增兼容字段 `role=DOOR_WALL`，scene 仍由同一 LoadingResult 派生。
5. **Loading Sequence 是否包含 Door Wall Build？** 是。28 件全部存在于可执行的 `DOOR_SEAL` 构建阶段；实体顺序在主货之后。
6. **是否保持 BLK007B/007C 兼容？** 是。Repair 未修改；API 只增加 cargo.role，没有删除或重命名既有字段。
7. **真实 14 SKU 案例是否改善？** 门区安全从后验检查升级为求解前强制预留、锁定门墙和零普通货侵入；利用率不是本 BLK 的优化目标。

## Service

The updated service is running on port 8091. `/api/v1/loading/health` returns `status=ok`.
