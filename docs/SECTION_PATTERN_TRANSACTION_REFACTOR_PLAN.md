# 工业级 3D-CLP 重构实施全景规格书（工程落地级细节版）

---

## 一、 为什么当前的单列贪心必然陷入死胡同？

### 1.1 贪心单列推导的死穴
当前系统的装载主循环本质如下：
```python
# 现状：外层强行推进 delta_x，内层按 Y 轴逐列贪心尝试
delta_x = opt.dx * rows_x
while cur_y < cW:
    pick_single_column_or_fallback()
```
这种模式在多 SKU 异构尺寸混装时会产生不可调和的矛盾：
1. **尺寸硬凑产生横向塌陷**：当货柜宽度剩下 $0.25\,\text{m}$ 时，若待装 SKU 的宽度为 $0.40\,\text{m}$ 或 $0.30\,\text{m}$，单列贪心直接失败放弃，整堵墙右侧留下一道巨大的贯通空腔。
2. **纵向悬空与假切片**：若列 1 的货箱深度为 $0.83\,\text{m}$，整堵墙的推进步长 $\Delta X$ 被强制设为 $0.83\,\text{m}$；如果紧邻的列 2 选用了深度为 $0.43\,\text{m}$ 的箱子，列 2 的前方就凭空留下了 $0.40\,\text{m}$ 的悬空深坑。
3. **单步硬性倾覆检查误杀合法解**：在单列放置时，一个旋转后的薄箱（如厚度 $0.188\,\text{m}$，高 $0.488\,\text{m}$）因前方暂时没有箱子，被 `_is_placement_tipping_safe` 瞬间判定为“倾覆不安全”而直接丢弃，哪怕一秒钟后下一堵墙就会顶上来把它完全封死！

---

## 二、 核心数学模型与数据结构定义

为了彻底终结“改这里坏那里”，必须将排样逻辑升级为**“截面整宽模具（Section Fit Pattern）+ 跨墙惰性动力学审计”**。

### 2.1 构型元（Orientation Variant）数据模型
每个待装 SKU 展开为有限个离散的放置构型：

```python
@dataclass(frozen=True)
class OrientationVariant:
    sku_id: str
    sku_name: str
    ori_name: str          # 如 "UPRIGHT_NORMAL", "UPRIGHT_ROTATED"
    dx: float             # 纵向厚度 (沿货柜 X 轴)
    dy: float             # 横向宽度 (沿货柜 Y 轴)
    dz: float             # 垂直高度 (沿货柜 Z 轴)
    max_stack: int        # 堆叠层数上限
    weight_kg: float
    is_slender: bool      # 倾覆敏感标记: True if dz / dx > 2.0 or dx < 0.20m
```

### 2.2 截面整宽模具（Pattern Specification）
一堵完整的“整墙模具”由若干列并排组成：

```python
@dataclass
class ColumnSpec:
    variant: OrientationVariant
    num_cols_y: int       # 该构型在横向占用的列数
    num_rows_x: int       # 该构型在纵向推进的排数 (dx * num_rows_x ≈ Target_Delta_X)
    num_layers_z: int     # 垂直堆叠层数 (dz * num_layers_z <= cH)
    y_start: float        # 该列在 Y 轴的起始坐标
    width: float          # 该列总宽度 = num_cols_y * variant.dy
    depth: float          # 该列总深度 = num_rows_x * variant.dx
    height: float         # 该列总高度 = num_layers_z * variant.dz

@dataclass
class SectionWallPattern:
    pattern_id: str
    columns: List[ColumnSpec]
    total_width: float    # sum(col.width) <= 2.350m
    flush_depth: float    # 齐平推进深度 Delta_X
    coverage_ratio: float # total_width / Container_Width
    has_slender_columns: bool # 是否包含潜在倾覆风险列
```

---

## 三、 五大实施阶段全流程与算法细节

```
                    ┌─────────────────────────────────────────────────────────┐
                    │ 阶段 1: 构型生成与整宽背包模具求解器                   │
                    │         (Exact Width Pattern Generation)                │
                    └────────────────────────────┬────────────────────────────┘
                                                 │
                                                 ▼
                    ┌─────────────────────────────────────────────────────────┐
                    │ 阶段 2: 纵向深度公约数找平与推进                        │
                    │         (Synchronized Flush-Plane Advance)              │
                    └────────────────────────────┬────────────────────────────┘
                                                 │
                                                 ▼
                    ┌─────────────────────────────────────────────────────────┐
                    │ 阶段 3: 瞬态物理标记与事务快照保存                      │
                    │         (Lazy Suspicion Tagging & State Snapshot)       │
                    └────────────────────────────┬────────────────────────────┘
                                                 │
                                                 ▼
                    ┌─────────────────────────────────────────────────────────┐
                    │ 阶段 4: 跨墙推进与前向实体支撑审计                      │
                    │         (Cross-Wall Contact & Overturning Audit)        │
                    └────────────────────────────┬────────────────────────────┘
                                                 │
                                    ┌────────────┴────────────┐
                                    ▼ 达标                    ▼ 不达标
                         [事务提交，移除标记]           [事务回退与模具降级]
                                                 (Rollback & Fallback)
```

---

### 阶段 1：截面整宽背包模具生成算法（`WidthPatternEngine`）

#### 1.1 构型全展开（包含旋转）
针对当前可用库存大于 0 的 SKU，提取所有合法的立放构型：
- 正常立放：$dx = \text{box.length}, \; dy = \text{box.width}, \; dz = \text{box.height}$
- 旋转立放：$dx = \text{box.width}, \; dy = \text{box.length}, \; dz = \text{box.height}$
- （若允许平放则增加平放构型，并限定只在顶部或底部使用）

#### 1.2 背包列组合整数求解
目标：在货柜可用宽度 $W_{\text{avail}} = 2.350\,\text{m}$ 上，求非负整数列数向量 $(n_1, n_2, \dots, n_k)$，满足：
$$W_{\text{occupied}} = \sum_{j=1}^{k} n_j \cdot dy_j \le 2.350\,\text{m} \quad \text{且} \quad 2.350 - W_{\text{occupied}} \le 0.040\,\text{m}$$

- **剪枝规则 1（品类纯度）**：一堵墙内允许组合的 SKU 种类严格限制在 $1 \sim 3$ 种（同 SKU 优先聚合排布，严禁五花八门的碎拼）。
- **剪枝规则 2（库存门槛）**：构型 $j$ 必须满足其总需求量 $\ge n_j \times (\text{基础层高})$，禁止为不足 1 列的零散件生成整墙。

#### 1.3 模具适应度打分函数（Fitness Function）
$$\text{Score}(\text{Pattern}) = 0.40 \cdot \frac{W_{\text{occupied}}}{2.350} + 0.35 \cdot \text{DepthAlignment} + 0.25 \cdot \text{ZoneCompliance}$$

其中 **$\text{DepthAlignment}$（深度对齐指数）** 计算公式：
$$\text{DepthAlignment} = 1.0 - \frac{\max(\text{depth}_j) - \min(\text{depth}_j)}{\max(\text{depth}_j)}$$
- 若列 1 深度 $0.833\,\text{m}$，列 2 推进 2 排深度 $0.820\,\text{m}$，极差仅 $0.013\,\text{m}$，$\text{DepthAlignment} \approx 0.985$（极高分）。
- 该公式强力引导求解器选择**“在 X 轴终点能完美对齐找平”**的互补组合！

---

### 阶段 2：纵向深度公约数齐平推进（Flush-Plane Advance）

#### 2.1 公共推进平面的计算
选定评分最高的模具后，确定整面墙在 X 轴上的终点基准线 $X_{\text{flush}}$：
$$X_{\text{flush}} = X_{\text{current}} + \Delta X_{\text{target}}$$
各列排数 $R_j$ 取最接近且不超过 $\Delta X_{\text{target}}$ 的整数倍：
$$R_j = \max\left(1, \; \left\lfloor \frac{\Delta X_{\text{target}}}{dx_j} \right\rfloor\right)$$

#### 2.2 实体垛成型
- 每一列按 $Z=0$ 直铺至最大允许高度 $H_{\text{limit}} = \min(2.65\,\text{m}, \; \text{max\_stack} \cdot dz_j)$。
- 在当前 $X \sim X_{\text{flush}}$ 区间内，整面墙一次性实体灌入，**绝不允许中途退化为单箱游离放置**。

---

### 阶段 3：瞬态物理标记与事务快照（Lazy Suspicion Tagging）

#### 3.1 物理脆弱特征动态判定（严禁硬编码绝对厚度）
是否具有瞬态倾覆隐患，**严禁硬编码绝对厚度（如 $dx < 0.20\,\text{m}$）**，因为薄或厚是相对的——高度仅 $0.10\,\text{m}$ 的薄箱即使厚度只有 $0.08\,\text{m}$ 也是极其稳固的，而高度达 $1.8\,\text{m}$ 的大箱即使厚度达到 $0.35\,\text{m}$ 也极易倾翻。

因此，算法**严格依据纯物理无量纲动力学判据（Dimensionless Physical Criteria）**判定：
1. **临界高厚比判据（Aspect Ratio Threshold）**：
   $$\frac{H_{\text{column}}}{D_{\text{column}}} = \frac{\text{堆叠总高度 } (\text{layers} \cdot dz)}{\text{纵向总支撑深度 } (\text{rows} \cdot dx)} > \lambda_{\text{critical}} \quad (\text{动态阈值 } \lambda_{\text{critical}} = 2.0 \sim 2.5)$$
2. **瞬态无支撑抗倾覆安全系数（Intrinsic Overturning Safety Factor）**：
   依据货车在法定紧急制动工况（$a = 0.5g \sim 0.6g$）下的达朗贝尔力矩平衡：
   $$\text{SF}_{\text{isolated}} = \frac{M_{\text{restoring}}}{M_{\text{overturning}}} = \frac{m \cdot g \cdot \frac{D_{\text{column}}}{2}}{m \cdot a \cdot \frac{H_{\text{column}}}{2}} = \frac{g}{a} \cdot \frac{D_{\text{column}}}{H_{\text{column}}}$$
   当且仅当 $\text{SF}_{\text{isolated}} < 1.5$（即自由站立时自身重力矩无法抵御制动惯性力矩）且前方尚未贴紧前壁或门板时，才触发「待跨墙验算」标记！

#### 3.2 事务快照记录
在正式向 `placements` 写入数据前，求解器建立轻量级内存事务：
```python
snapshot = {
    "wall_index": current_wall_idx,
    "current_x": current_x,
    "placements_checkpoint_len": len(placements),
    "remaining_qty_snapshot": dict(remaining_qty),
    "suspect_placement_ids": set(), # 记录带有风险标记的 placement_id
}
```
凡属于上述超薄列的放置，打上扩展字段：`tipping_status = "SUSPECT_UNLOCKED"`，放入待验清单。

---

### 阶段 4：跨墙前向支撑审计与终态力矩验算（Cross-Wall Audit）

#### 4.1 触发时机
- **正常跨墙触发**：当紧接着的下一堵墙（第 $K+1$ 堵墙）排布成型后，立即对第 $K$ 堵墙中留存的 `SUSPECT_UNLOCKED` 货箱发起前向闭环审查。
- **终态门板触发**：当推进到柜门端时，对最外侧门区货箱，以货柜门内壁（$X = 11.984\,\text{m}$）作为刚性物理支撑面进行审查。

#### 4.2 动力学审计数学公式
对于每一个标记货箱，检查其前表面（$X_{\text{front}} = x + dx$）与紧贴的下一堵墙后表面（$X_{\text{rear}} = X_{\text{front}}$）之间的重叠面积：

1. **有效前向支撑率（Forward Contact Ratio）**：
   $$\text{Contact Area} = \sum_{P_{\text{next}}} \max\left(0, \; \min(y+dy, y_{\text{next}}+dy_{\text{next}}) - \max(y, y_{\text{next}})\right) \times \max\left(0, \; \min(z+dz, z_{\text{next}}+dz_{\text{next}}) - \max(z, z_{\text{next}})\right)$$
   $$\text{Ratio} = \frac{\text{Contact Area}}{dy \cdot dz} \ge 70\%$$
2. **抗急刹车倾覆力矩判据（0.5g Deceleration Moment Check）**：
   $$M_{\text{overturn}} = m \cdot (0.5g) \cdot \frac{dz}{2}$$
   $$M_{\text{resist}} = m \cdot g \cdot \frac{dx}{2} + F_{\text{front\_support}} \cdot h_{\text{contact}}$$
   只要前向有连续实体阻挡（$\text{Ratio} \ge 70\%$），前向阻挡力 $F_{\text{front\_support}}$ 即可提供足够的抵消力矩，满足 $\text{Safety Factor} \ge 1.5$。

#### 4.3 达标解除标记
一旦通过上述两项指标审查，将该货箱的标记就地改写为：
```python
p["tipping_status"] = "VERIFIED_SAFE"
```
当前墙体事务正式提交（Commit）。

---

### 阶段 5：轻量级事务回滚与模具自愈机制（Rollback & Fallback）

#### 5.1 什么时候触发回滚？
若跨墙审计发现：
- 某一标记列的前方出现了大面积空洞（例如前方恰好没有箱子顶住，$\text{Ratio} < 50\%$）；
- 或者下一堵墙因尺寸差异，无法在关键受力点提供物理支撑。

#### 5.2 确定性回滚执行流程
```python
def rollback_and_repair(snapshot, failed_pattern):
    # 1. 物理位置复位：瞬间撤销本堵墙的所有放置记录
    del placements[snapshot["placements_checkpoint_len"]:]
    current_x = snapshot["current_x"]
    remaining_qty.clear()
    remaining_qty.update(snapshot["remaining_qty_snapshot"])
    
    # 2. 局部黑名单隔离：禁止在当前位置再次选用该危险模具
    exclusion_set.add(failed_pattern.pattern_id)
    
    # 3. 模具降级自愈：
    # 自动从候选池挑选次优解（例如：将高危薄列替换为正常朝向，或改用厚度更厚的大件补位）
    next_best_pattern = pattern_engine.get_next_best(exclusion_set)
    apply_pattern(next_best_pattern)
```

**为什么这能根治互相打架？**
- 回滚操作**被严格锁死在单堵墙的边界内**（本地局部事务）。
- 它绝不反向破坏前面已经通过安全验收的墙体，也绝不调整全局玄学权重，计算链条纯净、单向且可重现。

---

## 四、 关键实施计划表与文件改造点

### 4.1 涉及文件与职责清晰划分
1. **新建** `backend/solver_v2/solver/width_pattern_engine.py`：
   - 专职负责：构型展开、背包满宽求解、深度公约数匹配、模具评分。
2. **重构** `backend/solver_v2/solver/composite_strip.py`：
   - 作为截面模具的执行层，依据 `SectionWallPattern` 批量成垛生成，移除散落的单列贪心。
3. **改造** `backend/solver_v2/solver/unified_solver.py`：
   - 将主循环改为“获取当前最优整墙模具 $\to$ 铺设整墙 $\to$ 跨墙惰性力矩审计 $\to$ 异常单墙回滚”。

---

本规格书将此前构想的**数学模型、判定阈值、数据结构和回滚算法**全部细化到了代码级。确认该执行标准后，我们将严格按照上述规范开展第一阶段 `WidthPatternEngine` 的落地编码！
