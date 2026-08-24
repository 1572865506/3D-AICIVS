# BLK-007F-5 — Loading Direction Strategy Engine

## Status

`BLK007F5_STATUS = PASS`

`LOADING_DIRECTION_READY = true`

`FACING_STRATEGY_READY = true`

`NEXT_STAGE = BLK008B`

## Delivered

LDSE is an opt-in strategy layer placed after Cargo Intelligence and before Door/Cargo Wall planning. It provides container-axis interpretation, Cargo facing rules, wall-direction planning, Door direction policy, transport-risk simulation, explainable scoring and three downstream projections:

- Cargo Wall: `preferredFacing`
- Solver: `orientationPriority`
- Top Fill: `PROFILE_GATED_TOP_FLAT`

The strategy is a preference, not a new universal hard constraint. Existing CargoProfile prohibitions and Door safety rules remain authoritative. CargoSKU objects are not mutated, and no Solver Core, Beam, collision, compression, wall, top-fill or rendering algorithm was changed.

## Coordinate semantics

Business loading direction is door → rear (`-X`). Existing Solver V2/BLK007C canonical coordinates remain rear → door (`+X`, door at maximum X). LDSE exposes both views rather than reversing existing layout coordinates.

## Direction result

All 856 non-top Display placements in the real 14-SKU result use `SHORT_EDGE_FORWARD`; violations are zero. For SKU-02 this means 0.08 m occupies the longitudinal axis and 0.553 m forms the wall surface. Its global direction score is 91.7763 versus 43.7348 for long-edge-forward.

Top Fill remains context-specific: 129 SKU-14 placements use explicit Profile-authorized flat orientation, while MAIN_BODY flat count remains zero.

## Benchmark

| Metric | BLK007F4 | BLK007F5 |
|---|---:|---:|
| placements | 1462 | 1462 |
| utilization | 71.5044% | 71.5044% |
| Display non-top SHORT_EDGE_FORWARD | not strategy-audited | 856/856 |
| Display direction violations | not strategy-audited | 0 |
| Door Wall placements | 28 | 28 |
| Door longitudinal seal coverage | 99.75% | 99.75% |
| GlobalValidator | VALID | VALID |

Utilization is preserved rather than artificially increased: the accepted BLK007F4 geometry already happened to match the new strategy. LDSE makes that outcome deliberate, explainable, API-visible and regression-protected without reordering frozen walls.

## Required answers

1. **显示器是否优先窄面朝柜深？** 是。SKU-02/03/04/14 的全局首选均为 SHORT_EDGE_FORWARD，真实非顶部 placement 为 856/856。
2. **货墙方向是否更加连续？** 方向策略连续度为 100%；几何墙体指纹保持不变，因此没有通过重排制造虚假改善。
3. **柜门区域是否形成稳定封口？** 是。28 个锁定门墙 placement 均保持短边朝柜深，纵向封口覆盖 99.75%。
4. **是否降低运输倾倒风险？** 是。以 SKU-02 为例，短边策略风险 19.3092，长边策略风险 37.2712。
5. **方向选择是否从局部变为全局策略？** 是。每个 SKU 在 Wall 构建前生成统一 FacingRule、候选模拟、全局评分和下游优先级。
6. **14 SKU效果是否改善？** 安全和方向可解释性改善；利用率保持 71.5044%，满足不低于 BLK007F4 的验收要求。

## Validation

Final GlobalValidator is **VALID**. overlap=0, penetration=0, OOB=0, physical violations=0. Full suite: **279/279 PASS**.

BLK-007F-5 到此停止；未进入 BLK008B 或 BLK009。
