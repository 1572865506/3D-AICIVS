# 方案A实施计划：多目标CP-SAT优化 + 迭代验证循环

## 📋 项目概述

**目标**：将三阶段混合求解器从"单点调优"模式转变为"自适应泛化"架构，通过前置验证约束和迭代反馈机制，打破当前的优化循环陷阱。

**核心策略**：
- 在CP-SAT阶段注入质量约束（紧凑度、重心稳定性）
- 构造式放置增加实时验证和回溯能力
- 建立solve-validate-adjust迭代循环

**预期成果**：
- 刚性履约率保持 ≥99%
- 空腔体积从>10m³降至<5m³（40HQ容器10%阈值：6.77m³）
- 倾倒安全系数SF≥2.0达标率>95%
- 跨SKU组合泛化能力：50个生产失败案例通过率≥80%

---

## 🗓️ 三阶段实施路线图

### 第一阶段：CP-SAT多目标优化（Week 1-2）

#### 里程碑1.1：紧凑度目标函数（3天）

**目标**：在CP-SAT宏观分配阶段惩罚孤立空腔，优先生成紧密布局。

**技术实现**：
```python
# backend/solver_v2/solver/cpsat_engine.py

def _add_compactness_objective(self):
    """
    新增目标：最小化未占用体积的空间碎片化
    方法：3D连通域分析 - 惩罚孤立的未占用区域
    """
    # 1. 网格占用标记
    # 2. 洪水填充算法统计孤立空腔数量
    # 3. 添加软约束：isolated_voids * 1000
```

**修改文件**：
- `backend/solver_v2/solver/cpsat_engine.py` (添加 `_add_compactness_objective()`)
- `backend/solver_v2/solver/cpsat_hybrid_solver.py` (调用新目标函数)

**验证标准**：
- 在14-SKU案例上空腔体积 <8m³
- 求解时间增幅 <100%（从当前~15s到<30s）
- 刚性履约率仍保持99%+

**回滚方案**：若求解时间>60s或刚性履约率<98%，降低紧凑度权重或暂时禁用。

---

#### 里程碑1.2：重心稳定性约束（3天）

**目标**：在CP-SAT阶段强制重心前倾，确保dx/dz>0.25（预留安全裕度）。

**技术实现**：
```python
# backend/solver_v2/solver/cpsat_engine.py

def _add_center_of_mass_constraint(self):
    """
    硬约束：强制质心偏移比 dx/dz > 0.25
    适用场景：0.5g前向减速下的防倾倒验证（SF=2.0）
    """
    # 1. 计算累积重心坐标 (cx, cz)
    # 2. 添加线性约束：cx - 0.25*cz > container_length * 0.1
```

**修改文件**：
- `backend/solver_v2/solver/cpsat_engine.py` (添加 `_add_center_of_mass_constraint()`)
- `backend/solver_v2/solver/constructive_placer.py` (移除冗余的事后倾倒检查)

**验证标准**：
- 所有案例倾倒安全系数SF≥1.8（留20%裕度）
- 不引入新的刚性件漏装

**回滚方案**：若无解案例>2个，放宽约束至dx/dz>0.15。

---

#### 里程碑1.3：多目标权重调优（3天）

**目标**：平衡刚性履约、紧凑度、重心稳定性三者的权重系数。

**当前权重配置**：
```python
# 初始权重方案
objective = (
    10000 * rigid_fulfillment_score  # 刚性优先级最高
    + 1000 * compactness_score        # 紧凑度次之
    + 100 * com_stability_score       # 重心稳定性垫底
)
```

**调优方法**：
1. 在15个基准案例上网格搜索（刚性权重固定10000，紧凑度1000-5000，重心50-500）
2. 帕累托前沿分析：刚性履约率 vs 空腔体积 vs 求解时间
3. 选择"无明显短板"的权重组合

**验证标准**：
- 15个基准案例全部通过（刚性≥99%，空腔<8m³，SF≥1.8）
- 求解时间中位数<40s

**交付物**：
- 权重配置常量写入 `cpsat_engine.py`
- 调优报告（Markdown格式）记录帕累托曲线和最终选择理由

---

### 第二阶段：构造式放置回溯机制（Week 3）

#### 里程碑2.1：增量空腔检测（2天）

**目标**：在构造式放置的每一步后，实时计算新增空腔体积。

**技术实现**：
```python
# backend/solver_v2/solver/constructive_placer.py

def _place_box_with_cavity_check(self, box, position):
    """
    放置SKU后立即检测：
    1. 从门侧平面执行3D洪水填充
    2. 统计不可达空腔体积（与放置前差值）
    3. 若增量空腔>阈值，标记为"危险放置"
    """
    # 返回：(placement_success, incremental_cavity_volume)
```

**修改文件**：
- `backend/solver_v2/solver/constructive_placer.py` (新增 `_place_box_with_cavity_check()`)
- `backend/solver_v2/validation/independent_validator.py` (复用 `_compute_cavity_volume()`)

**验证标准**：
- 检测开销 <5%总求解时间
- 与全局验证器的空腔计算结果误差<1m³

---

#### 里程碑2.2：回溯搜索树（3天）

**目标**：若某步放置导致空腔爆炸，撤销最后N步并尝试备选位置。

**技术实现**：
```python
# backend/solver_v2/solver/constructive_placer.py

class PlacementState:
    """快照：已放置SKU列表、网格占用状态、累积空腔"""
    
def _backtrack_and_retry(self, depth=3):
    """
    回溯策略：
    1. 弹出最后3个放置
    2. 对每个SKU尝试次优位置（按空腔增量排序）
    3. 若所有分支均失败，返回最优子树
    """
```

**修改文件**：
- `backend/solver_v2/solver/constructive_placer.py` (新增 `PlacementState` 和回溯逻辑)

**验证标准**：
- 在"异构混合型"案例上空腔体积下降>30%
- 回溯触发率<20%（避免过度搜索）

**回滚方案**：若回溯导致求解时间>120s，禁用回溯并回退到里程碑1.3版本。

---

### 第三阶段：迭代验证闭环（Week 4）

#### 里程碑3.1：验证阈值配置（1天）

**目标**：在UnifiedSolver中启用验证器的阈值强制检查。

**技术实现**：
```python
# backend/solver_v2/solver/unified_solver.py (Line 320, 380)

validation_result = self.validator.validate(
    placed_skus,
    max_allowed_cavity_volume=6.77,  # 40HQ的10%
    min_safety_factor=2.0
)
```

**修改文件**：
- `backend/solver_v2/solver/unified_solver.py` (2处validate()调用)
- `tests/benchmark_suite.py` (line 377, 传递验证选项)

**验证标准**：
- 当前15个案例在严格阈值下的通过率（预期8-12个通过）
- 失败案例的违规维度分布（空腔 vs 倾倒 vs 碰撞）

---

#### 里程碑3.2：迭代调整机制（3天）

**目标**：若首次solve失败，提取违规特征并自动调整CP-SAT权重后重试。

**技术实现**：
```python
# backend/solver_v2/solver/unified_solver.py

def solve_with_adaptive_retry(self, max_iterations=3):
    """
    迭代流程：
    1. 初始权重求解
    2. 验证 → 若通过则返回
    3. 若失败：
       - 空腔超标 → 紧凑度权重 ×2
       - 倾倒风险 → 重心约束收紧10%
       - 碰撞 → 降低求解时间限制（强制CP-SAT更保守）
    4. 重新求解，最多3次
    """
```

**修改文件**：
- `backend/solver_v2/solver/unified_solver.py` (新增 `solve_with_adaptive_retry()`)
- `backend/solver_v2/solver/cpsat_engine.py` (支持运行时权重覆盖)

**验证标准**：
- 15个基准案例通过率≥13个（≥86%）
- 收敛速度：90%案例在2次迭代内通过

---

#### 里程碑3.3：生产案例泛化测试（2天）

**目标**：在50个真实失败案例上验证系统泛化能力。

**测试流程**：
1. 从生产日志/用户反馈中提取50个失败装柜案例（需用户提供）
2. 转换为benchmark格式：`tests/production_cases/*.json`
3. 执行批量测试：`python scripts/batch_sku_diagnostic.py --case production`
4. 分析失败模式：SKU尺寸分布、刚性比例、容器类型

**成功标准**：
- 通过率≥40个（80%）
- 失败案例中，"无解"（本质无法装入）占比>50%
- 剩余失败案例提取共性特征，作为下一轮优化方向

**交付物**：
- 生产案例测试报告（Markdown）
- 失败案例根因分析（按SKU模式分类）

---

## 📊 关键指标与监控

### 北极星指标
| 指标 | 当前值 | 阶段1目标 | 阶段2目标 | 阶段3目标 |
|------|--------|-----------|-----------|-----------|
| 刚性履约率 | 99%+ | 99%+ | 99%+ | 99%+ |
| 空腔体积(40HQ) | >10m³ | <8m³ | <6m³ | <5m³ |
| 倾倒安全系数 | 80%达标 | 90%达标 | 95%达标 | 98%达标 |
| 求解时间(中位数) | 15s | <40s | <60s | <45s |
| 生产案例通过率 | <50% | N/A | N/A | ≥80% |

### 回归测试
每个里程碑完成后，运行完整基准套件：
```bash
python scripts/batch_sku_diagnostic.py
```
通过标准：15个案例中≥14个PASS（允许1个边界case失败）。

---

## 🚨 风险与缓解

### 风险1：求解时间爆炸
- **触发条件**：CP-SAT多目标优化导致搜索空间指数增长
- **缓解措施**：
  - 设置硬超时：60s/案例
  - 若超时，回退到"紧凑度目标禁用"模式
  - 考虑引入"快速预检"：小网格分辨率预估可行性

### 风险2：刚性履约率下降
- **触发条件**：新增约束导致CP-SAT无解或次优解
- **缓解措施**：
  - 刚性权重始终保持10000x（不可妥协）
  - 若无解，自动放宽紧凑度/重心约束而非降低刚性优先级

### 风险3：回溯陷入局部最优
- **触发条件**：构造式放置的搜索树分支因子过大
- **缓解措施**：
  - 限制回溯深度≤3步
  - 每个分支点最多尝试5个备选位置
  - 若回溯耗时>30s，强制终止并接受当前最优解

---

## 📦 交付物清单

### 代码变更
- [ ] `backend/solver_v2/solver/cpsat_engine.py` - 紧凑度目标、重心约束、权重覆盖接口
- [ ] `backend/solver_v2/solver/cpsat_hybrid_solver.py` - 调用新目标函数
- [ ] `backend/solver_v2/solver/constructive_placer.py` - 增量空腔检测、回溯搜索树
- [ ] `backend/solver_v2/solver/unified_solver.py` - 迭代验证循环、阈值配置
- [ ] `backend/solver_v2/validation/independent_validator.py` - 验证阈值强制执行
- [ ] `tests/benchmark_suite.py` - 传递验证参数

### 文档
- [ ] `docs/phase1_weight_tuning_report.md` - 权重调优帕累托分析
- [ ] `docs/phase3_production_test_report.md` - 生产案例泛化测试结果
- [ ] `docs/architecture_changes.md` - 架构演进说明（从单点优化到自适应泛化）

### 测试数据
- [ ] `tests/production_cases/*.json` - 50个真实失败案例（需用户提供）
- [ ] `tests/benchmark_results_phaseX.json` - 每个阶段的基准测试快照

---

## ✅ 验收标准

### 最终验收（Week 4结束）
1. **功能完整性**：
   - 15个基准案例通过率≥86%（≥13个）
   - 50个生产案例通过率≥80%（≥40个）

2. **质量指标**：
   - 刚性履约率≥99%（所有通过案例）
   - 空腔体积<5m³（40HQ容器，通过案例中位数）
   - 倾倒安全系数≥2.0达标率≥95%

3. **性能约束**：
   - 求解时间中位数<45s
   - P95求解时间<120s

4. **泛化能力**：
   - 在未见过的SKU组合上无"意外崩溃"（鲁棒性测试）
   - 失败案例中，"算法缺陷"占比<30%（其余为本质无解或数据异常）

---

## 🎯 下一步行动

**立即开始**：里程碑1.1 - 紧凑度目标函数

**待确认事项**：
1. 是否启动实施？
2. 是否需要调整时间线（当前4周总周期）？
3. 生产失败案例数据是否可以提供？（里程碑3.3需要）
