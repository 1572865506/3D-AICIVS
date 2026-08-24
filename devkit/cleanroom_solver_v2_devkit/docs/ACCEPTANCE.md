# Acceptance Criteria

## Absolute validity gates

A solution is INVALID if any:
- overlap pair exists
- penetration volume > epsilon
- cargo exceeds container bounds
- hard business rule violated
- forbidden orientation used
- payload exceeded
- compression violated
- critical stability violated
- final Stability Debt remains

No score can compensate for these.

## Bad Case 001 gates

Visual reference:
`benchmarks/assets/bad_case_001_wall_hollow_collision.png`

V2 must report:
- overlap_pair_count
- penetration_volume
- enclosed_cavity_count
- enclosed_cavity_volume
- unreachable_residual_volume
- dead_space_volume
- fragmentation_score
- wall_flatness
- wall_occupancy
- reachable_residual_volume

Required:
- overlap_pair_count = 0
- penetration_volume = 0
- large enclosed cavities must be either prevented or explicitly penalized/reported

## Benchmark performance target

For ~14 SKUs / 1,845 cartons on modern 8–16 core CPU:

FAST:
- P50 target < 3 s
- P95 target < 8 s

BALANCED:
- P50 target < 10 s
- P95 target < 20 s

OPTIMIZE:
- default time budget ~60 s
- return best legal solution at timeout

These are engineering targets, not pre-validation guarantees.

## Required telemetry

- runtime_ms
- candidates_generated
- candidates_rejected_by_reason
- spatial_queries
- ems_peak
- extreme_points_peak
- cavity_count
- cavity_volume
- dead_space_volume
- reachable_residual_volume
- wall_flatness
- wall_occupancy
- backtracks
- search_states
- solutions_found
- best_score_over_time
- volume_utilization
- effective_utilization
- loaded/unloaded by SKU
