# BLK-002C 交付报告: Door Reserve Deployment & Boundary Unification

## 1. 任务概述与核心目标
在 BLK-002B 成功解决 SKU 崩塌、建立权威门区准备硬门禁（Hard Readiness Gate）的基础上，BLK-002C 重点攻坚并彻底解决了门区阶段（Phase 5 DOOR_SEAL）的两大核心痛点：
1. **Zone Boundary 权威源统一**：消除了 `DoorClosurePlanner`、`AdaptiveZoneManager`、`Validator` 以及评测脚本中各自独立的阈值与边界计算冲突，全部统一定向到 `ElasticDoorFrontier` 作为唯一真相源（Authoritative Source）。
2. **Door Reserve Pool 真实按需部署**：解决了主体推进到门端前沿（$11.480\text{m}$）后预留池未实际落位的问题，打通了门区前沿锚点生成、合法姿态遍历、物理碰撞/支撑/防倾覆校验及几何闭合求解链路，真实部署了预留 SKU（如 SKU-03、SKU-04），将残余门隙从 $0.552\text{m}$ 显著缩减至 **$0.122\text{m} \le 0.50\text{m}$**，全面达成 **`is_door_ready: true`**。

---

## 2. 核心架构修复与实现

### 2.1 统一权威边界（Zone Boundary Unification）
- **边界源统一**：`DoorClosurePlanner` 和评估流程全面对接 `ElasticDoorFrontier.get_metrics()`：
  - `authoritative_transition_start_x`: **$11.132\text{m}$**
  - `authoritative_door_start_x`: **$11.632\text{m}$**
  - `latest_safe_main_x`: **$11.832\text{m}$**
  - `boundary_source`: `"ElasticDoorFrontier"`
- **Strict Reachability 语义修正**：
  - `reached_transition_zone`: $X_{\max} \ge 11.132\text{m}$
  - `reached_door_closure_zone`: $X_{\max} \ge 11.632\text{m}$
  - 彻底消除了主墙在 $11.480\text{m}$ 时误判 `reached_door_closure_zone = true` 的风险。

### 2.2 动态按需门区部署（Active Door Reserve Deployment）
在 Phase 5 (`PlacementContext.DOOR_SEAL`) 或主体推进至 Transition 区间后，自动触发 `DoorClosurePlanner.deploy_door_seal(...)`：
- **前沿动态锚点生成**：在前沿货墙网格（$X \in [X_{\text{front}}, L_x]$）自动提取 Floor Frontier、Supported Frontier 以及 Extreme Points。
- **合法姿态与物理校验**：对预留池中的 `SKU-02 / 03 / 04 / 14` 遍历允许的 3D 姿态（包括平放/侧放深度优化），严密校验 AABB 边界、空间碰撞、底面接触支撑率（$\ge 70\%$）及防倾覆宽高比（$\text{slenderness} \le 3.0$）。
- **按需闭合终止准则**：不强制要求 46 箱全部放入，只要几何闭合、支撑稳定性、`largest_door_gap <= 0.50m`、`closure_coverage >= 25%`、`door_occupancy >= 5%` 达成即完成封门，避免暴力塞箱破坏货堆规整性。

---

## 3. 基准测试与模式对比验证（Benchmark Case 001）
基准数据集：`devkit/cleanroom_solver_v2_devkit/benchmarks/40hq_cleanroom_case_001.json`（40HQ 集装箱，$L_x=12.032\text{m}, L_y=2.352\text{m}, L_z=2.698\text{m}$，14 种 SKU，1845 箱货物）。

| 维度 / 指标 | BaselineGreedy | FAST (5s) | BALANCED (30s) | OPTIMIZE (60s) | BLK-001 (对照) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **装载箱数 (Placed)** | 42 | 211 | **337** | **313** | 292 |
| **容积利用率 (Util %)** | 5.35% | 28.35% | **36.95%** | **36.03%** | 26.24% |
| **全量硬约束校验 (Valid)** | **True** | **True** | **True** | **True** | True |
| **重叠碰撞对数 (Overlap)** | 0 | 0 | **0** | **0** | 0 |
| **穿透体积 (Penetration)** | 0.0 | 0.0 | **0.0** | **0.0** | 0.0 |
| **越界箱数 (OOB)** | 0 | 0 | **0** | **0** | 0 |
| **主墙终点 (Max X)** | 2.915m | 8.948m | **11.978m** | **11.978m** | 7.219m |
| **过渡区到达 (Reached Transition)** | False | False | **True** | **True** | False |
| **门区到达 (Reached Door Zone)** | False | False | **True** | **True** | False |
| **门区预留实际部署 (Reserve Deployed)**| 0 | 0 | **6** | **6** | 0 |
| **门端最大残余间隙 (Largest Gap)** | 9.117m | 3.084m | **0.122m** | **0.122m** | 4.813m |
| **门截面闭合覆盖率 (Closure Coverage)**| 28.65% | 30.74% | **77.69%** | **70.25%** | 0.0% |
| **门区体积填充率 (Door Occupancy)** | 0.0% | 0.0% | **17.02%** | **17.02%** | 0.0% |
| **门区端面平整度 (Door Flatness)** | 0.0 | 0.0 | **0.8994** | **0.8994** | 0.0 |
| **防倾覆安全比例 (Anti-Toppling)** | 100% | 100% | **100%** | **100%** | 100% |
| **门区就绪状态 (is_door_ready)** | False | False | **True** | **True** | False |
| **门区综合评分 (Readiness Score)** | 20.0 | 20.0 | **72.09** | **72.09** | 0.0 |

---

## 4. 门区部署专项 Telemetry (`BLK002C_DOOR_TRACE.json`)

在 BALANCED 与 OPTIMIZE 模式下，Phase 5 Door Seal 专项遥测数据表现如下：
- `door_phase_started`: **True**
- `door_phase_start_x`: **$11.480\text{m}$**
- `door_anchor_count`: **159** (BALANCED) / **69** (OPTIMIZE)
- `door_candidates_generated`: **6648** (BALANCED) / **2472** (OPTIMIZE)
- `door_candidates_valid`: **363** (BALANCED) / **261** (OPTIMIZE)
- `door_placements_count`: **6**
- `reserve_deployed_by_sku`: `{"SKU-02": 0, "SKU-03": 4, "SKU-04": 2, "SKU-14": 0}`
- `reserve_remaining_by_sku`: `{"SKU-02": 14, "SKU-03": 2, "SKU-04": 8, "SKU-14": 16}`
- `closure_before` $\to$ `closure_after`: **$76.34\% \to 77.69\%$**
- `largest_gap_before` $\to$ `largest_gap_after`: **$0.552\text{m} \to 0.122\text{m}$**
- `door_occupancy_before` $\to$ `door_occupancy_after`: **$0.0\% \to 17.02\%$**
- `door_clearance_margin_m`: **$0.054\text{m}$**（距箱门预留 $5.4\text{cm}$ 安全防擦空间）

---

## 5. 回归测试门禁（Regression Gate）检查结论

- [x] **BALANCED 利用率**: $36.95\% \ge 34.0\%$（通过）
- [x] **OPTIMIZE 利用率**: $36.03\% \ge 34.0\%$（通过）
- [x] **全量硬约束**: `overlap = 0`, `penetration = 0`, `out_of_bounds = 0`, `hard_violations = 0`, `is_valid = true`（通过）
- [x] **门区就绪状态**: BALANCED & OPTIMIZE 均达成 **`is_door_ready = true`**（通过）
- [x] **全量单元测试**: 111 个测试用例 **100% 通过（Ran 111 tests, OK）**

---

## 6. 交付物列表
1. `BLK002C_DOOR_DEPLOYMENT_REPORT.md` — 本交付技术报告
2. `BLK002C_BEFORE_AFTER.json` — 4 种 Solver 模式基准测试前后对比 JSON 数据
3. `BLK002C_DOOR_TRACE.json` — 门区部署专项诊断与几何追踪 JSON 数据
4. `run_blk002c_benchmark.py` — BLK-002C 自动化基准测试与验证入口
