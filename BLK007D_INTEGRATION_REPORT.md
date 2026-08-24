# BLK-007D Integration Report

## Integration outcome

The production frontend path is now:

```text
user/init/parameter change
  -> BLK007D Backend Client
  -> POST /api/v1/loading/jobs
  -> GET /api/v1/loading/{job_id}
  -> validate BLK007C LoadingResult
  -> scene / animation / camera adapters
  -> existing Three.js renderer
```

There is no automatic Backend-to-local-solver fallback.

## Rendering data ownership

- Cargo identity, position, size, rotation, color, step, and wall come from `scene.objects` plus matching `cargo` metadata.
- The adapter only maps the canonical BLK007C axes into the frozen renderer coordinate frame; it does not pack or reposition cargo.
- Loading playback consumes `animation.frames`, including backend `from`, `to`, `movements`, and `duration`.
- `PLACE` and `PLACE_GROUP` are supported; repair groups are surfaced as anti-tip group messages and object metadata.
- Camera position, target, and zoom come from `camera`.
- Object selection requests the BLK007C highlight endpoint and displays SKU, canonical position, layer, wall, loading step, and repair group.

## Deprecated local code

`IndustrialSmartContainerPacker` remains in the monolithic historical source and is explicitly marked deprecated. There is no constructor invocation in the default orchestration function or Mock Mode. The old `/api/v2/pack` request/fallback helper was removed.

## Acceptance answers

1. **前端是否完全切换 Backend Mode？** 是。默认模式只创建并读取后端 Loading Job。
2. **是否还存在 Local Solver 调用？** 默认和 Mock 调用链均不存在；只保留未引用的 deprecated 类定义。
3. **Three.js 是否完全由 LoadingResult 驱动？** 是。Backend/Mock 模式的货物几何、动画、相机和业务元数据均来自 LoadingResult。
4. **Backend Offline 是否正确提示？** 是。显示离线状态、清空 KPI，并提示检查服务、API 配置和网络；不降级求解。
5. **Mock Mode 是否保留？** 是，仅 `?mode=mock` 可启用。
6. **BLK007C Contract 是否完全兼容？** 是，版本和必需字段均强制校验，现有子资源未改变。
7. **是否可以进入 BLK008？** 可以；BLK-007D 验收与回归均通过，但本次未开始 BLK008。

## Final status

```text
BLK007D_STATUS = PASS
BACKEND_RENDERING_READY = true
NEXT_STAGE = BLK008
```
