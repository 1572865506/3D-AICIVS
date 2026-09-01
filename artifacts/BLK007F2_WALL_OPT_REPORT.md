# BLK-007F-2 — Wall Optimization & Transition Layer Report

## Status

`BLK007F2_STATUS = PASS`

`TRANSITION_WALL_READY = true`

`WALL_CHAIN_READY = true`

`NEXT_STAGE = BLK007F3`

Work stopped at BLK-007F-2. BLK-007F-3 and BLK-008 were not started.

## Implemented architecture

The optimization layer is located in `src/constraints/wall/optimization` and runs after BLK-007F-1 wall formation but before the frozen solver:

1. `WallContinuityOptimizer` centers complete wall layers and reduces their largest lateral edge gap.
2. `WallExpansionEngine` performs bounded inventory/geometry enumeration over cargo explicitly admitted to the door context.
3. `TransitionWallBuilder` materializes complete, upright, centered transition walls.
4. `WallMergeOptimizer` canonicalizes adjacent equal-composition walls into larger structural segments.
5. `WallChainGraph` links Cargo Wall → Transition Wall → Door Wall and measures every longitudinal gap.
6. `WallBalanceAnalyzer` checks lateral weight balance and longitudinal center of mass.
7. `WallOptimizationScore` evaluates continuity, coverage, support, balance, chain strength, voids and fragmentation.
8. `WallOptimizationAdapter` reserves transition inventory and passes only the proven residual to the unchanged solver.

Candidate generation uses CargoProfile roles, CargoRisk classification, existing door eligibility and `DoorOrientationRules`. No SKU ID or product-name scoring branch was introduced.

## Real 14-SKU result

| Metric | BLK-007F-1 | BLK-007F-2 | Change |
|---|---:|---:|---:|
| Structural wall end x | 7.227 m | 10.829 m | +3.602 m |
| Final placements | 877 | 1330 | +453 |
| Utilization | 60.3716% | 69.1412% | +8.7696 pp |
| Reachable residual volume | 26.341472 m³ | 20.177503 m³ | -6.163969 m³ |
| Wall fragments/nodes | 51 | 16 merged segments | -68.63% |
| Existing-wall continuity | 88.0255 | 89.4071 | +1.3816 |
| Longitudinal transition coverage | — | 99.9168% | new |

Final structure:

- Cargo Walls: 17
- Cargo Wall placements: 474
- Transition Walls: 34
- Transition placements: 828
- Door Wall placements: 28
- remaining Cargo-to-Door gap: 0.003 m
- WallChain length: 10.912 m
- WallChain valid: true
- weak links: 0
- broken points: 0
- minimum connection strength: 70.8333
- balance score: 95.8084/100
- optimization score: 89.6402, grade B

The 3.605 m expansion interval is filled by a deterministic bounded combination of eligible wall templates. Inventory consumed by the transition is SKU-02 ×448, SKU-03 ×70, SKU-04 ×54 and SKU-14 ×256. All remain upright with the existing `SHORT_EDGE_FORWARD` door policy. This is a result of geometry/inventory enumeration, not SKU-specific scoring.

Weight ordering is longitudinal and centered, with no transition carton stacked across incompatible SKU layers. Existing compression and final global validation remain authoritative. The fixed Door Wall is not moved or re-oriented.

## Top-fill handoff

No Top Fill algorithm was added or changed. The optimization result exports:

- `remaining_top_candidates`
- `unused_height_regions`

These are diagnostics/handoff records for BLK-007F-3 only.

## Safety and compatibility

- GlobalValidator: VALID
- overlap: 0
- penetration: 0
- OOB: 0
- hard violations: 0
- enclosed cavities: 0
- ordinary cargo entering reserved door region: 0
- LoadingSequence: feasible
- Door Wall: 28 locked SKU-02 placements, unchanged
- BLK007B Repair: unchanged
- BLK007C API fields: unchanged; additive `TRANSITION_WALL` role only
- Beam Search, Candidate Generator, Collision and Compression core: unchanged
- Three.js renderer: unchanged

## Required answers

1. **货墙是否延伸到更多柜体区域？** 是，从 x=7.227m 延伸到 x=10.829m，新增 3.602m。
2. **Door Wall 和 Cargo Wall 之间是否存在连续受力路径？** 是，WallChain 有效、broken point=0、weak link=0，末端只有 3mm 容许间隙。
3. **是否减少墙体断裂？** 是，51 个墙节点合并为 16 个结构段，碎片数量下降 68.63%。
4. **是否提高整体稳定性？** 是，左右平衡分 95.81，链连接全部有效，最终 Support/Compression/GlobalValidator 均通过。
5. **是否保持 BLK007E 安全逻辑？** 是，门墙数量、方向、锁定状态和预留区零侵入全部保持。
6. **14 SKU 利用率是否提升？** 是，由 60.3716% 提升至 69.1412%，增加 8.7696 个百分点。
