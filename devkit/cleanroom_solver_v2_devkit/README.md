# 3D-AICIVS Clean-Room Solver V2 Agent DevKit

Target project:
`1572865506/3D-AICIVS`

Baseline framework branch:
`feature/v1.4.1-layer-first-xyz-audit`

## Purpose

Reuse the existing application framework, but **replace the packing algorithm from scratch**.

Reuse:
- Three.js visualization
- UI / SKU input
- API/server scaffolding
- project structure
- existing evaluator/tests only as regression references

Do NOT reuse as Solver V2 algorithm implementation:
- `backend/planner.py`
- `backend/industrial_packer.py`
- legacy placement heuristics
- legacy wall-building logic
- legacy orientation selection
- legacy gap-fill logic
- legacy candidate scoring

Legacy algorithm code is reference/baseline only.

## Clean-room rule

Agents implementing Solver V2 must not copy, translate, port, or lightly refactor legacy packing logic into the new solver.

Allowed uses of legacy code:
1. understand API data shapes
2. reproduce baseline output for A/B tests
3. collect bad cases
4. maintain backwards compatibility

Forbidden uses:
- copy placement strategy
- copy candidate generation
- copy global orientation choice
- copy wall packing algorithm
- copy gap filler
- copy scoring rules
- copy collision policy as final V2 truth

## Solver V2 core principle

Every placement must pass through one authoritative WorldState:

```text
Input
  ↓
Constraint Compiler
  ↓
Canonical WorldState
  ↓
Free Space Engine
  ↓
Candidate Generator
  ↓
Hard Validation
  ↓
Soft Scoring
  ↓
Atomic Commit
  ↓
Incremental WorldState Update
```

No object may enter the committed layout before hard geometry and rule validation.

## Canonical coordinates

- x = container length, inner wall → doors
- y = container width
- z = floor → roof
- origin = far-inner-left-floor
- units = meters / kilograms

## First benchmark bad case

`benchmarks/assets/bad_case_001_wall_hollow_collision.png`

This visual demonstrates two critical legacy failure classes:
1. internal wall cavities / fragmented dead space
2. cargo overlap/interpenetration

Solver V2 acceptance requires:
- overlap count = 0
- penetration volume = 0
- enclosed cavity detection
- residual-space quality metrics
- wall occupancy/flatness metrics
