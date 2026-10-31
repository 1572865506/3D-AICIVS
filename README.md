# 3D-AICIVS: 3D AI Container Intelligent Loading Visualization System
### 3D 智能集装箱工业级装载规划与可视化系统 | Cleanroom Solver V2 • 物理统一门禁 • 专家打标与三维剖切 • 数据工厂与 Transformer 决策 • Three.js PBR 渲染 • 空间算法拓扑 • 测试诊断看板

[![GitHub License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Three.js](https://img.shields.io/badge/Three.js-r128-black.svg)](https://threejs.org/)
[![Architecture](https://img.shields.io/badge/Architecture-Cleanroom%20Solver%20V2-emerald.svg)](./algorithm_space.html)
[![Physics Kernel](https://img.shields.io/badge/Physics%20Kernel-Decoupled%20Gate-orange.svg)](./backend/solver_v2/physics_kernel/)
[![AI Brain](https://img.shields.io/badge/AI%20Brain-Transformer%20Guided-purple.svg)](./backend/solver_v2/brain/)
[![Test Harness](https://img.shields.io/badge/Harness-Tier1%20100%20Cases-purple.svg)](./test_dashboard.html)

---

## 📖 项目简介 (Overview)

**3D-AICIVS** 是面向现代现代智慧物流、工业海运与多式联运集装箱打造的**工业级 3D 智能装箱求解、专家协同与全景可视化全栈系统**。系统深度融合了运筹优化切片咬合、解耦物理约束内核、端到端装载决策模型（Transformer Brain）、引导式集束搜索、工业专家 3D 打标标注工作流以及基于 Three.js 的实时工业级 PBR 3D 渲染引擎。

系统能够毫秒级至秒级高保真求解包含 15+ 复杂异构 SKU、多维旋转朝向受限、门区防倾覆自锁、严苛物理分层（`must_be_on_floor` / `max_stack_layers` / `no_top_stack` / `max_bearing_weight`）等超复杂工况，达成 **100% 满配刚性装载、0 规则违规、0 物理碰撞、空间三维重心平衡**。

---

## 🌟 核心系统特性 (Key Features)

### 1. Cleanroom Solver V2 工业求解内核与五阶段架构 (5-Stage Architecture)
- **阶段 1：解耦统一物理内核 (Decoupled Shared Physics Kernel)**：
  - 核心物理规则下沉解耦为独立算子：基底接触与完全支撑 (`support`)、碰撞与三维干涉 (`collision`)、逐层递增压载核算 (`bearing`)、六向允许姿态检验 (`orientation`) 以及倾覆力矩审计 (`tipping`)。
  - 统一前置门禁 (`UnifiedConstraintGate`)，杜绝后处理删箱，在放置前完成全维度严格裁决。
- **阶段 2：3D 交互式专家打标与剖切协同 (Expert Annotation & Cross-Section Slicer)**：
  - 提供毫米级双轴剖切时间线控制，内嵌工业专家评审打标抽屉与历史面板。支持 A/B/C/D 四级评级、违规标签记录与专家改进意图录入，形成持续迭代闭环。
- **阶段 3：工业数据工程工厂与反空腔过滤管线 (Data Factory Pipeline)**：
  - 内置复杂装载工况合成器 (`ManifestSynthesizer`) 与真实运行轨迹采集器 (`PackingDataCollector`)。
  - 配备空腔率拓扑检测器与反空腔过滤器 (`AntiCavityFilter`)，自动化清洗并输出可供神经网络训练的高价值基准数据集 (`PackingDataset`)。
- **阶段 4：端到端装载决策网络 (Transformer Brain)**：
  - 基于自注意力机制与几何特征编码的 `PackingTransformer` 启发式策略前馈网络，精准提取高维空间拓扑特征与剩余装载倾向，提供全局动作置信度先验。
- **阶段 5：神经引导式集束搜索 (Guided Beam Search Engine)**：
  - 结合 Transformer/启发式先验概率与严格物理门禁，执行多候选分支回溯探索与前瞻剪枝，在超大规模组合爆炸下实现全局最优求解。

### 2. 4-Pass 分层切片与空间致密化引擎 (Hierarchical Sectional Placer)
- **Pass 1: 主断面多模数条带咬合 (Multi-Modulus Section Slices)**：
  - 基于动态规划与复合条带构建器（`CompositeStripBuilder`），求解宽度方向满宽闭包与横向模数紧密咬合。
- **Pass 2 & 3: 阶梯式顶部空间平铺与接力填充 (Stepped Headroom & Top Fill)**：
  - 自适应识别断面台阶落差，下发顶部平铺与净空接力填充策略。
- **Pass 4: 空间网格三维空腔微块回填 (3D Spatial Grid Cavity Backfilling)**：
  - 极值点与空闲空间（EMS）扫描，对内部死角与残余空隙进行微块（Micro-Block）多向扩展回填，彻底消除刚性 SKU 弃装与饥饿。
- **Pass 5: 刚体动力学防倾倒与自锁封门 (Anti-Tipping & Door-Zone Locking)**：
  - 柜门端（Door Zone）自适应生成咬合自锁式阶梯封门结构，消除海运晃动与开柜坍塌风险。

### 3. 沉浸式 Three.js 工业级 3D 可视化视口 (Industrial 3D Viewport)
- **高对比度双层 3D 外轮廓描边 (Dual-Layer High-Contrast Outline Stroke)**：
  - 为 Hover / 选中的货物生成同心微膨胀双层边缘描边（`#00f0ff` 电光青蓝 / `#ffeb3b` 荧光黄金），相近色系货箱边界瞬间明晰。
- **六面全向拓扑自适应动态透视引擎 (6-Face Full Topological Cutaway)**：
  - 随相机视角实时剖切阻挡视线的壁板与立柱，保持背景结构，呈现 CAD 级别的工业通透感。
- **全国际标准箱型支持 (Standard Containers)**：
  - 精准覆盖 20GP, 40GP, 40HQ, 45HQ, 53HQ 等国际海运及内陆标准集装箱。
- **横纵多轴剖面切片与时间线**：
  - 毫米级滑动控制，自由沿集装箱进深（Z轴）及高度（Y轴）剖视内部货垛微观细节。
- **三维重心（CoG）与载荷平衡检测**：
  - 动态计算纵向、横向、垂直重心偏差，图形化渲染合规安全包络区。

### 4. 自动化测试套件与工业测试看板 (`/test_dashboard.html`)
- **平台级测试矩阵 (Platform Test Harness)**：
  - 内置 50+ 标准工业工况、随机工况生成器与 Tier 1（100 用例）全自动化批跑流水线。
- **全维度归因分析引擎 (Analyzer & Diagnostic)**：
  - 自动化审计空间利用率、刚性履行率、弹性完成率、优先级倒挂判定、违规及碰撞。
- **交互式测试看板 (Interactive Test Dashboard)**：
  - Web 端可视化监控测试批次进度、健康度分布、耗时对比及失败归因详情，并支持一键发起增量压测。

### 5. 算法空间全链路架构拓扑可视化 (`/algorithm_space.html`)
- **D3.js 力导向架构拓扑图**：覆盖从 L1 特征解析、L2 区位隔离、L3 满宽闭包、L4 拓扑支撑到 L5 动力学封门、L6 双盲物理裁决的完整拓扑链路。
- **KaTeX 数学定理与公式证明**：运筹优化截面规划、支撑率相交积分与刚体动力学力矩平衡严谨数学推导。
- **交互式节点检查器 (Node Inspector)**：实时查看每个算法环节的 Tensor 规范、中英文职责定义与核心源码片段。

---

## 🏛️ 系统架构 (Architecture)

```
3D-AICIVS/
├── backend/                              # 工业级 Python 求解器与后端服务
│   ├── server.py                         # HTTP 核心服务 (REST API、打标接口与静态托管)
│   ├── harness_service.py                # 测试看板与自动化 Harness 调度 API 服务
│   └── solver_v2/                        # Cleanroom Solver V2 模块化架构
│       ├── physics_kernel/               # 阶段 1: 共享解耦物理内核
│       │   ├── unified_gate.py           # 统一前置物理门禁
│       │   ├── support.py                # 基底有效支撑与多箱搭接计算
│       │   ├── collision.py              # AABB 空间干涉与碰撞检测
│       │   ├── bearing.py                # 逐层递增载荷与压强核算
│       │   ├── orientation.py            # 六面姿态合法性检验
│       │   ├── tipping.py                # 重心偏角与倾覆力矩审计
│       │   └── constraint_gate.py        # 业务约束规则组合门禁
│       ├── brain/                        # 阶段 4: 端到端决策模型
│       │   └── packing_transformer.py    # Transformer 装载决策与特征编码前馈网络
│       ├── placement_engine/             # 阶段 5: 启发式与引导式搜索
│       │   └── guided_beam_search.py     # 神经引导式集束搜索与状态剪枝探索
│       ├── data_pipeline/                # 阶段 3: 工业数据工厂
│       │   ├── manifest_synthesizer.py   # 复杂多规格货单工况合成器
│       │   ├── collector.py              # 真机装载轨迹与决策步采集器
│       │   ├── anti_cavity_filter.py     # 反空腔拓扑清洗与质量过滤
│       │   └── packing_dataset.py        # 训练样本 Tensor 打包与持久化
│       ├── solver/                       # 核心求解与切片引擎
│       │   ├── unified_solver.py         # 4-Pass 分层切片与空间微块回填引擎
│       │   ├── composite_strip.py        # 复合条带模数构建器 (Knapsack DP)
│       │   ├── compaction.py             # 空间挤压与致密化后处理
│       │   ├── gap_filler.py             # 空腔微块回填引擎
│       │   ├── constructive_placer.py    # 快速构造式放置策略
│       │   └── cpsat_hybrid_solver.py    # OR-Tools CP-SAT 混合优化求解器
│       ├── stability/
│       │   └── tipping_moment.py         # PASS 5 门区倾覆力矩审计
│       ├── validation/
│       │   └── independent_validator.py  # 10 维双盲物理约束独立验证器
│       ├── domain/models.py              # Canonical 领域模型与 Tensor
│       └── api/adapter.py                # 工业装载标准 API 协议适配器
├── frontend/                             # 模块化前端体系 (ES Modules)
│   └── src/
│       ├── expertAnnotation.js           # 阶段 2: 3D 专家打标与方案评审交互组件
│       ├── crossSectionSlicer.js         # 阶段 2: 交互式横纵双轴剖切控制器
│       ├── stateManager.js               # 全局响应式状态管理
│       ├── sceneManager.js               # Three.js 场景构建、光影与相机控制
│       ├── visualizationCore.js          # 货箱几何体装配、材质与双层高亮管线
│       ├── uiHandlers.js                 # 侧边抽屉、工具栏与交互绑定
│       ├── dataImportExport.js           # 货单导入/导出与格式化
│       ├── apiClient.js                  # 算柜与任务请求通信客户端
│       ├── backendSwitch.js              # 网关协议切换与适配层
│       ├── manifestWorkflow.js           # 货单多规格交互工作流
│       ├── orientationRendering.js       # 六面姿态与 UV 贴图渲染映射
│       └── errorLogReporter.js           # 运行时异常捕获与诊断器
├── scripts/
│   ├── run_data_factory.py               # 阶段 3: 数据工厂一键批量运行与清洗脚本
│   ├── batch_sku_diagnostic.py           # 批诊断工具 (履约率/倒挂/饥饿/违规全量诊断)
│   └── test_harness/                     # 平台级自动化测试流水线
│       ├── runner.py                     # 多用例并发/串行调度执行器
│       ├── analyzer.py                   # 智能归因与指标统计
│       ├── case_generator.py             # 组合变异与随机工况生成器
│       └── reporter.py                   # Markdown/JSON 诊断报告生成器
├── tests/
│   ├── cases/                            # 工业基准与扩展用例 (Case 01 ~ Case 51+)
│   ├── benchmark_suite.py                # 核心 Benchmark 基准测试套件
│   ├── regression_guard.py               # 回归守护防线
│   ├── test_physics_kernel_consistency.py# 物理内核一致性与门禁测试
│   ├── test_brain_search.py              # Transformer Brain 与搜索测试
│   ├── test_data_pipeline.py             # 数据工厂合成与过滤测试
│   ├── test_annotation_api.py            # 专家打标评审 API 测试
│   └── test_stage5_integration.py        # 全链路集成测试
├── data/
│   └── annotations/                      # 专家评审与打标数据持久化目录 (.jsonl)
├── index.html                            # 3D-AICIVS 核心应用界面 (Three.js PBR 视口 + 专家打标)
├── test_dashboard.html                   # 自动化测试与压测监控看板
├── algorithm_space.html                  # 算法空间全链路架构拓扑可视化
├── docs/                                 # 规范与架构设计文档库
│   ├── SKU_RULES_SEMANTIC_SPECIFICATION.md # SKU 约束规则语义全景规范
│   └── SOLVER_V2_ARCHITECTURE.md         # Solver V2 架构演进说明
└── requirements.txt                      # 运行依赖 (标准库友好，开箱即用)
```

---

## 🚀 快速启动与本地运行 (Quick Start)

### 1. 环境准备
推荐使用 Python 3.10+ 环境：

```bash
# 克隆仓库
git clone https://github.com/1572865506/3D-AICIVS.git
cd 3D-AICIVS

# 安装可选开发/求解加速依赖 (基础求解支持纯 Python 标准库开箱即用)
pip install -r requirements.txt
```

### 2. 启动服务
```bash
# 启动核心后端服务 (默认监听 8080 端口，同时托管 REST API 与静态前端)
python backend/server.py 8080
```

### 3. 访问应用
打开现代浏览器（Chrome / Edge / Safari / Firefox）访问：
- **装载规划与 3D 渲染主页**: [http://localhost:8080/](http://localhost:8080/)
- **自动化测试看板**: [http://localhost:8080/test_dashboard.html](http://localhost:8080/test_dashboard.html)
- **算法空间架构拓扑图**: [http://localhost:8080/algorithm_space.html](http://localhost:8080/algorithm_space.html)
- **API 健康检查**: [http://localhost:8080/api/v1/loading/health](http://localhost:8080/api/v1/loading/health)

### 4. 运行数据工厂 (可选)
一键批量合成装载工况、采集真实轨迹并通过反空腔过滤器提纯生成训练数据集：
```bash
python scripts/run_data_factory.py --num-manifests 10 --output-dir data/factory_output
```

---

## 🧪 测试与质量守护体系 (Testing & Diagnostic)

为杜绝倒挂、弃装与物理违规，项目推行严格的分级测试门禁：

```bash
# L1 冒烟验证 (<30s，修改代码后必跑)
python -c "from backend.solver_v2 import solve; print('import OK')"

# L2 核心诊断 (单用例全量指标诊断)
python scripts/batch_sku_diagnostic.py --case "14-SKU"

# L3 基准与回归守护 (提交前全量验证)
python tests/benchmark_suite.py --run
python tests/regression_guard.py

# L4 平台级 100 用例自动化压测与归因
python scripts/test_harness/runner.py --tier 1
```

---

## 🔌 API 接口规范 (API Endpoints)

系统遵循工业装载接口标准、Harness 诊断协议与专家标注协同协议：

| 接口路径 | 方法 | 说明 |
| :--- | :--- | :--- |
| `/api/v1/loading/health` | `GET` | 检查后端内核健康状态与可用求解器列表 |
| `/api/v1/loading/jobs` | `POST` | 提交装载任务，执行 Cleanroom Solver V2 计算并返回权威装载方案 |
| `/api/v1/loading/{job_id}` | `GET` | 获取指定任务的完整 3D 场景对象树、货垛序列与 KPI 指标 |
| `/api/v1/loading/{job_id}/layout` | `GET` | 获取集装箱空间布局与坐标系统 |
| `/api/v1/annotations` | `GET` | 查询专家历史评审与打标记录（支持方案 ID 与评级过滤） |
| `/api/v1/annotations` | `POST` | 提交专家打标评审记录（评级、违规标记、改进建议与签名） |
| `/api/v1/harness/status` | `GET` | 查询测试 Harness 当前运行状态与最近执行摘要 |
| `/api/v1/harness/reports/latest` | `GET` | 获取最新 Tier 自动化测试全量分析报告 |
| `/api/v1/harness/run` | `POST` | 触发指定 Tier 或指定约束标签的自动化回归测试 |
| `/api/v1/harness/stop` | `POST` | 中断当前正在执行的压测任务 |

---

## 💡 使用指南与交互提示 (User Guide)

1. **调整货单与业务约束**：
   - 在左侧抽屉中可直接修改各 SKU 的长宽高尺寸、装载件数、允许摆放朝向、落地限制（`必须落地`）、抗压极限（`最大承重`）、顶层限制（`不可被压`）以及最大堆叠层数；
2. **一键计算与方案渲染**：
   - 点击主工具栏的 **“开始计算”**，系统将实时驱动求解器完成装载排布，并在 3D 视口呈现高精度装箱几何排布与空间利用率；
3. **Hover 轮廓高亮与检查**：
   - 将鼠标悬停在左侧 SKU 列表或 3D 货箱上，目标货箱将立即亮起**双层高对比度外轮廓描边**，即使相邻货箱颜色极度接近亦能精准区分；
4. **横纵双轴剖面切片**：
   - 拖动顶部 **“进深剖切 (Z)”** 或 **“高度剖切 (Y)”** 滑块，自由深入柜体内部检查任意断面结构；
5. **专家评审与打标闭环**：
   - 点击顶部 **“专家打标”** 按钮即可呼出标注面板，对当前方案进行 A/B/C/D 四级评级、标注违规项与装载建议，并支持查看历史打标记录；
6. **自动化压测与测试看板**：
   - 点击顶部工具栏的 **“测试看板”**，可直达测试监控中心查看百例工况压测详情、碰撞检测状态与物理健康度。

---

## 📄 开源许可证 (License)

本项目遵循 [MIT License](LICENSE) 开源。
