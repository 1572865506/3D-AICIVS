# BLK-007B — Sequence-aware Repair Engine

## Outcome

`BLK007B_STATUS = PASS`

`SEQUENCE_FEASIBILITY_RATE = 100.00%`

`NEED_BLK008 = false`

## Required answers

1. BENCH-001 修复：**成功**，从 `TEMPORARY_INSTABILITY` 变为 `SEQUENCE_FEASIBLE`。
2. Repair Action：**CREATE_PAIR_GROUP**，placements = `['p_0325_SKU-02', 'p_0324_SKU-03']`。候选由同 row、距离和结构规则产生，没有 SKU-ID 特判。
3. 最终 Geometry：**未改变**；位置、方向、bbox 均保持冻结结果，`geometry_changed = false`。
4. 新建 Loading Group：**4** 个，均为最小 PAIR construction group。
5. Temporary Stability：**已解决**，debt 必须在同一个 `PLACE_GROUP` 内归零。
6. Dependency：**保持 DAG**，dependency changes = `0`。
7. 装载复杂度：增加 **4 个 atomic group step**；没有扩大为 Row/Wall group，符合 smallest-change-wins。
8. 性能：380-placement repair = **1.461s**，`<2s = True`。

## Regression

- BENCH-001～012 sequence feasible：**12/12**。
- Repair deterministic：**PASS**。
- BLK-007B tests：**9 tests, PASS**。
- Full suite：**199 tests, PASS**。
- Frozen Packing Solver geometry：未修改。

本阶段只实现 `TEMPORARY_INSTABILITY_REPAIR`。未进入 BLK-008。
