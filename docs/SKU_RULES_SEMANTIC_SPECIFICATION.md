# 3D-AICIVS SKU 装载规则语义一致性审查与工业级规范指南

> **文档版本**: v1.0.0  
> **编写角色**: 角色 E (架构审计) / 角色 B (稳定性与物理规范)  
> **适用范围**: 前端 UI 配置、适配层 (`InputAdapter`)、核心求解器 (`unified_solver`)、独立验证器 (`independent_validator`)  
> **核心目标**: 彻底消除前端测试、算法求解、生产验收三方在装载规则上的不对等、含糊与冲突，确立统一的物理与业务语义标准。

---

## 目录
- [一、审查背景与执行摘要](#一审查背景与执行摘要)
- [二、核心约束参数全景语义对齐矩阵](#二核心约束参数全景语义对齐矩阵)
- [三、六大核心语义冲突与深度归因剖析](#三六大核心语义冲突与深度归因剖析)
  - [3.1 冲突一：allow_stacking_on_top 的“自叠 vs 他叠”悖论与孤岛字段](#31-冲突一allow_stacking_on_top-的自叠-vs-他叠悖论与孤岛字段)
  - [3.2 冲突二：承重检查的“单层直接接触”截断漏检与多层传力缺失](#32-冲突二承重检查的单层直接接触截断漏检与多层传力缺失)
  - [3.3 冲突三：朝向权限的“单向强制缺失”与上下文越权放大](#33-冲突三朝向权限的单向强制缺失与上下文越权放大)
  - [3.4 冲突四：门区锁定的“真空死腔坑”与小体量门区件冲突](#34-冲突四门区锁定的真空死腔坑与小体量门区件冲突)
  - [3.5 冲突五：must_be_on_floor 底板饱和与降级熔断机制缺失](#35-冲突五must_be_on_floor-底板饱和与降级熔断机制缺失)
  - [3.6 冲突六：局部支撑承重折算的应力集中盲区](#36-冲突六局部支撑承重折算的应力集中盲区)
- [四、三方对等规范化数据契约标准](#四三方对等规范化数据契约标准)
- [五、实施落地方案与语义卫语句（Semantic Guards）](#五实施落地方案与语义卫语句semantic-guards)

---

## 一、审查背景与执行摘要

在 3D 集装箱装载（3D-CLP）工程落地中，最常见的隐性故障往往不是几何碰撞算法本身的 bug，而是**参数语义在生命周期中的漂移与扭曲**：
- **前端测试人员的直觉理解**（如：“我不勾选允许堆叠，意思是别拿别人的重货压坏我”）；
- **后端适配层的翻译映射**（如：将 `allowStackingOnTop: false` 翻译为任何重物乃至同品类都禁止叠放）；
- **核心求解器的启发式搜索**（如：只在放置前做快速局部剪枝，忽略了全局传力）；
- **独立验证器的合规审计**（如：使用刚性几何边界或单层接触面检查，触发虚假拦截或漏判致命物理风险）。

经过对 `backend/solver_v2/` 核心代码、`tests/cases/` 测试集、`frontend/src/` 及 `independent_validator.py` 的逐行语义审查，共识别出 **6 大核心冲突** 与 **2 项物理截断漏洞**。本文档确立工业级的统一规范。

---

## 二、核心约束参数全景语义对齐矩阵

| 序号 | 规则参数 | 前端 UI 字段 | 后端模型定义 | 验证器判定方式 | 实际工业物理语义 |
|:---|:---|:---|:---|:---|:---|
| 1 | **落地要求** | `mustBeOnFloor` (单选布尔) | `StackingPolicy.must_be_on_floor` | Floor-Rooted 起堆链，允许同品类在 `max_stack_layers` 内自叠，严禁异品垫底 | 货物自重大或底托要求，必须以地板为物理根基，自身可柱状自叠 |
| 2 | **允许上方堆叠** | `allowStackingOnTop` (布尔) | `StackingPolicy.allow_stacking_on_top` | 检查上表面候选箱体列表 `upper_boxes` 是否为空 | **存在歧义**：是禁止被杂货压，还是绝对封顶（自叠也禁止）？ |
| 3 | **自品类堆叠** | *(前端未暴露)* | `StackingPolicy.stack_on_self: bool = True` | *(孤岛字段，未被实际审计)* | 是否允许同款 SKU 互相叠放 |
| 4 | **最大堆叠层数** | `maxStackLayers` (整数) | `StackingPolicy.max_stack_layers` | 垂直接触 DAG 最长同品类路径计数 | 本品类自下而上连续叠放的最大物理件数上限（防压溃） |
| 5 | **顶面承重上限** | `maxBearingKg` / `maxTopLoad` | `CompressionPolicy.max_top_load_kg` / `StackingPolicy.max_bearing_kg` | 累加 `z + dz` 直接接触上箱投影重量 | **存在漏检**：仅计算单层直接接触，未计算多层累计重力传导 |
| 6 | **表面压强上限** | `maxPressureKgM2` (数值) | `CompressionPolicy.max_pressure_kg_m2` | `upper_weight / base_area` | 包装箱表面瓦楞纸/木板的抗局部压陷压强极限 |
| 7 | **底部支撑率** | `minSupportRatio` (0~1) | `StabilityPolicy.min_support_ratio` | 下表面支撑箱体投影面积和 / 底面积 | 悬空率限制，防止悬臂过大发生弯折倾覆（默认 70%） |
| 8 | **允许朝向** | `allowedOrientation` (下拉) | `OrientationPolicy` (含规则集合) | 检查放置旋转维度与策略规则白名单匹配 | 货物立放、平放、侧放的物理许可（液体/精密机械通常严禁侧倾） |
| 9 | **保持直立** | `keepUpright` (布尔) | `HandlingPolicy.keep_upright` | 检查 `OrientationMode.UPRIGHT` | 高度方向（Z轴）必须保持货物初始包装的朝上箭头方向 |
| 10 | **门区封锁** | `allowDoorZone` / `requirement: "封柜门"` | `PackingRole.DOOR_SEAL` / `ZoneType.DOOR` | 门区边界 `[Lx - door_len, Lx]` 互斥阻断 | 门端稳固防滚落货物，或最后装车、最先卸载的特定货物 |
| 11 | **装载优先级** | `loadPriority` (整数) | `PlacementPolicy.load_priority` | 算法排序优先，验证器不设硬失败 | 先后装载顺序：基础件/重件靠前，零散件靠后 |
| 12 | **弹性件标记** | `isElastic` (布尔) | `QuantityPlan.is_elastic` | `rigid_completion_pct` 履约率与倒挂判定 | 空间不足时可安全舍弃或少装的货物，严禁反客为主抢占刚性件 |

---

## 三、六大核心语义冲突与深度归因剖析

### 3.1 冲突一：allow_stacking_on_top 的“自叠 vs 他叠”悖论与孤岛字段

#### 现状剖析
在 `backend/solver_v2/validation/independent_validator.py` 第 780 行：
```python
if cargo and not cargo.stacking_policy.allow_stacking_on_top and upper_boxes:
    rule_violations.append(ViolationDetail(
        violation_type=ViolationType.NO_TOP_STACK_VIOLATION,
        message=f"Placement {p['placement_id']} (SKU: {sku_id}) forbids stacking on top, but has {len(upper_boxes)} boxes resting above it",
    ))
```
- **代码行为**：只要 `allow_stacking_on_top == False`，该箱体上方只要有**任何**箱子（哪怕是完全相同的同款 SKU），验证器均直接判定为致命违规！
- **业务矛盾**：
  在实际货运中，货主配置“禁止上方堆叠”通常有 80% 的概率表达的是：**“这是家电纸箱，不能把重机械或其他杂货压在上面（No Foreign Cargo Above），但同款家电纸箱结构咬合，出厂允许堆放 2~3 层”**。
  此时如果用户输入：`allowStackingOnTop = false`, `maxStackLayers = 3`。
  - 前端：没有任何冲突报错，直接保存提交；
  - 求解器：若生成了同款叠放 2 层的方案；
  - 独立验证器：在第 1 层上方检测到同款第 2 层，直接拦截并报 `NO_TOP_STACK_VIOLATION`！
- **孤岛字段**：
  数据模型中其实已经定义了 `StackingPolicy.stack_on_self: bool = True`，但无论在求解器主链路还是在验证器中，**该字段完全被闲置，从未参与判定**！

#### 工业规范定义
重构为两级正交约束语义：
1. `allow_foreign_stacking_on_top: bool`（是否允许**异品类/其他货物**堆叠在其上方，默认 True）；
2. `stack_on_self: bool`（是否允许**同款品类**在 `max_stack_layers` 限制内自堆叠，默认 True）；
3. 原 `allow_stacking_on_top` 保持向下兼容，但其严格语义为：`allow_foreign_stacking_on_top`。如果 `allow_stacking_on_top=False` 且 `stack_on_self=True`，则**允许同品类合法自叠，仅拦截异品类堆叠**！

---

### 3.2 冲突二：承重检查的“单层直接接触”截断漏检与多层传力缺失

#### 现状剖析
在 `independent_validator.py` 第 764-778 行：
```python
candidate_uppers = get_supported_candidates(z + dz)
for j in candidate_uppers:
    ...
    contact_frac = (ox * oy) / (p2["dx"] * p2["dy"])
    w = p2["weight_kg"] * contact_frac
    upper_weight += w
```
- **物理缺陷**：验证器只通过 `get_supported_candidates(z + dz)` 累加了**紧贴在其顶面的那 1 层箱子**的重量！
- **重大漏检风险**：
  假设某个纸箱底座 SKU 的承重极限是 `max_bearing_kg = 30 kg`。
  上层依次柱状垂直堆叠了 3 个同款箱体，每个自重 `20 kg`。
  - **实际物理受力**：底层箱体顶面承受的总重力载荷 = 第 2 层 (20kg) + 第 3 层 (20kg) + 第 4 层 (20kg) = **60 kg**！已超载 100%，必然被压塌！
  - **验证器判定结果**：
    - 检查底层箱：头顶只有第 2 层直接接触，载荷计为 20 kg < 30 kg，**判定合格 ✅**！
    - 检查第 2 层：头顶只有第 3 层直接接触，载荷计为 20 kg < 30 kg，**判定合格 ✅**！
    - 检查第 3 层：头顶只有第 4 层直接接触，载荷计为 20 kg < 30 kg，**判定合格 ✅**！
  - **结果**：验证器亮起绿灯，系统将极其危险的超重方案发往生产现场！

#### 工业规范定义
- 验证器承重与压强审计必须采用**全局向下累加传力模型（Recursive Load Propagation DAG）**。
- 一个箱体承受的顶面总载荷应为其上方所有连通堆叠体沿接触面加权传递的重力之和，而非仅切片相邻层。

---

### 3.3 冲突三：朝向权限的“单向强制缺失”与上下文越权放大

#### 现状剖析
在 `backend/solver_v2/api/adapter.py` 第 146 行：
```python
return OrientationPolicy(
    allow_upright=True,   # 硬编码，从不从 raw_item 解析 allow_upright！
    allow_flat=allow_flat,
    allow_side=allow_side,
    ...
)
```
以及第 140 行：
```python
if allow_flat or allowed_ori in ('any', 'allow_flat') or '允许旋转' in raw_item.get('requirement', ''):
    contexts_flat.extend([PlacementContext.MAIN_WALL, PlacementContext.GENERAL, PlacementContext.FOUNDATION])
```
- **业务矛盾 1：无法表达“仅限平放，禁止立放”**：
  在实际工业中，大型薄板（如大理石台面板、特种仪器、扁平纸盒底托）出于防倾覆或重心考虑，严格要求“**必须平放，严禁立放**”。
  但系统无论怎么配置，`allow_upright` 永远为 `True`，算法始终会尝试以高纵横比立放该物品，无法实现“仅平放”的业务意图。
- **业务矛盾 2：平放权限被静默泛化**：
  前端测试时如果选择“允许平放”，许多测试人员的初衷是“在主墙上方的空间（TOP_FILL）或者缝隙中允许平放以提高空间利用率”。
  但 Adapter 一旦识别到 `allow_flat`，立刻将 `MAIN_WALL` 和 `FOUNDATION`（底盘）也全部打通平放权限，导致承重底盘被平放的脆弱货物占满，主墙结构承载力急剧恶化。

#### 工业规范定义
1. 支持显式配置 `allow_upright: bool = True`，允许设置为 `false`（例如：`allowedOrientation = "flat_only"`）；
2. 明确区分 **全局允许旋转 (Anywhere)** 与 **受限情境平放 (TopFill/GapFill Only)**。

---

### 3.4 冲突四：门区锁定的“真空死腔坑”与小体量门区件冲突

#### 现状剖析
在 `independent_validator.py` 第 671-689 行：
只要订单中出现了任何一个门区 SKU（`target_zone == ZoneType.DOOR` 或 `PackingRole.DOOR_SEAL`），整个门区区间 `[Lx - door_zone_len, Lx]` 便被绝对锁定（Lockout）。
- **业务矛盾**：
  - 门区默认保留长度通常为 1.0m ~ 1.2m（在 40HQ 柜中体积高达约 7.6 m³）；
  - 如果客户清单中仅有 2 箱特定小货（例如 0.4m x 0.4m x 0.4m，总体积仅 0.128 m³）在订单上备注了“放门口/最先卸载”；
  - 求解器将这 2 箱货放入门区后，剩余的 7.4 m³ 门区空间由于硬性门区锁（Lockout）的限制，**严禁任何普通主墙货物进入**！
  - **后果**：集装箱后部留下大面积不可填充的“真空死腔”，空间利用率直线下跌 8%~12%，并造成整车前后质量分布严重失衡（严重的甩尾和制动轴偏载隐患）。

#### 工业规范定义
门区业务语义应精确拆分为两类，严禁混为一谈：
1. **`DOOR_WALL_CLOSURE`（封门稳固墙）**：货物体积与面宽必须足以构成一道横跨柜体宽度的稳固物理隔断墙（用于防止开门货物倾泻倒塌）。体积不足以建墙的货物不得分配为 `DOOR_SEAL`。
2. **`PRIORITY_DISCHARGE`（优先卸载区）**：仅代表装载位置倾向于靠近柜门（方便目的地第一站卸货），其上方和周围在做好防倒措施前提下，**允许非门区货物在后方紧密顶靠填充**，不得对门区施行全截面真空封锁！

---

### 3.5 冲突五：must_be_on_floor 底板饱和与降级熔断机制缺失

#### 现状剖析
当多个大型刚性 SKU 均配置了 `mustBeOnFloor: true`，且其总底面积（Footprint Area）大于集装箱底板面积时（例如集装箱底面积 28 m²，而落地货物总底面积达 35 m²）：
- **当前表现**：
  - 前端无任何警告或预检拦截；
  - 求解器在底板铺满后，对于剩下的落地重货无法放置，只能导致严重的 **刚性件饥饿弃装 (Rigid Starvation)**；
  - 或者若算法松懈，将部分必须落地的货物置于上层，直接被独立验证器判定为 `FLOOR_ONLY_VIOLATION` 失败！

#### 工业规范定义
引入 **底板饱和度预检卫语句（Floor Saturation Guard）**：
- 在订单输入阶段计算 $\sum (\text{Footprint Area} \times \text{Quantity})$；
- 若落地货物理论最小底面积占柜体底面积比例 $> 100\%$，且相关 SKU 的 `max_stack_layers <= 1`，立即在前端和 API 抛出明确业务阻断错误：`FLOOR_CAPACITY_EXCEEDED`，提示用户提高层数上限或分批装柜，严禁将不可行方案送入求解器。

---

### 3.6 冲突六：局部支撑承重折算的应力集中盲区

#### 现状剖析
求解器和验证器计算上方箱体对下方箱体的施加载荷时，均采用如下线性面积比例分摊：
$$\text{added\_weight} = \text{upper\_weight} \times \frac{\text{contact\_area}}{\text{upper\_base\_area}}$$
- **物理隐患**：
  若一个 300kg 的硬质金属重箱，只有 10% 的下表面搭在下方一个耐压仅 50kg 的纸箱边缘角落（其余 90% 支撑在坚固平台上）。
  - 按现行公式计算：分摊重量 $= 300 \times 10\% = 30\text{ kg} < 50\text{ kg}$，**判定完全安全**！
  - 实际力学状况：重箱的锐角对纸箱产生极其严重的**剪切应力集中（Concentrated Shear Stress）**，下方的纸箱角落瞬间被压裂踩穿，导致整个上层货物向一侧剧烈倾倒！

#### 工业规范定义
**承重面积均摊的前提是“有效接触比（Effective Contact Fraction）”达标**：
- 当上方箱体对下方箱体的接触重合面积小于上方箱体底面积的 $25\%$ 时，视为局部点接触/线接触；
- 必须施加至少 $1.5 \times \sim 2.0 \times$ 的局部应力集中放大惩罚系数，或直接触发不安全支撑拦截。

---

## 四、三方对等规范化数据契约标准

为了确保前端、后端、求解器和验证器四位一体，建立如下强类型、自解释的数据结构契约（建议在后续迭代中逐步固化至 `domain/models.py` 与 `contracts/API_V2.md`）：

```json
{
  "sku_id": "SKU-HEAVY-01",
  "name": "重型注塑底座",
  "dimensions": { "length": 1.2, "width": 0.8, "height": 0.6 },
  "weight_kg": 250.0,
  "quantity": {
    "required": 20,
    "min_quantity": 20,
    "is_elastic": false
  },
  "orientation_rules": {
    "allow_upright": true,
    "allow_flat": false,
    "allow_side": false,
    "allowed_modes": ["UPRIGHT"]
  },
  "stacking_rules": {
    "grounding_requirement": "FLOOR_ROOTED", 
    "max_stack_layers": 2,
    "allow_foreign_stacking_on_top": false,
    "allow_self_stacking_on_top": true,
    "max_bearing_kg": 300.0,
    "max_pressure_kg_m2": 312.5,
    "min_support_ratio": 0.80
  },
  "zone_rules": {
    "zone_preference": "REAR",
    "is_door_seal_wall": false,
    "priority_discharge": false
  }
}
```

### 规范术语对照表
1. **`grounding_requirement`**:
   - `ANYWHERE`: 任何高度均可放置（需满足支撑率）；
   - `FLOOR_ROOTED`: 必须从地面起堆，同品类自叠链最高到 `max_stack_layers`；
   - `FLOOR_EXCLUSIVE`: 严格仅限最底层地面（$z=0$），哪怕同品类也不得叠在上面（等价于 `FLOOR_ROOTED` 且 `max_stack_layers=1`）。
2. **`allow_foreign_stacking_on_top`**:
   - `true`: 允许其他品类的安全货物在其上方堆叠；
   - `false`: 禁止任何非同款杂物压在其上方。
3. **`allow_self_stacking_on_top`**:
   - `true`: 允许同款 SKU 按照 `max_stack_layers` 自堆叠；
   - `false`: 绝对封顶，本品顶部不得放任何物品。

---

## 五、实施落地方案与语义卫语句（Semantic Guards）

为了在不破坏现有基线算法性能的前提下彻底消除这些语义隐患，推荐按以下三个渐进阶段实施：

### 阶段 1：适配层与输入预检卫语句（Safe Adapter Guards）
在 `backend/solver_v2/api/adapter.py` 中增加对前端输入的规范化防御性修正：
- **卫语句 1**：当检测到 `allow_stacking_on_top == False` 且 `max_stack_layers > 1` 时，若未明确设置 `stack_on_self`，自动将语义规范化为 `stack_on_self = True`，并在验证器中放行合法自叠，仅拦截异品杂货堆叠。
- **卫语句 2**：落地重货底板饱和度预检，若必须落地货物的总底面积超出集装箱底板可用面积，提前抛出清晰友好的配置警告，杜绝后端静默弃装。
- **卫语句 3**：朝向解耦，支持从前端透传 `allowUpright: false`，消除“无法禁止立放”的系统级死角。

### 阶段 2：独立验证器的物理力学修正（Validator Physics Alignment）
在 `backend/solver_v2/validation/independent_validator.py` 中：
- 修复承重检查切片截断缺陷，引入跨层累计载荷计算；
- 完善 `allow_stacking_on_top` 的异品类判定逻辑（区分自叠与他叠）；
- 升级门区真空封锁判定：对小体积门区件放宽为非阻断式优先区域，避免利用率虚假暴跌。

### 阶段 3：前端 UI 交互提示与校验升级（UI Form Alignment）
在 `index.html` 与 `frontend/src/manifestWorkflow.js` 中：
- 将“允许上方堆叠”文本升级为“允许异品杂物堆叠（同款自叠请配置最大层数）”，增加悬浮提示说明；
- 针对 `keepUpright` 与 `allowFlat` 增加联动互斥提示与自动重置；
- 在 SKU 列表概览中直观展示“落地”、“限叠”、“承重”标签，杜绝误配置。

---
*本文档由 3D-AICIVS 架构审计与稳定性规范组共同确立，作为系统装载规则的核心权威标准。*
