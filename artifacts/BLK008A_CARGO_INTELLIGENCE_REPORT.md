# BLK-008A — Cargo Intelligence & Loading Policy Engine Report

## Status

`BLK008A_STATUS = PASS`

`CARGO_INTELLIGENCE_READY = true`

`POLICY_ENGINE_READY = true`

`NEXT_STAGE = BLK008B`

Work stopped at BLK-008A. BLK-008B and BLK-009 were not started.

## Architecture

CILPE is implemented under `src/cargo/intelligence` and executes before the Door Safety adapter. It adds a business-intelligence profile over the already accepted solver-domain CargoProfile instead of replacing it.

Policy precedence:

1. Manual JSON profile (`USER_DEFINED`).
2. Existing solver CargoProfile and orientation/top-fill rules.
3. Auditable name, geometry and weight classification (`INFERRED`).
4. Conservative defaults.

The adapter operates in `AUDIT_AND_GATE` mode. It exposes normalized constraints to Door, Wall and Top Fill orchestration while preserving all existing USER_DEFINED solver policies. `solver_constraints_mutated=false` in the policy audit.

Implemented engines:

- CargoProfileEngine
- CargoClassifier
- OrientationPolicyEngine
- StackPolicyEngine
- CompressionPolicyEngine
- FragilityPolicyEngine
- LoadingPriorityEngine
- CargoConstraintAdapter

Manual profiles are stored in `config/cargo_profiles/SKU-02.json`, `SKU-03.json` and `SKU-14.json` and can be adjusted without changing algorithms.

## 14-SKU intelligence audit

| Metric | Result |
|---|---:|
| SKU profiles | 14 |
| USER_DEFINED profiles | 3 |
| INFERRED profiles | 11 |
| DISPLAY | 4 |
| ELECTRONIC | 2 |
| HEAVY | 2 |
| FRAGILE | 3 |
| NORMAL_BOX | 3 |
| HIGH fragility | 7 |
| MEDIUM fragility | 2 |
| LOW fragility | 5 |

SKU-02 is classified as DISPLAY/HIGH with vertical base and door orientation, explicit conditional `FLAT_HORIZONTAL` top permission, maximum three top layers, 60kg compression limit and door priority 10.

SKU-14 is DISPLAY/HIGH with vertical base/door orientation, explicit top-only `FLAT_HORIZONTAL`, maximum three top layers, 25kg compression limit and top priority 10.

SKU-03 remains vertical-only. Its side and flat-horizontal orientations are explicitly forbidden.

## Integration behavior

- Door Wall receives normalized door priority and door orientation constraints.
- Cargo Wall receives stack/support/fragility policy metadata while existing physical limits stay authoritative.
- Top Fill candidates are checked against the same explicit top orientation intent compiled into the existing CargoProfile.
- Every real Top Fill placement in the benchmark passes the CILPE orientation gate.
- Layout cargo records now include `category`, `fragility`, `orientationUsed`, `stackLayer`, and `loadingReason` as additive BLK007C-compatible fields.

No Packing Solver Core, Beam Search, Candidate Generator, Collision, Compression, Door Wall, Cargo Wall, Top Fill, Repair, BLK007C or Three.js implementation was changed.

## Real 14-SKU regression

| Metric | BLK-007F-3 | BLK-008A | Change |
|---|---:|---:|---:|
| Placements | 1459 | 1459 | 0 |
| Utilization | 71.3574% | 71.3574% | 0 pp |
| Cargo volume | 54.482412 m³ | 54.482412 m³ | 0 |
| Top Fill placements | 129 | 129 | 0 |
| Door Wall placements | 28 | 28 | 0 |

Safety remains:

- GlobalValidator: VALID
- overlap / penetration / OOB / hard violations: 0
- enclosed cavities: 0
- LoadingSequence: feasible
- Door Wall locked and unchanged

## Required answers

1. **算法是否知道货物属性？** 是。每个 SKU 有 category、confidence、fragility、orientation、stack、compression、priority 和 source。
2. **是否能区分显示器/普通箱？** 是。SKU-02/03/14 等显示器与 NORMAL_BOX、HEAVY、ELECTRONIC 分开分类。
3. **是否限制非法旋转？** 是。显示器 SIDE 被拒绝；SKU-03 顶部 FLAT 也被拒绝。
4. **是否支持顶部特殊摆放？** 是。SKU-02/14 的人工规则允许 `FLAT_HORIZONTAL`，真实 Top Fill 全部通过策略门禁。
5. **是否支持最大堆叠？** 是。SKU-14 顶部三层通过、第四层以 `MAX_STACK_LAYERS` 拒绝。
6. **是否支持承压判断？** 是。SKU-14 20kg 顶载通过，30kg 以 `COMPRESSION_LIMIT_EXCEEDED` 拒绝；易碎规则随后继续校验。
7. **14 SKU 结果是否保持或提升？** 保持，利用率与件数均无下降。
