# 3D-AICIVS 代码重构完整实施计划

## 执行概要

本计划详细说明将 index.html 中 5120 行内联 JavaScript 拆分为 7 个模块文件的完整步骤。当前进度：**3/7 模块已完成** (dataImportExport.js, stateManager.js, sceneManager.js)。

---

## 当前状态

### 已完成的模块
1. ✅ **frontend/src/dataImportExport.js** (220 行) - Excel 导入/导出、截图功能
2. ✅ **frontend/src/stateManager.js** (134 行) - 状态管理、localStorage 持久化
3. ✅ **frontend/src/sceneManager.js** (661 行) - Three.js 场景、相机、渲染器、门动画、自适应切割系统

### 待创建的模块
4. ⏸️ **frontend/src/visualizationCore.js** (~1200 行)
5. ⏸️ **frontend/src/apiClient.js** (~600 行)
6. ⏸️ **frontend/src/uiHandlers.js** (~1000 行)
7. ⏸️ **frontend/src/main.js** (~320 行)

---

## 步骤 1: 提取 visualizationCore.js (~1200 行)

### 代码来源
从 `E:/Users/Desktop/3D-AICIVS/index.html` 第 3164 行开始的内联脚本块中提取。

### 功能范围
- 3D boxes 渲染逻辑
- PBR 材质系统（MeshStandardMaterial 配置）
- 颜色映射系统（按 SKU、朝向、约束条件着色）
- Geometry 实例化和内存管理
- Cargo 对象到 Three.js Mesh 的转换
- 解决方案可视化更新函数

### 关键函数清单
```javascript
// Cargo mesh 创建
function createCargoMesh(cargoItem) { ... }

// 颜色映射
function getColorBySKU(sku) { ... }
function getColorByOrientation(orientation) { ... }
function getColorByConstraint(cargo) { ... }

// 可视化更新
function updateVisualization(solution) { ... }
function clearVisualization() { ... }

// 材质管理
function createPBRMaterial(color, metalness, roughness) { ... }
function disposeMesh(mesh) { ... }

// 坐标转换
function v2ToThreePosition(v2Pos) {
  return {
    x: v2Pos.x * V2_TO_THREE_SCALE.x + V2_TO_THREE_OFFSET.x,
    y: v2Pos.y * V2_TO_THREE_SCALE.y + V2_TO_THREE_OFFSET.y,
    z: v2Pos.z * V2_TO_THREE_SCALE.z + V2_TO_THREE_OFFSET.z
  };
}

// Hover 高亮
let hoveredObject = null;
function onMouseMove(event) { ... }
function highlightCargo(mesh) { ... }
function clearHighlight() { ... }
```

### Window 暴露接口
```javascript
window.visualizationCore = {
  updateVisualization,
  clearVisualization,
  createCargoMesh,
  getColorBySKU,
  getColorByOrientation,
  getColorByConstraint,
  onMouseMove
};
```

### 依赖关系
- 依赖 `window.stateManager` (获取当前配色模式)
- 依赖 `window.sceneManager` (访问 scene 对象)
- 依赖全局 `THREE` 对象

---

## 步骤 2: 提取 apiClient.js (~600 行)

### 功能范围
- `/api/solve` 请求封装
- `/api/validate` 调用
- `/api/status` 轮询
- Response parsing
- Error handling
- Loading 状态管理

### 关键函数清单
```javascript
// Solve API
async function callSolveAPI(cargoList, containerType, constraints) {
  const response = await fetch('/api/solve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      cargo_list: cargoList,
      container_type: containerType,
      constraints: constraints
    })
  });
  return await response.json();
}

// Validate API
async function callValidateAPI(solution) { ... }

// Status 轮询
async function pollStatus(taskId, onProgress, onComplete, onError) {
  const interval = setInterval(async () => {
    const status = await fetch(`/api/status/${taskId}`);
    const data = await status.json();
    
    if (data.state === 'SUCCESS') {
      clearInterval(interval);
      onComplete(data.result);
    } else if (data.state === 'FAILURE') {
      clearInterval(interval);
      onError(data.error);
    } else {
      onProgress(data);
    }
  }, 1000);
  
  return interval;
}

// Error parser
function parseAPIError(error) { ... }
```

### Window 暴露接口
```javascript
window.apiClient = {
  callSolveAPI,
  callValidateAPI,
  pollStatus,
  parseAPIError
};
```

### 依赖关系
- 无外部依赖
- 被 uiHandlers.js 调用

---

## 步骤 3: 提取 uiHandlers.js (~1000 行)

### 功能范围
- Container type 选择器事件
- Constraint toggles（max_weight_per_layer, support_ratio 等）
- Orientation controls
- Button event listeners（Solve, Clear, Export, Screenshot）
- Input validation
- UI 状态同步

### 关键函数清单
```javascript
// Container type 切换
function onContainerTypeChange(event) {
  const type = event.target.value;
  window.stateManager.setState({ containerType: type });
  window.sceneManager.rebuildContainerModel();
}

// Solve 按钮
async function onSolveButtonClick() {
  const state = window.stateManager.state;
  
  // 显示 loading
  showLoading();
  
  try {
    const result = await window.apiClient.callSolveAPI(
      state.cargoList,
      state.containerType,
      state.constraints
    );
    
    // 更新可视化
    window.visualizationCore.updateVisualization(result.solution);
    
    // 保存结果
    window.stateManager.setState({ solution: result.solution });
    
  } catch (error) {
    showError(error.message);
  } finally {
    hideLoading();
  }
}

// Constraint toggles
function onConstraintChange(constraintName, value) {
  const constraints = { ...window.stateManager.state.constraints };
  constraints[constraintName] = value;
  window.stateManager.setState({ constraints });
}

// Orientation 切换
function onOrientationModeChange(mode) {
  window.stateManager.setState({ colorMode: mode });
  window.visualizationCore.updateVisualization(window.stateManager.state.solution);
}

// Clear 按钮
function onClearButtonClick() {
  window.visualizationCore.clearVisualization();
  window.stateManager.setState({ solution: null, cargoList: [] });
}

// Screenshot 按钮
function onScreenshotButtonClick() {
  window.captureViewportScreenshot();
}

// Excel upload
function onExcelUploadChange(event) {
  const file = event.target.files[0];
  window.handleExcelFileUpload(file);
}
```

### Window 暴露接口
```javascript
window.uiHandlers = {
  onContainerTypeChange,
  onSolveButtonClick,
  onClearButtonClick,
  onConstraintChange,
  onOrientationModeChange,
  onScreenshotButtonClick,
  onExcelUploadChange
};
```

### 事件绑定
在 main.js 中统一绑定：
```javascript
document.getElementById('container-type-select').addEventListener('change', window.uiHandlers.onContainerTypeChange);
document.getElementById('solve-btn').addEventListener('click', window.uiHandlers.onSolveButtonClick);
// ... 其他事件绑定
```

### 依赖关系
- 依赖 `window.stateManager`
- 依赖 `window.apiClient`
- 依赖 `window.visualizationCore`
- 依赖 `window.sceneManager`

---

## 步骤 4: 提取 main.js (~320 行)

### 功能范围
- 应用入口点
- 模块初始化顺序控制
- DOM 事件绑定
- 初始状态恢复

### 完整代码结构
```javascript
/**
 * main.js
 * Application Entry Point
 */

// ==================== 初始化顺序 ====================

function initializeApp() {
  console.log('[Main] Initializing 3D-AICIVS...');
  
  // 1. 加载持久化状态
  window.loadAppState();
  
  // 2. Three.js 场景已经在 sceneManager.js 中自动启动
  // 无需手动调用 window.sceneManager.startApp()
  
  // 3. 绑定 UI 事件
  bindUIEvents();
  
  // 4. 恢复上次会话
  restoreLastSession();
  
  console.log('[Main] Application ready');
}

// ==================== UI 事件绑定 ====================

function bindUIEvents() {
  // Container type
  const containerSelect = document.getElementById('container-type-select');
  if (containerSelect) {
    containerSelect.addEventListener('change', window.uiHandlers.onContainerTypeChange);
  }
  
  // Solve button
  const solveBtn = document.getElementById('solve-btn');
  if (solveBtn) {
    solveBtn.addEventListener('click', window.uiHandlers.onSolveButtonClick);
  }
  
  // Clear button
  const clearBtn = document.getElementById('clear-btn');
  if (clearBtn) {
    clearBtn.addEventListener('click', window.uiHandlers.onClearButtonClick);
  }
  
  // Screenshot button
  const screenshotBtn = document.getElementById('screenshot-btn');
  if (screenshotBtn) {
    screenshotBtn.addEventListener('click', window.uiHandlers.onScreenshotButtonClick);
  }
  
  // Excel upload
  const excelInput = document.getElementById('excel-upload');
  if (excelInput) {
    excelInput.addEventListener('change', window.uiHandlers.onExcelUploadChange);
  }
  
  // Door toggle
  const doorBtn = document.getElementById('door-toggle-btn');
  if (doorBtn) {
    doorBtn.addEventListener('click', window.toggleDoorAction);
  }
  
  // Camera views
  const cameraButtons = document.querySelectorAll('[data-camera-view]');
  cameraButtons.forEach(btn => {
    btn.addEventListener('click', (e) => {
      const view = e.target.dataset.cameraView;
      window.switchCamera(view);
    });
  });
  
  // Adaptive cutaway
  const cutawayToggle = document.getElementById('cutaway-toggle');
  if (cutawayToggle) {
    cutawayToggle.addEventListener('change', window.toggleAdaptiveCutaway);
  }
  
  // Constraint checkboxes
  const constraintInputs = document.querySelectorAll('[data-constraint]');
  constraintInputs.forEach(input => {
    input.addEventListener('change', (e) => {
      const constraintName = e.target.dataset.constraint;
      const value = e.target.type === 'checkbox' ? e.target.checked : parseFloat(e.target.value);
      window.uiHandlers.onConstraintChange(constraintName, value);
    });
  });
  
  // Orientation mode
  const orientationRadios = document.querySelectorAll('input[name="color-mode"]');
  orientationRadios.forEach(radio => {
    radio.addEventListener('change', (e) => {
      window.uiHandlers.onOrientationModeChange(e.target.value);
    });
  });
}

// ==================== 会话恢复 ====================

function restoreLastSession() {
  const state = window.stateManager.state;
  
  // 恢复 container type
  const containerSelect = document.getElementById('container-type-select');
  if (containerSelect && state.containerType) {
    containerSelect.value = state.containerType;
  }
  
  // 恢复约束条件
  const constraints = state.constraints || {};
  Object.keys(constraints).forEach(key => {
    const input = document.querySelector(`[data-constraint="${key}"]`);
    if (input) {
      if (input.type === 'checkbox') {
        input.checked = constraints[key];
      } else {
        input.value = constraints[key];
      }
    }
  });
  
  // 如果有上次的 solution，恢复可视化
  if (state.solution) {
    window.visualizationCore.updateVisualization(state.solution);
  }
}

// ==================== 启动应用 ====================

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeApp);
} else {
  initializeApp();
}

console.log('[Main] Module loaded');
```

### Window 暴露接口
```javascript
// main.js 不需要暴露接口，它是应用入口
```

### 依赖关系
- 依赖所有其他模块
- 最后加载

---

## 步骤 5: 更新 index.html

### 操作清单

#### 5.1 在第 2142 行后添加模块引用
```html
<!-- Existing modules (lines 2135-2142) -->
<script src="/frontend/src/errorLogReporter.js"></script>
<script src="/frontend/src/orientationRendering.js"></script>
<script src="/frontend/src/manifestWorkflow.js"></script>
<script src="/frontend/src/backendSwitch.js"></script>

<!-- NEW: Modularized core modules -->
<script src="/frontend/src/stateManager.js"></script>
<script src="/frontend/src/dataImportExport.js"></script>
<script src="/frontend/src/sceneManager.js"></script>
<script src="/frontend/src/visualizationCore.js"></script>
<script src="/frontend/src/apiClient.js"></script>
<script src="/frontend/src/uiHandlers.js"></script>
<script src="/frontend/src/main.js"></script>
```

#### 5.2 删除行 3164-8284 的内联脚本块
- 定位到 `<script>` 标签开始行（约 3164 行）
- 定位到对应的 `</script>` 标签结束行（约 8284 行）
- 删除整个区块

### 验证点
- 删除后 index.html 应从约 8284 行减少到约 3170 行
- 保留所有 CDN 引用（three.js, OrbitControls, xlsx, html2canvas）
- 保留所有 HTML 结构和 CSS

---

## 步骤 6: 功能验证

### 验证清单

#### 6.1 基础功能
- [ ] 页面加载无 JavaScript 错误
- [ ] Three.js 场景正常渲染
- [ ] OrbitControls 可以旋转/缩放/平移视角
- [ ] 地面阴影正常显示

#### 6.2 Container 功能
- [ ] Container type 切换（20GP, 40GP, 40HQ, 45HQ, 53HQ）
- [ ] 切换后容器模型尺寸正确更新
- [ ] 门开关动画正常（quadratic easing）
- [ ] Adaptive cutaway 切割系统功能正常

#### 6.3 Camera 功能
- [ ] Camera 预设视角切换（iso, front, side, top）
- [ ] 切换动画流畅（cubic easing）
- [ ] Viewport boundary enforcement 自动回弹

#### 6.4 数据导入
- [ ] Excel 文件上传解析正常
- [ ] SKU 列表正确填充到界面
- [ ] Template 下载功能正常

#### 6.5 API 调用
- [ ] Solve 按钮调用 `/api/solve`
- [ ] Loading 状态显示
- [ ] 解决方案返回后正确渲染 3D boxes
- [ ] 颜色映射正确（按 SKU/orientation/constraints）

#### 6.6 约束条件
- [ ] Constraint toggles 正确更新状态
- [ ] 约束值变化后重新 Solve 生效

#### 6.7 导出功能
- [ ] Screenshot 导出正常
- [ ] Manifest JSON 下载正常

#### 6.8 状态持久化
- [ ] localStorage 正确保存状态
- [ ] 刷新页面后状态恢复
- [ ] 7 天 TTL cache 机制正常

---

## 步骤 7: 代码审查检查点

### 审查清单

#### 7.1 代码质量
- [ ] 所有函数有清晰的职责
- [ ] 无重复代码
- [ ] 变量命名语义化
- [ ] 无全局污染（除 window 暴露接口外）

#### 7.2 依赖关系
- [ ] 模块间依赖关系清晰
- [ ] 无循环依赖
- [ ] 加载顺序正确

#### 7.3 性能
- [ ] 无内存泄漏（Mesh dispose 正确）
- [ ] Event listener 正确移除
- [ ] requestAnimationFrame 无重复调用

#### 7.4 错误处理
- [ ] API 调用有 try-catch
- [ ] 用户友好的错误提示
- [ ] 控制台日志完整

---

## 步骤 8: Git 操作（需用户授权）

**⚠️ 重要提醒：按照用户要求，暂不推送到 GitHub。如需推送，必须先询问用户并新建分支。**

### 如果用户同意推送，执行以下步骤：

```bash
# 1. 创建新分支
git checkout -b refactor/modularize-index-html

# 2. 添加文件
git add frontend/src/dataImportExport.js
git add frontend/src/stateManager.js
git add frontend/src/sceneManager.js
git add frontend/src/visualizationCore.js
git add frontend/src/apiClient.js
git add frontend/src/uiHandlers.js
git add frontend/src/main.js
git add index.html

# 3. 提交
git commit -m "refactor(frontend): modularize index.html inline scripts into 7 modules

- Extract 5120 lines of inline JavaScript from index.html
- Create sceneManager.js (Three.js scene/camera/renderer/lights)
- Create visualizationCore.js (3D boxes rendering, PBR materials, color mapping)
- Create apiClient.js (API calls to /api/solve, /api/validate, /api/status)
- Create uiHandlers.js (UI event handlers, constraint toggles)
- Create dataImportExport.js (Excel import/export, screenshots)
- Create stateManager.js (state management, localStorage persistence)
- Create main.js (app entry point, event binding)
- Update index.html to reference external modules
- Remove ~5120 lines inline script block (lines 3164-8284)

Closes #[issue_number_if_applicable]

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"

# 4. 推送到远程
git push -u origin refactor/modularize-index-html

# 5. 创建 Pull Request
gh pr create \
  --title "refactor(frontend): modularize index.html inline scripts" \
  --body "$(cat <<'EOF'
## Summary
Modularized 5120 lines of inline JavaScript from index.html into 7 well-structured modules in frontend/src/.

## Changes
- ✅ **sceneManager.js** (661 lines): Three.js scene, camera, renderer, lighting, doors, adaptive cutaway
- ✅ **visualizationCore.js** (~1200 lines): 3D boxes rendering, PBR materials, color mapping
- ✅ **apiClient.js** (~600 lines): API calls, polling, error handling
- ✅ **uiHandlers.js** (~1000 lines): UI event handlers, constraint toggles
- ✅ **dataImportExport.js** (220 lines): Excel import/export, screenshots
- ✅ **stateManager.js** (134 lines): State management, localStorage
- ✅ **main.js** (~320 lines): App entry point, initialization

## Testing
- [x] Page loads without errors
- [x] Container type switching works
- [x] Door animations functional
- [x] Camera views functional
- [x] Adaptive cutaway works
- [x] Excel import works
- [x] Solve API works
- [x] Visualization renders correctly
- [x] State persistence works

## Architecture
Follows existing pattern in frontend/src/ (errorLogReporter.js, etc.). Uses window object exposure for cross-module communication.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## 附录 A: 文件大小对照表

| 文件 | 预估行数 | 实际行数 | 状态 |
|------|---------|---------|------|
| dataImportExport.js | ~700 | 220 | ✅ 完成 |
| stateManager.js | ~500 | 134 | ✅ 完成 |
| sceneManager.js | ~800 | 661 | ✅ 完成 |
| visualizationCore.js | ~1200 | - | ⏸️ 待创建 |
| apiClient.js | ~600 | - | ⏸️ 待创建 |
| uiHandlers.js | ~1000 | - | ⏸️ 待创建 |
| main.js | ~320 | - | ⏸️ 待创建 |
| **总计** | **~5120** | **1015** | **19.8%** |

---

## 附录 B: 关键代码位置速查

### index.html 关键位置
- **行 2135-2142**: 现有外部模块引用
- **行 3164**: 内联 `<script>` 开始标记
- **行 8284**: 内联 `</script>` 结束标记

### 代码识别标记
查找以下关键字定位代码边界：
- `let scene, camera, renderer` → sceneManager.js
- `function createCargoMesh` → visualizationCore.js
- `fetch('/api/solve'` → apiClient.js
- `document.getElementById(...).addEventListener` → uiHandlers.js / main.js
- `function parseExcelData` → dataImportExport.js (已完成)
- `const CONTAINER_SPECS` → stateManager.js (已完成)

---

## 执行建议

1. **分步执行**：每完成一个模块立即测试，不要等全部完成
2. **备份原文件**：`cp index.html index.html.backup`
3. **使用版本控制**：每个模块完成后提交一次 commit
4. **增量验证**：每添加一个模块引用后刷新页面检查 console
5. **保留原文件**：最终删除内联代码前先确认所有功能正常

---

## 联系与审核

完成上述步骤后，请通知我进行最终审核。我将验证：
- 代码质量和风格一致性
- 功能完整性
- 性能和安全性
- Git 提交信息规范

**预计总耗时**：4-6 小时（取决于代码熟悉程度）
