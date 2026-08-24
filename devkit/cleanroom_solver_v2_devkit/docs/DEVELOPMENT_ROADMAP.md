# Development Roadmap

## M0 — Framework isolation
Goal: create a clean V2 package without using legacy algorithm code.

Deliver:
- solver_v2 skeleton
- canonical schemas
- input/output adapters
- baseline bad-case catalog
- benchmark runner

## M1 — Geometry kernel
Deliver:
- WorldState
- AABB/spatial index
- EMS
- Extreme Points
- Candidate Generator
- atomic commit/rollback
- independent collision validator

Acceptance:
- overlap = 0
- penetration = 0
- out-of-bounds = 0

## M2 — Business/Orientation
Deliver:
- Constraint Compiler
- Rule Engine
- Adaptive Zones
- Quantity/Reservation
- Placement Context
- Orientation Policy

Acceptance:
- hard business violations = 0
- illegal orientation = 0
- free text not parsed in solver core

## M3 — Space quality / wall quality
Deliver:
- fragmentation metric
- cavity detection
- reachable space
- dead-space classification
- wall surface map
- wall flatness
- residual-space scoring

Acceptance:
- bad_case_001 cannot reproduce large enclosed internal cavities without strong penalty/rejection
- cavity/dead-space telemetry exists

## M4 — Physics
Deliver:
- SupportGraph
- Compression
- Item/Cluster/Wall Stability
- Stability Debt

Acceptance:
- compression violations = 0
- critical stability violations = 0
- unresolved debt = 0

## M5 — Structure/TopFill/Door
Deliver:
- Block/Layer/Wall Builder
- Top Fill
- conditional flat displays
- Door Closure Planner

## M6 — Search quality
Deliver:
- Multi-start
- Beam
- Backtracking
- Local Search
- time budget

## M7 — Frontend/API integration
Deliver:
- solverVersion=v2
- versioned result
- applyPackingSolution
- stale-result protection

## M8 — Field execution
Later:
- loading sequence
- reachability/insertion path
- tolerance/robustness
- locked placement / incremental repack
