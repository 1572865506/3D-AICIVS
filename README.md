# 3D-AICIVS: 3D AI Container Intelligent Loading Visualization System
### 3D 智能货柜装载可视化系统 | 基于 Three.js 的工业级 PBR 渲染与六面全向拓扑自适应透视引擎

---

## 🌟 核心特性与架构亮点

1. **六面全向拓扑自适应动态透视引擎 (6-Face Full Topological Cutaway Engine)**：
   - 实时计算视线向量与六面体法线夹角（天窗顶板、平整钢底板、前侧长边板、后侧长边板、后端封闭墙板、前端双开箱门）。
   - **智能拓扑邻接判定**：当且仅当某构件/角件相邻的壁板均处于透视时，该构件同步剖切消隐；只要连接任意一面深色背景墙，相连骨架坚实保留，呈现最高级的工业 CAD 空间感。
   - **支持全方位观察**：无论从上方俯视、侧向环绕，还是自下而上仰视货柜底部托盘与货箱，均能无缝智能剖切。

2. **高保真实体工业集装箱建模 (ISO 20FT Standard Industrial Proportions)**：
   - **纤细硬朗骨架**：0.12m 纤细立柱与纵横端梁，配以 8 组 ISO 标准三向孔角件。
   - **深波纹 3D 瓦楞板**：顶板、侧板与双开箱门均具备 4cm 物理深度真实波浪起伏。
   - **重型工业箱门锁具**：直径 5cm 深色枪灰立式防盗锁杆、锻造凸轮锁头、32cm 加长转轴把手与 8 组重型承重铰链。
   - **平整一体式拉丝钢底板**：内嵌式深色微拉丝 PBR 钢板（`#2b343b`），平整严密嵌合于底梁内部。

3. **双向联动 3D 构件图层调试器 (CAD Layer & Object Inspector)**：
   - 结构化管理 20 组主体骨架构件、6 面全向壁板底板、双开箱门组与 84 件货物托盘。
   - 支持**一键👁️显隐切换、🔲网格拓扑线框模式、🎯单独隔离（Isolate Selection）**与 3D 视口点击反向寻址。
   - 实时毫米级尺寸、空间坐标（X/Y/Z）与材质属性检测。

4. **实时渲染效果调优控制台 (Live Render Studio)**：
   - **光影与角度**：光源 360° 方位角、高度角、距离、主光/环境光强、阴影柔和度半径与地表色调微调。
   - **材质与色泽**：支持骨架漆色、金属度、粗糙度、法线凹凸度与外壳透光色调调整。
   - **4 款一键风格预设**与**一键导出 JSON 配置文件**。

---

## 📦 基准配置标准 (Baseline Configuration)

项目已将当前最佳渲染参数锁定为官方基准配置 [`config.baseline.json`](./config.baseline.json)：

```json
{
  "foregroundOpacity": 0.01,
  "glassRoughness": 0.15,
  "glassColor": "#b8d7f4",
  "frameColor": "#2f383d",
  "frameMetal": 0.5,
  "frameRough": 0.68,
  "bump": 0.94,
  "backColor": "#43474c",
  "exposure": 0.72,
  "sunIntensity": 4.0,
  "ambIntensity": 0.2,
  "shadowRadius": 1.6,
  "groundColor": "#e0e7f0",
  "sunAzimuth": 42,
  "sunElevation": 52,
  "showShadow": true,
  "smartCutaway": true
}
```

---

## 🚀 快速启动与本地运行

该项目采用纯原生 Web 标准构建（Vanilla HTML5 + Three.js），零外部重型构建依赖，开箱即用：

```bash
# 1. 克隆仓库
git clone https://github.com/1572865506/3D-AICIVS.git
cd 3D-AICIVS

# 2. 启动静态 Web 服务（Python 示例）
python -m http.server 8080

# 3. 浏览器访问
# http://localhost:8080
```

---

## 📄 License
MIT License.
