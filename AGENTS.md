# AGENTS.MD — Agent 开发协作规范

> 本文档规范所有参与 3D-AICIVS 项目开发的 AI Agent 的行为边界、职责分工和交付标准。
> 任何 Agent 在开始工作前**必须阅读本文档**。

---

## ⛔ 强制执行声明（Agent 必读 — 最高优先级）

**任何 Agent 在本项目中执行第一个代码修改之前，必须在对话中输出以下确认声明：**

```
📋 AGENTS.MD 合规确认：
1. 我的角色是：[A/B/C/D/E]
2. 本次修改涉及的文件：[文件列表]
3. 这些文件在我的角色权限范围内：[是/否]
4. 本次使用的测试级别：[L1/L2/L3]
5. 我不会在对话中逐个 SKU 打印分析：[确认]
6. 我不会每次微小修改后运行全量 benchmark：[确认]
```

**未输出此声明就开始修改代码的 Agent，其所有修改视为无效。**

### Agent 行为红线（违反任意一条 → 立即停止工作）

```
🚫 连续两次"改代码 → 跑全量测试 → 逐 SKU 分析"循环 → 立即停止，改用批诊断脚本
🚫 单次对话中测试输出超过 50 行 → 立即停止，只摘录 summary 单行
🚫 修改不在自己角色权限内的文件 → 立即停止，说明理由并请求授权
🚫 未经 L1 冒烟验证就运行 L3 全量测试 → 立即停止，按测试阶梯执行
```

---

## 一、核心铁律（所有 Agent 必须遵守）

### 1.1 绝对禁止

```
❌ 禁止在后处理阶段（PASS5 或任何 post-placement 逻辑）中删除已放置的箱子
   → 正确做法：在放置前预检（pre-check gate），拒绝不安全的放置
   
❌ 禁止修改 _has_sufficient_support 的返回值语义
   → z < 1e-3（地面层）永远返回 True，不附加任何额外检查
   
❌ 禁止在一次 PR 中同时修改算法逻辑和稳定性检查
   → 必须分开提交，分别验证

❌ 禁止跳过基准测试就提交算法修改
   → 每次修改必须运行 tests/benchmark_suite.py 并对比前后数据

❌ 禁止通过“塞满弹性件”牺牲刚性SKU履行率来虚增利用率 (Priority Inversion)
   → 刚性SKU未装完时，弹性件放入量必须受控，严禁丢弃小件/刚性件装弹性件

❌ 禁止出现任何 SKU 饥饿/弃装 (SKU Starvation)
   → 任何指定要装的SKU（required > 0）放置数不得为 0

❌ 禁止在对话中逐个 SKU 交互式打印日志排查 (Token Waste)
   → 必须统一使用本地诊断工具进行批量提取与分析，严禁将大量上下文与 Token 浪费在单点逐个 SKU 查询上

❌ 禁止创建 > 500 行的新文件
   → 超过 500 行必须拆分为多个模块

❌ 禁止在 backend/ 中使用 from src. 导入
```

### 1.2 必须遵守

```
✅ 任何算法修改前，先记录当前基准数据（利用率、刚性履行率、放入数、violations）
✅ 任何算法修改后，运行基准并在 commit message 中包含对比数据
✅ 排查 SKU 漏装、履约率与倒挂问题时，必须优先运行本地批诊断脚本提取全貌
✅ 修改 unified_solver.py 前，必须说明修改的具体 PASS/方法和行号范围
✅ 优先保证所有刚性SKU 100% 装载，在满足物理/业务约束前提下提升空间利用率
✅ 新增模块必须有 docstring 说明用途、输入/输出、被谁调用
✅ 所有报告和注释使用中文
```

---

## 二、Agent 角色定义

### 🔧 角色 A: 算法工程师

**职责**: 优化装柜利用率和放入数量

**可触碰的文件**:
- `backend/solver_v2/solver/unified_solver.py` 的算法逻辑（PASS 1-4, 试算策略, headroom relay）
- `backend/solver_v2/solver/composite_strip.py` — 截面宽度引擎
- `backend/solver_v2/solver/gap_filler.py` — 间隙填充
- `backend/solver_v2/solver/compaction.py` — 缩紧优化
- `backend/solver_v2/solver/swap_optimizer.py` — 交换启发
- `backend/solver_v2/solver/elastic_recovery.py` — 弹性恢复
- `backend/solver_v2/solver/scorer.py` — 评分器

**禁止触碰**:
- `_has_sufficient_support`, `_check_cog_projection`, `_check_lateral_stability` — 稳定性工程师专属
- `validation/independent_validator.py` — 验证器不可修改
- `stability/` 目录 — 稳定性工程师专属

**交付标准**:
```
刚性SKU履行率不得低于当前基准 (严禁倒挂，优先 100%)
饥饿SKU数必须保持 0 (严禁弃装指定货物)
利用率不得低于当前基准 -2%
violations 必须保持 0 (含承重/层数/朝向/顶叠/落地)
碰撞必须保持 0
放入数不得低于当前基准 -5 箱
```

---

### 🛡️ 角色 B: 稳定性工程师

**职责**: 倾覆安全、支撑检查、物理约束

**可触碰的文件**:
- `backend/solver_v2/stability/` — 全部
- `unified_solver.py` 的稳定性方法: `_has_sufficient_support`, `_check_cog_projection`, `_check_lateral_stability`, `_is_placement_tipping_safe`
- `unified_solver.py` 的 PASS 5 区域（L1358-1373）
- `validation/independent_validator.py` 的稳定性检查部分

**核心约束**:
```
⚠️ 修改稳定性参数（阈值、margin_ratio 等）必须说明物理依据
⚠️ 任何拒绝逻辑必须在放置前（pre-check），不在放置后（post-removal）
⚠️ 修改后利用率下降不得超过 3%
⚠️ 如果利用率下降超过 1%，必须提供替代朝向方案
```

**禁止**:
- 删除已放置的箱子（`placements.pop()`, `placements.remove()` 等）
- 修改 PASS 1-4 的算法逻辑
- 修改试算策略列表

---

### 🧪 角色 C: 测试工程师

**职责**: 测试覆盖、基准维护、回归守护

**可触碰的文件**:
- `tests/` — 全部
- `config/` — 测试配置

**交付标准**:
```
新增测试必须使用 pytest 框架
新增测试必须可在 60s 内完成
基准测试修改后必须更新 benchmark_results.json
```

---

### 🎨 角色 D: 前端工程师

**职责**: 3D 可视化、用户交互、API 集成

**可触碰的文件**:
- `frontend/src/` — 全部
- `index.html`
- `backend/server.py` — 仅 API 路由层

**禁止**:
- 修改 `solver_v2/` 下的任何算法文件
- 修改 `validation/` 下的任何文件

---

### 📐 角色 E: 架构审计

**职责**: 代码结构、模块拆分、文档同步

**可触碰的文件**:
- `docs/` — 全部
- `README.md`
- 模块 `__init__.py` 文件
- 文件拆分重构（需先提出方案获批准）

**核心任务**:
- 保持文档与实际代码一致
- 识别并标记孤岛代码
- 审查跨 Agent 的修改冲突

---

## 三、文件所有权矩阵

| 文件/目录 | 角色A(算法) | 角色B(稳定) | 角色C(测试) | 角色D(前端) | 角色E(架构) |
|:---|:---:|:---:|:---:|:---:|:---:|
| solver/unified_solver.py (PASS 1-4) | ✅ | ❌ | ❌ | ❌ | ❌ |
| solver/unified_solver.py (稳定性方法) | ❌ | ✅ | ❌ | ❌ | ❌ |
| solver/unified_solver.py (PASS 5) | ❌ | ✅ | ❌ | ❌ | ❌ |
| solver/composite_strip.py | ✅ | ❌ | ❌ | ❌ | ❌ |
| stability/ | ❌ | ✅ | ❌ | ❌ | ❌ |
| validation/ | ❌ | ✅ | ❌ | ❌ | ❌ |
| tests/ | 🔵 | 🔵 | ✅ | 🔵 | ❌ |
| frontend/src/ | ❌ | ❌ | ❌ | ✅ | ❌ |
| docs/ | ❌ | ❌ | ❌ | ❌ | ✅ |
| server.py | ❌ | ❌ | ❌ | ✅ | ❌ |

> 🔵 = 可读、可添加测试，不可修改已有代码

---

## 四、分支与交接策略

### 4.1 分支命名

```
feat/algo-<描述>      — 算法工程师
feat/stab-<描述>      — 稳定性工程师
feat/test-<描述>      — 测试工程师
feat/ui-<描述>        — 前端工程师
refactor/arch-<描述>  — 架构审计
fix/<模块>-<描述>      — 紧急修复
```

### 4.2 Commit Message 格式

```
<type>(<scope>): <简述>

Benchmark: 14-SKU <利用率>% (刚性履行: <刚性率>%, 放入 <箱数>箱) / violations: <数量> / health: <健康状态>
Changed: <修改的方法/PASS 列表>
```

示例:
```
feat(solver): add section-width knapsack engine

Benchmark: 14-SKU 88.02% (刚性履行: 98.5%, 放入 2092箱) / violations: 0 / health: HEALTHY
Changed: _solve_single_trial PASS1, composite_strip.py
```

### 4.3 交接协议

当一个 Agent 完成工作并交接给下一个 Agent 时，必须提供：

```markdown
## 交接清单
- [ ] 修改文件列表及行号范围
- [ ] 基准对比数据（前 vs 后，含利用率、刚性履行率、弹性完成率）
- [ ] 饥饿SKU排查结果（必须为 0）
- [ ] 约束合规审计（承重/层数/朝向/顶叠/落地/门区）
- [ ] 已知的遗留问题/风险
- [ ] 未完成的待办事项
- [ ] 对后续 Agent 的建议/约束
```

---

## 五、测试门禁与 Token 节约铁律

### 5.1 三级测试阶梯（严格按级执行，禁止跳级）

| 级别 | 何时触发 | 命令 | 耗时 | 说明 |
|:---:|:---|:---|:---:|:---|
| **L1** | 每次代码修改后 | 见下方 | <30s | 冒烟验证：只确认不崩溃 |
| **L2** | L1 通过 + 修改了算法逻辑 | 见下方 | 30-60s | 核心基线：单用例验证关键指标 |
| **L3** | 准备提交或交接时 | 见下方 | 5-10min | 全量回归：15 用例完整审计 |
| **L4** | 重大重构/发布前/批量归因 | 见下方 | 10-30min | 平台级大规模工况与随机对抗压测 (100~300+用例) |

**L1 冒烟测试**（每次修改后必跑）：
```bash
python -c "from backend.solver_v2 import solve; print('import OK')"
```

**L2 核心基线**（算法修改后跑）：
```bash
python scripts/batch_sku_diagnostic.py --case "14-SKU"
```

**L3 全量回归**（仅提交/交接时跑一次）：
```bash
python tests/benchmark_suite.py --run
python tests/regression_guard.py
```

**L4 平台级测试与故障归因**（扩展至 100~300+ 生产级与随机工况）：
```bash
# Tier 1: 核心 100 用例自动化闭环（自动运行、归因并输出精简报告）
python scripts/test_harness/runner.py --tier 1

# 指定特定约束或柜型批量诊断
python scripts/test_harness/runner.py --tags door,bearing
python scripts/test_harness/runner.py --container 20GP,45HQ

# 增量模式（只跑发生变动的用例）
python scripts/test_harness/runner.py --incremental
```

> ⚠️ **禁止跳级**：不准跳过 L1 直接跑 L3/L4。不准每次微小修改后跑 L3/L4。

### 5.2 Token 节约绝对禁止事项

```
❌ 禁止每次微小修改后运行全量 benchmark_suite.py（15 用例 × 17-72 秒）
   → 正确做法：L1 冒烟通过后仅跑 L2 单用例

❌ 禁止在对话中逐个 SKU、逐个立方块打印分析
   → 正确做法：运行 batch_sku_diagnostic.py 一次性输出全貌

❌ 禁止将 benchmark 完整输出（数千行 JSON）粘贴到对话中
   → 正确做法：只摘录 summary 段的关键指标（见 5.3 格式）

❌ 禁止循环"改一行 → 跑全量 → 逐SKU分析 → 再改一行"
   → 正确做法：积攒一批相关修改 → L1 → L2 → 确认方向正确 → 继续积攒

❌ 禁止在对话中输出超过 50 行的测试/诊断原始输出
   → 正确做法：摘录关键行，其余说"详见终端输出"
```

### 5.3 诊断输出格式规范（Agent 在对话中报告结果时必须使用此格式）

Agent 在对话中报告测试结果时，**只允许**输出以下单行格式：

```
L1 结果: import OK ✅
L2 结果: 14-SKU | 利用率 85.0% | 刚性 100% | 弹性 12.3% | 违规 0 | 碰撞 0 | HEALTHY ✅
L3 结果: 15用例 | 14 PASS / 1 WARN | 全局碰撞 0 | 倒挂 0 | 饥饿 0 ✅
```

如需报告异常，额外附加**最多 5 行**异常摘要：
```
⚠️ 异常: TALL-SLENDER-TIPPING | 刚性 41.67% | 饥饿 2 SKU | PRIORITY_INVERSION
⚠️ 异常: 45HQ-EXTENDED | 违规 7 | VIOLATED
```

**严禁输出原始 JSON、完整 SKU 列表、逐箱坐标等大段内容。**

### 5.4 SKU 漏装与倒挂批量诊断规范

严禁在 Agent 对话中逐个 SKU 打印日志排查。分析漏装与优先级倒挂问题时，必须直接运行统一诊断脚本：

```bash
# 全量用例诊断
python scripts/batch_sku_diagnostic.py

# 单个或指定用例诊断（支持模糊匹配）
python scripts/batch_sku_diagnostic.py --case "14-SKU"
```

该工具将自动汇总并清晰输出：
- 空间利用率、刚性履行率、弹性完成率
- 0 碰撞与 0 约束违规审计状态
- 优先级倒挂判定（刚性未满 99% 时是否有弹性件抢占）
- 所有未满载 SKU 列表、缺额件数与所属类型（刚性/弹性）
- 严重饥饿/弃装 SKU 清单

### 5.5 回归守护

```bash
python tests/regression_guard.py
```

满足以下任一条件立即**阻止提交/拒绝合并**：
- 刚性SKU履行率出现倒挂（刚性未满先塞弹性件）
- 出现饥饿/弃装SKU（`starved_skus > 0`）
- 利用率低于基准 2%
- violations > 0 或 碰撞 > 0

---

## 六、当前活跃代码地图（Agent 必读）

```
backend/solver_v2/
├── __init__.py               ← solve() 入口
├── solver/
│   ├── unified_solver.py     ← ⚠️ 核心引擎 (1777行)
│   ├── composite_strip.py    ← 截面宽度引擎 (49KB)
│   ├── compaction.py         ← 缩紧后处理
│   ├── swap_optimizer.py     ← 交换启发
│   ├── gap_filler.py         ← 间隙填充
│   ├── elastic_recovery.py   ← 弹性恢复
│   ├── scorer.py             ← 评分器
│   └── baseline_solver.py    ← SolverSolution 数据类
├── stability/
│   └── tipping_moment.py     ← PASS5 倾覆审计
├── geometry/
│   ├── aabb.py               ← 包围盒
│   └── spatial_index.py      ← 空间哈希索引
├── validation/
│   └── independent_validator.py ← 10维验证器 (57KB)
└── domain/
    └── models.py             ← 所有数据模型 (21KB)
```

> 以上是**活跃调用路径**涉及的文件。
> 
> ### ⚠️ 方案 C 架构隔离铁律（冻结目录清单）
> 以下目录属于历史实验模块与独立测试用例，**当前主算柜链路未被调用，处于严格冻结状态**：
> - `backend/solver_v2/search/` (包括 `engine.py`, `beam.py` 等)
> - `backend/solver_v2/topfill/` (包括 `planner.py`, `terminal_repair.py` 等)
> - `backend/solver_v2/world/` (包括 `state.py` 等)
> - `backend/solver_v2/loading/` (包括 `planner.py` 等)
> - `backend/solver_v2/door/` (包括 `closure_planner.py` 等)
> - `backend/solver_v2/structure/` (包括 `wall_model.py`, `cavity_classifier.py` 等)
> 
> **所有 Agent 必须遵守**:
> 1. ❌ 严禁在上述冻结模块中编写新代码或新增依赖。
> 2. ❌ 严禁在 `unified_solver.py` 中引用这些冻结模块（避免引入死锁与计算爆炸）。
> 3. ✅ 所有业务逻辑、装载算法优化与倾覆防范，必须严格在【活跃调用路径】所列模块中闭环解决。
> 4. 待核心算法达标稳定后，由架构审计 Agent 统一将冻结代码迁移到 `_archive/` 目录。
