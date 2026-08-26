# BLK-007F-7.8 Browser Verification

本地 `http://127.0.0.1:8091/?mode=mock` 已完成浏览器验证：

- 页面默认显示 `📦 真实贴图`。
- 点击后切换为 `📦 朝向辅助`。
- Mock LoadingResult 的两件货物由后端适配路径创建。
- ASSIST 使用单个批量 `LineSegments`，不是逐箱 ArrowHelper。
- 页面切换后无新增 JavaScript 错误。

真实贴图仍是默认生产显示；青色辅助箭头仅表达产品原始向上轴，不改变包装贴图、
箱体 Geometry、坐标或占用尺寸。
