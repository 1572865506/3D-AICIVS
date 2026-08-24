# Clean-Room Solver V2 Agent Prompt

You are contributing to a new packing solver inside the existing 3D-AICIVS framework.

Read:
- README.md
- docs/CLEANROOM_SCOPE.md
- docs/SOLVER_V2_ARCHITECTURE.md
- docs/ALGORITHM_RUNTIME_FLOW.md
- docs/RESIDUAL_SPACE_MODEL.md
- docs/COLLISION_AND_GEOMETRY.md
- docs/ORIENTATION_TOPFILL.md
- docs/DEVELOPMENT_ROADMAP.md
- docs/ACCEPTANCE.md
- your assigned task

Critical clean-room rule:
Do not copy, port, translate, or refactor legacy placement/wall/orientation/gap/scoring algorithms from `planner.py` or `industrial_packer.py`.

Legacy code may be used only for API compatibility and regression comparison.

Before coding, report:
1. files to add/change
2. algorithm being implemented
3. invariants
4. tests
5. unknown business values

While coding:
- canonical x/y/z only
- hard invalid states are rejected
- WorldState is authoritative
- placement commits are atomic
- use spatial index
- residual space quality matters
- context-dependent orientation
- deterministic seed
- time budget for search
- no invented business/physics values

After coding, report:
- changed files
- tests
- benchmark results
- bad-case metrics
- unresolved assumptions
