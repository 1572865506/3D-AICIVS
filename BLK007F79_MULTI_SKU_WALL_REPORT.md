# BLK-007F-7.9 — Multi-SKU Wall Joint Recomposition Report

## 结论

多 SKU 相邻货墙联合重组引擎已经建立并接入生产流水线，位置为 True Cargo Recomposition 之后、Wall/Layer/TopFill 刷新之前。

首次验收被证明不足后已撤销：旧版本只覆盖0～5.84m，且不完整层56→56、above-cargo=0，不能判定完成。

修正版覆盖全柜0～11.424m，共检测34个结构问题区，按全柜均匀覆盖预算处理32个。3个 `MIXED_GAP_FILL` 和1个 `SUPPORTED_MIXED_LAYER_COMPLETION` 方案通过完整 GlobalValidator并提交：新增5个完整侧边列、21个跨SKU支撑行，共77件货物。利用率由75.6519299%提升至77.6893477%，墙侧空隙0.051m→0，不完整层56→51，多SKU墙10→14，异SKU上放43件。

## 实现内容

- `WallProblemDetector`：依据几何检测墙间隙、侧边空位、居中墙、孤立列和不完整层，不使用固定 Benchmark 坐标。
- `MixedSkuWallBlueprintGenerator`：生成左右锚定、接口闭合和从剩余库存抽取兼容 SKU 的完整列候选。
- `AboveCargoAdmissionResolver`：明确区分同 SKU 层数限制与异 SKU 上放权限。
- `JointWallScoreEngine`：按覆盖、接口、侧边、层、顶面、库存混合和结构惩罚评分。
- `MultiSkuWallRecompositionEngine`：区域级原子提交，任何 Hard Constraint 失败均回滚。
- `DoorIntegratedSolver`：新增 opt-in 编排接口；生产服务器已显式启用。

## 必答问题

1. **是否真正支持多个 SKU 联合拼墙？** 是。联合区域同时包含多堵墙的已有 SKU 和剩余库存候选；本轮新增列加入已有多 SKU 墙结构，而不是生成孤立 filler。
2. **是否仍然只是主 SKU 加局部单箱？** 否。提交单位是完整竖向列，禁止机会主义单箱提交；不过当前还不是任意三维层镶嵌求解。
3. **是否减少墙间小间距？** 合成测试已证明接口间距可以联合压缩；真实基准进入本模块前纵向墙间距已经为 0。
4. **是否解决一箱导致整墙错位？** 已提供联合接口候选且通过专项测试；真实基准该指标已被上一阶段修至 0。
5. **是否减少左右空位？** 是，真实基准墙侧空隙 0.051m → 0。
6. **自身 max_stack_layers 是否错误封顶？** 否。该字段只参与同 SKU 连续层数；异 SKU 上放由承压、类别和支撑决定。
7. **其他 SKU 能否放在限层 SKU 上方？** 能，专项测试证明物理条件满足时 AUTO_PASS；显式 0 承压仍 HARD REJECT。
8. **是否减少中空和孤立列？** 不完整层56→51；按真实横向接触重新计算的无约束孤立列为0。仍有51个不完整层未解决。
9. **是否改善 TopSurface？** 是，提交21个连续支撑行、54件跨SKU补层货物，43件属于异SKU上放。
10. **是否保持门墙安全？** 是，门墙 membership/geometry 不变，运输与开门验证均通过。
11. **坐标是否真实变化？** 是，最终 deterministic fingerprint 已更新，且增加 40 个真实 Placement。
12. **是否更接近人工装柜？** 侧边完整度和库存部署改善；跨层三维拼接仍需继续完善。

## 安全结果

```text
GlobalValidator = VALID
overlap = 0
penetration = 0
OOB = 0
door wall changed = false
door transport = PASS
door open = PASS
```

独立验证器的门侧 flood-fill 仍把被锁定门墙隔开的可达空间记为 cavity partition；这不是本轮新增的结构空洞，现有 hard gate 未触发。

## 状态

```text
BLK007F79_STATUS = FAIL
MULTI_SKU_WALL_COMPOSER_READY = true
JOINT_WALL_RECOMPOSITION_READY = true
FALSE_STACK_CEILING_FIXED = true
NEXT_REPAIR_TARGET = BLK007F79B_3D_LAYER_RECOMPOSITION
```

原因：核心路径已经真实生效，但仍有51个高度不完整层，不能声称截图中的全部排列问题已经闭环。禁止直接进入 Human Final Packing Pass，下一步应先做交换式三维层重组。
