# BLK-007 — Loading Sequence / Physical Operability

## Outcome

`BLK007A_STATUS = PASS`

`SEQUENCE_FEASIBILITY_RATE = 91.67%`

`NEED_BLK007B = true`

## Required answers

1. `STATIC_FEASIBLE` means the frozen final 3D geometry passes the independent validator. `SEQUENCE_FEASIBLE` additionally means a dependency-respecting order exists and every placement can travel from door plane `x=L` along `-X`, with support and temporary stability valid during the step-by-step simulation.
2. **11 / 12** frozen Benchmark layouts are sequence feasible.
3. Most common failure: **TEMPORARY_INSTABILITY** (`{'TEMPORARY_INSTABILITY': 1}`).
4. Rear Top Fill trapped by front closure: **0 benchmark(s)**.
5. Door Seal too early: **0 benchmark(s)**.
6. Temporary stability is a primary failure in **1 benchmark(s)**; bounded thin-pair debt is explicit and must resolve inside its PLACE_GROUP step.
7. Dependency cycle was found in **0 benchmark(s)**.
8. Largest audited layout contained **380 placements** and planned in **0.378s** (5s target: **True**, 2s target: **True**).
9. Frozen Solver V1 regression: **NONE**; full suite **190 tests**, **PASS**.
10. BLK-007B Sequence-aware Repair is **needed**. This stage only emits SequenceRepairRequest and did not alter any placement.

## Authoritative geometry

Door plane is `x=L`; container rear is `x=0`; loading proceeds deep-to-door. Straight insertion retains final orientation. Swept-volume queries reuse the existing spatial hash as broad phase and exact AABB intersection as narrow phase. Support, blocking, Top Fill ceiling closure and Door Seal-last dependencies are hard edges. Wall/Row/Layer membership only controls deterministic groups and soft priority.

BLK-007B was not started. Frozen packing geometry was not modified.
