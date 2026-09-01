# 3D-AICIVS 算柜算法引擎 V1 -> V2 迁移与退役路线图

本文档正式规范 `src/`（Legacy V1 启发式管线）向 `backend/solver_v2/`（Cleanroom V2 工业拓扑管线）的迁移策略、功能对照表与退役时间表，避免两套算法逻辑长期共存产生语义漂移。

---

## 1. 架构定位对比

| 维度 | Legacy V1 (`src/`) | Cleanroom V2 (`backend/solver_v2/`) |
| :--- | :--- | :--- |
| **理论模型** | 空间切片启发式 (SDP) | 6 层拓扑机理 (分层实体推进 + 空间自适应自锁) |
| **几何与物理校验** | 求解器内局部碰撞校验 | 独立双盲全局验证器 (`IndependentGlobalValidator`) |
| **空间管理** | 1D/2D 空间分割 | 3D Voxel BFS 泛洪 + 极值点 + EMS 空间拓扑 |
| **门区处理** | 经验降高梯级裁剪 | 90° 翻转大深基底物理自锁 + 弹性门区前沿协作封门 |
| **约束完整性** | 部分硬编码 | 6 大物理约束全字段捕获与运行时硬拦截 |
| **多柜型适配** | 仅优化 40HQ | 20GP/40GP/40HQ/45HQ/53FT 全参数化动态适配 |

---

## 2. 功能模块对照与迁移映射

| 功能领域 | V1 遗留模块 (`src/`) | V2 标准模块 (`backend/solver_v2/`) | 迁移状态 |
| :--- | :--- | :--- | :--- |
| **货物数据模型** | `src.unified_pipeline.model.UniversalCargoTensor` | `backend.solver_v2.domain.models` (`CargoSKU`, `BoxDim`, `QuantityPlan`) | 已完成对接 |
| **物理与几何验证** | `src.optimization.validator` | `backend.solver_v2.validation.independent_validator.IndependentGlobalValidator` | 已完成收敛 |
| **门区封柜规划** | `src.solver.door_sealing` | `backend.solver_v2.door.closure_planner.DoorClosurePlanner` | 已完成收敛 |
| **顶层回填算法** | `src.solver.topfill` | `backend.solver_v2.topfill.planner.TopFillPlanner` | 已完成收敛 |
| **大墙结构管理** | `src.unified_pipeline.engine.UniversalHierarchicalSolver` | `backend.solver_v2.structure.wall_manager.WallStructureManager` | 双轨运行中 |
| **空腔分类与防架桥** | 无 / 简单启发式 | `backend.solver_v2.structure.cavity_classifier.AdvancedCavityClassifier` | 已全面激活 |

---

## 3. 冻结与退役阶段计划

- **阶段一（已完成）**：`src/` 停止任何新功能开发，进入只读维护模式；
- **阶段二（当前阶段）**：后端 `backend/server.py` 默认调度 `v2-cleanroom` 引擎，`src/` 仅保留兼容性基准对比；
- **阶段三（计划 2026-10-01）**：移除 `src/` 遗留非通用模块，全工程统一引用 `backend/solver_v2/`。
