# 3D-AICIVS: 3D AI Container Intelligent Loading Visualization System
### 3D 智能集装箱工业级装载规划与可视化系统 | Cleanroom Solver V2 • Three.js PBR 渲染 • 全向自适应剖切 • 空间算法拓扑

[![GitHub License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Three.js](https://img.shields.io/badge/Three.js-r128-black.svg)](https://threejs.org/)
[![Architecture](https://img.shields.io/badge/Architecture-Cleanroom%20Solver%20V2-emerald.svg)](./algorithm_space.html)

---

## 📖 项目简介 (Overview)

**3D-AICIVS** 是面向现代工业物流、外贸海运与集装箱多模态运输打造的**工业级 3D 智能装箱求解与沉浸式可视化全栈系统**。系统融合了运筹优化动态规划、高密度复合条带分层咬合、刚体运动学防倾倒约束、空腔极值点（Extreme Points / EMS）微块回填与基于 Three.js 的实时工业级 PBR 3D 渲染引擎。

系统能够毫秒级求解包含 15+ 复杂 SKU、多重摆放朝向、柜门区防倾倒封门、分层堆叠限制（`must_be_on_floor` / `max_stack_layers`）等严苛工业工况，达成 **100% 满配装载、0 违规、重心三维均衡**。

---

## 🌟 核心系统特性 (Key Features)

### 1.  Cleanroom Solver V2 工业求解内核 (4-Pass Hierarchical Sectional Engine)
- **Pass 1: 主断面多模数条带咬合 (Multi-Modulus Section Slices)**：
  - 基于动态规划与复合条带构建器（`CompositeStripBuilder`），求解宽度方向满宽闭包与横向模数紧密咬合。
- **Pass 2 & 3: 阶梯式顶部空间填补与回填 (Stepped Headroom & Top Fill)**：
  - 针对不同高度货箱构成的断面台阶，自适应下发顶部平铺与净空接力填充策略。
- **Pass 4: 空间网格三维空腔微块回填 (3D Spatial Grid Cavity Backfilling)**：
  - 采用极值点与空闲空间（EMS）扫描，对集装箱内部所有死角与残余空隙进行微块（Micro-Block）多向扩展回填，彻底消灭 SKU 尾数残留。
- **刚体物理防倾倒与动力学封门 (Anti-Tipping & Door-Zone Locking)**：
  - 柜门端（Door Zone）严格执行基底支撑率强校验（Support Ratio $\ge 0.7$），自动生成自锁式阶梯封门大墙，彻底规避开柜坍塌风险。
- **全动态约束解析 (Zero-Cache Dynamic Constraints)**：
  - 实时响应前端对货物的区位策略（`REAR`/`MIDDLE`/`DOOR`）、朝向权限（`UPRIGHT`/`FLAT`/`SIDE`）、落地限制（`must_be_on_floor`）与层数上限（`max_stack_layers`），计算请求纳秒级防缓存穿透。

### 2. 沉浸式 Three.js 工业级 3D 可视化视口 (Industrial 3D Viewport)
- **高对比度双层 3D 外轮廓描边 (Dual-Layer High-Contrast Outline Stroke)**：
  - 为 Hover / 选中的 SKU 货物生成同心微膨胀双层边缘描边（`#00f0ff` 电光青蓝 / `#ffeb3b` 荧光黄金），即使相邻货箱颜色极度相近亦能瞬间明晰物理边界。
- **六面全向拓扑自适应动态透视引擎 (6-Face Full Topological Cutaway)**：
  - 根据相机视角与视线夹角，实时智能剖切阻挡视线的壁板与立柱，保留背景结构，呈现 CAD 级别的空间通透感。
- **全箱型支持 (Standard Containers)**：
  - 精准支持 20GP, 40GP, 40HQ, 45HQ, 53HQ 等国际海运/内陆标准集装箱。
- **纵深剖面切片时间线 (Longitudinal Slicing Timeline)**：
  - 毫米级滑动条切片控制，支持自柜门向最深内壁逐层剖切检查内部货垛摆放细节。
- **三维重心（CoG）与载荷平衡检测**：
  - 实时计算纵向、横向、垂直重心偏差，图形化展示重心安全包络线。
- **多模式超清截图套件 (Multi-Mode Screenshot Suite)**：
  - 支持“一键复制到剪贴板”与“无损 PNG 下载”，支持纯 3D 视图与带 UI 全景两种渲染导出。

### 3. 算法空间全链路架构拓扑可视化 (`/algorithm_space.html`)
- **D3.js 力导向架构拓扑图**：覆盖从 L1 特征解析、L2 区位隔离、L3 满宽闭包、L4 拓扑支撑到 L5 动力学封门、L6 双盲物理裁决的完整链路。
- **KaTeX 数学定理与公式证明**：运筹优化截面规划、支撑率相交积分与刚体动力学力矩平衡严谨数学推导。
- **交互式节点检查器 (Node Inspector)**：实时查看每个算法环节的 Tensor 规范、中英文职责定义与核心源码片段。

---

## 🏛️ 系统架构 (Architecture)

```
3D-AICIVS/
├── backend/                              # 工业级 Python 求解器后端服务
│   ├── server.py                         # HTTP 核心服务 (REST API & 静态资源托管)
│   ├── solver_v2/                        # Cleanroom Solver V2 架构
│   │   ├── solver/
│   │   │   ├── unified_solver.py         # 4-Pass 统一分层切片与空间求解器
│   │   │   ├── composite_strip.py        # 复合条带模数构建器
│   │   │   ├── compaction.py             # 空间挤压与致密化
│   │   │   └── gap_filler.py             # 空腔微块回填引擎
│   │   ├── spaces/                       # 空闲空间与极值点引擎
│   │   │   ├── engine.py                 # FreeSpaceEngine 空间管理器
│   │   │   ├── ems.py                    # 3D Empty Maximal Spaces
│   │   │   ├── extreme_points.py         # 候选锚点计算
│   │   │   └── residual_quality.py       # 残余空间质量评分器
│   │   ├── domain/models.py              # Canonical 领域模型与 Tensor
│   │   └── api/adapter.py                # BLK-007C/D API 协议适配器
│   └── api/routes/                       # RESTful 路由服务
├── frontend/                             # 前端核心业务逻辑
│   └── src/
│       ├── backendSwitch.js              # 前后端通信网关与防缓存传输层
│       ├── manifestWorkflow.js           # 货单导入与多规格交互工作流
│       ├── orientationRendering.js       # 六面姿态与 UV 贴图渲染映射
│       └── errorLogReporter.js           # 前端运行时异常捕获与诊断器
├── devkit/cleanroom_solver_v2_devkit/    # 标准测试集与 Benchmark 评测工具
│   └── benchmarks/                       # 40HQ 15-SKU 复杂工业测试用例
├── index.html                            # 3D-AICIVS 核心应用界面 (Three.js PBR 视口)
├── algorithm_space.html                  # 算法空间全链路架构拓扑可视化
├── README.md                             # 项目技术全景文档
└── requirements.txt                      # 运行依赖 (无重型依赖，开箱即用)
```

---

## 🚀 快速启动与本地运行 (Quick Start)

### 1. 环境准备
推荐使用 Python 3.10+ 环境（无需安装臃肿复杂的外部重型库）：

```bash
# 克隆仓库
git clone https://github.com/1572865506/3D-AICIVS.git
cd 3D-AICIVS
```

### 2. 启动服务
```bash
# 启动后端服务 (默认监听 8080 端口)
python backend/server.py 8080
```

### 3. 访问应用
打开现代浏览器（Chrome / Edge / Safari / Firefox）访问：
- **装载规划与 3D 渲染主页**: [http://localhost:8080/](http://localhost:8080/)
- **算法空间架构拓扑图**: [http://localhost:8080/algorithm_space.html](http://localhost:8080/algorithm_space.html)
- **API 健康检查**: [http://localhost:8080/api/v1/loading/health](http://localhost:8080/api/v1/loading/health)

---

## 🔌 API 接口规范 (API Endpoints)

系统全面遵循 **BLK-007C / BLK-007D** 工业装载接口标准：

| 接口路径 | 方法 | 说明 |
| :--- | :--- | :--- |
| `/api/v1/loading/health` | `GET` | 检查后端内核健康状态与可用求解器列表 |
| `/api/v1/loading/jobs` | `POST` | 提交装载任务，执行 4-Pass Cleanroom Solver 计算并返回权威装载方案 |
| `/api/v1/loading/{job_id}` | `GET` | 获取指定任务的完整 3D 场景对象树、货垛序列与 KPI 指标 |
| `/api/v1/loading/{job_id}/layout` | `GET` | 获取集装箱空间布局与坐标系统 |
| `/api/v1/loading/{job_id}/highlight` | `GET` | 获取指定 SKU、墙体或装载步骤的高亮标识数组 |

---

## 💡 使用指南与交互提示 (User Guide)

1. **调整货单与约束**：在左侧抽屉中可直接修改各 SKU 的数量、摆放朝向要求、装载区域（最里面/中间/封柜门）及最大堆叠层数；
2. **一键计算**：点击主工具栏的 **“开始计算”**，系统将实时驱动 Cleanroom Solver V2 并以 3D 动画与实体渲染展示装载结果；
3. **Hover 轮廓高亮**：将鼠标悬停在左侧 SKU 卡片或 3D 货箱上，目标货箱将立即亮起**双层高对比度外轮廓描边**，轻松区分相近色系货箱；
4. **纵深切片查看**：拖动顶部切片滑块，可随时查看货柜任意断面内部的堆叠情况。

---

## 📄 开源许可证 (License)

本项目遵循 [MIT License](LICENSE) 开源。
