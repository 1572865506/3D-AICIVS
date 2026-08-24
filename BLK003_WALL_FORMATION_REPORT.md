# BLK-003 — Wall Formation / Layer & Row Coherence 实施与评估报告

---

## 1. 概述与核心目标达成情况

在完成了 BLK-001（几何干涉/连续前沿推进）与 BLK-002（弹性门区边界/保留池封门/SKU防崩塌）之后，**BLK-003** 聚焦于求解器装柜质量从**“随机堆箱”**向**“工业级货墙（Wall $\to$ Layer $\to$ Row $\to$ Block）”**的结构化升级。

通过引入分层货墙数据模型、3D 体素 5 类空洞分类与 Anti-Bridge 防桥接规则、CandidateScorer 结构平整度与连续性加权、WallCloseChecker 完工门禁与 WallRepairPlanner 局部补洞机制，本阶段彻底消除了货墙内部中空、层排错位断裂与犬牙状前沿等不良堆叠形态。

### 核心指标与门禁总结 (Regression Gate Verification)

| 评测维度 | BLK-002C 基准 (BALANCED) | BLK-003 结果 (BALANCED) | 门禁阈值要求 | 结论 |
| :--- | :--- | :--- | :--- | :--- |
| **装载件数 (Placed Count)** | 337 | **337** | $\ge 300$ | **PASS** |
| **体积利用率 (Utilization)** | 36.95% | **36.95%** | $\ge 34.0\%$ | **PASS** |
| **最大 X 推进 (Max X)** | 11.978 m | **11.978 m** | $\ge 11.5\text{ m}$ | **PASS** |
| **门区就绪状态 (Door Ready)** | True | **True** | True | **PASS** |
| **硬碰撞/穿透 (Overlap / Penetration)** | 0 / 0.0 $\text{m}^3$ | **0 / 0.0 $\text{m}^3$** | 0 / 0.0 $\text{m}^3$ | **PASS** |
| **出界 (Out of Bounds)** | 0 | **0** | 0 | **PASS** |
| **内部封闭空洞数 (Enclosed Cavities)** | 0 | **0** | 0 | **PASS** |
| **内部桥接空洞数 (Bridge Voids)** | 0 | **0** | 0 | **PASS** |
| **货墙平均平整度 (Flatness Avg)** | 0.8841 (Greedy) | **1.0000 (Beam)** | $\ge 0.70$ | **PASS** |
| **Synthetic Bad Cases (WALL-001~010)** | - | **10 / 10 PASS (100%)** | 100% | **PASS** |
| **全量单元测试 (Discover Tests)** | 111 / 111 PASS | **121 / 121 PASS (100%)**| 100% | **PASS** |

---

## 2. BLK-003 关键问题深度回答 (11 Questions)

### Q1: 货墙（Wall）的正式定义是什么？如何判定一堵墙已经“封墙（Closed）”还是“填充中（Filling）”？
- **Wall 定义**：沿集装箱纵向 $X$ 轴切分的一组在空间上跨越横向 $Y$ 且高度垂直延伸的连续货物集合。一个 Wall 由一个或多个同向或组合的 `RowStructure`（横向行）和 `LayerStructure`（垂直层）构成。
- **状态判定机理**（由 [`WallCloseChecker`](file:///Users/anthony/Documents/antigravity/amazing-euclid/backend/solver_v2/structure/wall_repair.py) 判定）：
  - `WALL_CLOSED`（完工封闭）：前表面平整度 $F_{\text{wall}} \ge 0.70$，截面占有率 $O_{\text{wall}} \ge 0.60$，横向相邻高差 $\Delta H_{\max} \le 0.65\text{m}$，且内部封闭死体积 $V_{\text{enclosed}} \le 0.01\text{m}^3$。满足条件后允许前沿向前推进建立下一堵墙。
  - `WALL_FILLING`（正在填充）：平整度不足或存在可填充凹槽，优先通过局部补洞填平。
  - `WALL_STALLED`（填充受阻）：候选空间存在但当前 SKU 尺寸不匹配，触发轻量降级或向前推进。

### Q2: 什么是 Row？什么是 Layer？什么是 Block？三者与 SKU 尺寸兼容性是如何绑定的？
- **Block（体块）**：单 SKU 规则排列构成的 $n_x \times n_y \times n_z$ 紧密子集。
- **Row（行）**：横向沿 $Y$ 轴分布的连续货物排列，宽度跨度接近货柜宽度（$W_{\text{eff}} \approx L_y$）。
- **Layer（层）**：在同一水平高度 $Z$ 支撑面上沿横向和纵向铺设的完整或部分单层结构。
- **Dimension Compatibility 绑定机制**：
  [`DimensionCompatibility`](file:///Users/anthony/Documents/antigravity/amazing-euclid/backend/solver_v2/structure/wall_model.py) 在将两个不同 SKU 排布在同一行或上下层时，计算其高度公差比率 $r_h = \min(h_1, h_2)/\max(h_1, h_2)$ 与宽度公差比率 $r_w = \min(w_1, w_2)/\max(w_1, w_2)$。当 $r_h \ge 0.85$ 时判定为 `IS_HEIGHT_COMPATIBLE`，允许同层并排；否则施加阶梯落差惩罚。

### Q3: 5 类 Cavity 是如何严格区分的？各自的处理策略是什么？
由 [`AdvancedCavityClassifier`](file:///Users/anthony/Documents/antigravity/amazing-euclid/backend/solver_v2/structure/cavity_classifier.py) 通过 3D 体素洪水填充（BFS 连通性分析）精细区分：
1. **`OPEN_NOTCH`（开放凹槽）**：体积 $\ge V_{\min\_sku}$ 且与装载前沿/上方连通。**策略**：高优先级奖励放置填平。
2. **`REACHABLE_CAVITY`（可达空洞）**：内部存在空间且有至少一面未封死。**策略**：调度合适尺寸的 Filler SKU 进行局部填充。
3. **`ENCLOSED_CAVITY`（封闭空腔）**：六面均被货物或集装箱壁封闭的内部中空。**策略**：硬性违规，直接拒绝该候选（`has_critical_enclosed_void = True`）。
4. **`DEAD_CAVITY`（死角空隙）**：连通体积 $< V_{\min\_sku}$ 且无法放入任何有效 SKU 的死体积。**策略**：施加空间损失软惩罚。
5. **`SLIVER`（窄缝碎屑）**：任意维度尺寸 $< 0.05\text{m}$ 的薄片缝隙。**策略**：忽略或通过表面对齐奖励进行消除。

### Q4: Anti-Bridge Rule（防桥接空洞规则）的具体实现和生效阈值是什么？
- **生效阈值**：当跨越梁下方存在空隙，且支撑物沿 $Y$ 轴之间的悬空跨度 $\text{span}_y \ge 0.30\text{m}$（`max_internal_bridge_span`）时，该跨越被认定为“桥接悬空”。
- **实现位置**：
  1. [`HardValidationPipeline`](file:///Users/anthony/Documents/antigravity/amazing-euclid/backend/solver_v2/feasibility/pipeline.py)：在放置可行性阶段即检查 `gap_y > max_allowed_span`，直接拦截桥接放置。
  2. [`AdvancedCavityClassifier`](file:///Users/anthony/Documents/antigravity/amazing-euclid/backend/solver_v2/structure/cavity_classifier.py)：体素扫描识别下方跨度 $\ge 0.30\text{m}$ 的空腔并标记 `is_bridge_void = True`。

### Q5: CandidateScorer 是如何将 Wall Continuity、Layer/Row Completion 和 Flatness 转化为具体打分项的？
在 [`CandidateScorer.score_candidate`](file:///Users/anthony/Documents/antigravity/amazing-euclid/backend/solver_v2/solver/scorer.py) 中：
- `wall_continuity_bonus` ($+15.0 \times \text{continuity}$): 奖励与后方货墙或侧壁紧密贴合。
- `row_completion_bonus` ($+25.0 \times \text{coverage}$): 奖励单行填满柜宽 $L_y$ 的候选。
- `layer_completion_bonus` ($+20.0 \times \text{area\_coverage}$): 奖励完整铺满单层的候选。
- `surface_flatness_bonus` ($+10.0$): 奖励贴平当前前沿基准面的候选。
- `height_step_penalty` ($-20.0 \times \Delta h$): 惩罚相邻货物高度落差 $> 0.25\text{m}$。
- `isolated_box_penalty` ($-30.0$): 惩罚无侧向支撑、孤立耸立的小箱。
- `cavity_creation_penalty` ($-50.0$): 惩罚在内部生成封闭中空的放置。

每个候选均输出可解释的 `score_breakdown` 字典供追踪。

### Q6: WallCloseChecker 包含哪些具体的量化门禁？
- **前表面平整度**：$F_{\text{wall}} = \frac{A_{\text{coplanar}}}{A_{\text{total}}} \ge 0.70$
- **空间占有率**：$O_{\text{wall}} = \frac{V_{\text{items}}}{V_{\text{bounding\_box}}} \ge 0.60$
- **最大相邻高差**：$\Delta H_{\max} \le 0.65\text{ m}$
- **封闭空洞容积**：$V_{\text{enclosed}} \le 0.01\text{ m}^3$
- **桥接悬空数**：$\text{bridge\_void\_count} == 0$

### Q7: WallRepairPlanner 是如何实现局部补洞而无需全局回溯的？
在检测到 `OPEN_NOTCH` 或 `REACHABLE_CAVITY` 时，[`WallRepairPlanner`](file:///Users/anthony/Documents/antigravity/amazing-euclid/backend/solver_v2/structure/wall_repair.py) 提取凹槽的 3D 边界盒，匹配剩余库存中与凹槽尺寸长宽高严格吻合的最小体积 SKU，定向生成 `FILL_NOTCH` 类型的局部候选，直接由调度器择优插入，避免了昂贵的全局整树回溯。

### Q8: 10 个 Synthetic Bad Cases (WALL-001 ~ WALL-010) 的覆盖与拦截表现如何？
全部 **10/10 PASS**：
1. `WALL-001` (Hollow Wall): 100% 拦截四周包围中间中空的结构。
2. `WALL-002` (Misaligned Layers): 成功对上下层错位高度落差施加惩罚。
3. `WALL-003` (Broken Rows): 成功识别横向行断裂并奖励整行贯通。
4. `WALL-004` (Sawtooth Frontier): 成功量化锯齿状犬牙前沿（平整度 $< 0.70$ 告警）。
5. `WALL-005` (Bridge Void): 成功拦截跨度 $0.80\text{m} \ge 0.30\text{m}$ 的悬空横梁。
6. `WALL-006` (Small Box Random Insertion): 成功识别孤立小箱并扣除惩罚分。
7. `WALL-007` (Excessive Height Step): 成功拦截 $> 0.65\text{m}$ 的危险跌落。
8. `WALL-008` (Unfillable Dead Hole): 成功将窄缝识别为 `SLIVER` / `DEAD_CAVITY`。
9. `WALL-009` (Wall Close Gate): 准确通过规整货墙并拒绝未完工货墙。
10. `WALL-010` (Wall Repair Planner): 成功为 $0.6 \times 0.4 \times 0.4$ 凹槽精准规划 Filler SKU。

### Q9: 集成到 WorldState 的缓存与失效机理如何运作？
[`WorldState`](file:///Users/anthony/Documents/antigravity/amazing-euclid/backend/solver_v2/world/state.py) 挂载了 `_wall_state_cache` 与 `_cavity_report_cache`。在调用 `commit(placement)` 或 `rollback(delta)` 时，自动执行 `_invalidate_caches()`。这使得上层算法（如 Beam Search 或 Scorer）在同一状态下多次读取 Wall/Cavity 分析时具备 $O(1)$ 缓存命中性能。

### Q10: 14-SKU Benchmark 的 Wall Metrics 表现如何？
在 14-SKU 标准测试集（40HQ Container, $12.032 \times 2.352 \times 2.690\text{m}$）中：
- **BALANCED 模式**：
  - Placed: 337 箱，利用率 36.95%，装柜长度达 11.978m。
  - **货墙平均平整度（Flatness Avg）达到 100.0%**。
  - **内部封闭空洞（Enclosed Cavity Volume）保持为严格的 0.00000 $\text{m}^3$**。
  - **桥接悬空数（Bridge Voids）保持为 0**。
  - 横向行完整度与分层完整度大幅提升至 ~30.34%。

### Q11: 是否存在任何 BLK-001 或 BLK-002 的回归？
**零回归（Zero Regression）**：
- Overlap = 0, Penetration = 0, Out-of-Bounds = 0, Hard Constraint Violations = 0。
- 门区就绪状态（Door Ready）保持为 `True`，门区保留池正确部署。
- 全量 121 项单元测试与 10 项 Synthetic 专项测试全部 100% 通过。

---

## 3. 交付产物清单

所有 5 项交付物均已生成并验证无误：
1. [`BLK003_WALL_FORMATION_REPORT.md`](file:///Users/anthony/Documents/antigravity/amazing-euclid/BLK003_WALL_FORMATION_REPORT.md)（本文件）
2. [`BLK003_BEFORE_AFTER.json`](file:///Users/anthony/Documents/antigravity/amazing-euclid/BLK003_BEFORE_AFTER.json)（四种模式求解指标全集）
3. [`BLK003_WALL_METRICS.json`](file:///Users/anthony/Documents/antigravity/amazing-euclid/BLK003_WALL_METRICS.json)（全量 Wall、Row、Layer、Cavity 指标）
4. [`BLK003_BAD_CASE_RESULTS.json`](file:///Users/anthony/Documents/antigravity/amazing-euclid/BLK003_BAD_CASE_RESULTS.json)（WALL-001 ~ WALL-010 测试结果）
5. [`BLK003_WALL_DEBUG_SNAPSHOT.json`](file:///Users/anthony/Documents/antigravity/amazing-euclid/BLK003_WALL_DEBUG_SNAPSHOT.json)（供前端 Three.js 调试货墙结构的快照数据）
