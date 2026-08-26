# BLK-007F-7.8 — Physical Package Label Orientation Rendering

## 状态

`BLK007F78_STATUS = PASS`

`PHYSICAL_LABEL_ORIENTATION_READY = true`

`SHARED_TEXTURE_ISOLATION = PASS`

`ORIENTATION_CACHE_READY = true`

## 修复结果

原渲染器把标签固定分配给 Three.js 世界坐标的前后面，后端虽然输出具体
Orientation，标签和 `THIS SIDE UP` 箭头却不会跟随产品原始六面变化。

新实现保持后端 occupied AABB、position 和 mesh rotation 不变，只使用六个共享单位
BoxGeometry 变体重排六面的 `materialIndex` 和 UV：

- `UPRIGHT_ROTATED`：标签面随产品绕竖直轴转到新的实际侧面。
- `FLAT_XZ / FLAT_ZX`：产品原始向上轴变为水平轴，贴图箭头不再伪装朝上。
- `SIDE_YZ / SIDE_ZY`：标签、顶面胶带和箭头共同随侧翻改变。
- Orientation 缺失的旧数据保守回退为 `UPRIGHT_NORMAL`。

基础 CanvasTexture 以 SKU 为键创建一次且不可变。方向变化只选择共享 Geometry/UV
变体和轻量材质引用数组，禁止修改 `Texture.rotation`，所以同 SKU 中单箱改变方向
不会影响其他箱子。

## 双显示模式

- `PHYSICAL`（默认）：显示真实包装六面和真实箭头方向。
- `ASSIST`：保留真实贴图，额外用一批 `LineSegments` 绘制产品原始向上轴。所有箱子
  共用一个辅助绘制批次，只增加一个 draw call。

## 几何与接口保持

- Solver、Orientation Policy、Collision 和 GlobalValidator 未修改。
- canonical `X/Y/Z → Three X/Z/Y` 坐标映射未修改。
- occupiedDimensions、position 和最终 AABB 未修改。
- BLK007C 仅在 Scene metadata 中兼容增加可选 `orientation`，既有字段未删除。
- 前端也可从 cargo.rotation.orientation 获取方向，旧 Mock 数据保持兼容。

## 必答问题

1. 标签是否随产品原始面旋转：是。
2. 箭头是否反映横放/侧放：是，Flat/Side 的产品向上轴为水平方向。
3. 同 SKU 不同方向是否互不影响：是，测试验证数组隔离且共享基础材质引用。
4. 是否共享基础 SKU Texture：是，一 SKU 一套纹理缓存。
5. 缓存是否受控：是，Geometry 最多六个方向变体。
6. 是否改变位置或 occupiedDimensions：否。
7. PHYSICAL / ASSIST 是否可用：是，页面切换验证通过。
8. BLK007C 是否兼容：是。
