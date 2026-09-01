# BLK-006D — Search Performance Optimization & Quality Calibration

## Outcome

The canonical beam=2/depth=4/cap=6 GLOBAL run remains COMPLETE_LEGAL and fell from 105.112s to 35.019s. Door readiness and the independent final GlobalValidator remain authoritative; no collision, support, compression, stability, CargoProfile, orientation, or Door threshold was relaxed.

| metric | BLK-006C | BLK-006D |
| --- | ---: | ---: |
| runtime | 105.112s | 35.019s |
| average state expansion | 6103.518ms | 300.513ms |
| best GLOBAL utilization | 40.5038% | 40.2247% |
| returned utilization | 40.5038% | 41.7456% |
| returned source | GLOBAL_SEARCH | LEGACY_INCUMBENT |

## Performance findings

Deep profiling identified the pre-optimization Top 3 as historical state reconstruction (68.9s), inclusive state expansion (42.0s), and candidate enumeration (1.34s). The dominant waste was sequential replay of every historical EMS/extreme-point intermediate state. GLOBAL now reconstructs exact WorldState, collision index, contact/support/load state, while its read-only frontier anchor view is derived directly from immutable placement geometry. Spatial contact/support construction uses the existing uniform hash as broad phase and retains exact narrow phase. Candidate validation remains incremental (new↔existing and new↔new); final COMPLETE always runs full GlobalValidator.

The branch-owned deep snapshot experiment was rejected after profiling because it cost 70.6s. The implemented frontier view is both faster and simpler; branch mutable state remains isolated. CandidateGeometryCache and context-complete TopFillEstimateCache report real hit/miss telemetry. Aggregate/validation caches were not added because their exact context keys produced negligible reuse and their measured stages were not hotspots.

## Quality calibration

Small controlled calibration covered beam 1/2/4, cap 4/6/8, and depth 4/5/6 without Cartesian brute force. Beam=4 did not justify becoming the default when marginal quality did not offset compute. The default remains beam=2/cap=6/depth=4.

Intermediate-score versus final-descendant correlation is recorded as `-0.15239`. The controlled trace does not support changing generic weights; depth, not weight tuning, produced the only quality gain.

`GLOBAL_BEATS_INCUMBENT = false`. Best GLOBAL utilization is 40.5214% versus the validated Legacy incumbent 41.7456%, leaving 1.2242 percentage points. The production result therefore remains `LEGACY_INCUMBENT`; GLOBAL placements are not relabeled as Legacy and the full GLOBAL result remains in diagnostics.

The volume decomposition shows the remaining gap is primarily `Top Fill conversion loss`. Recommended BLK-006E repair target: terminal Top Fill plan selection around residual continuous top regions; preserve all hard gates. No Local Repair, Wall Replacement, or Swap was implemented here.

## Regression

- deterministic replay / branch isolation: PASS / PASS
- TOP-001~012 / WALL-001~010: PASS / PASS
- BLK-005B / 005C / 006A / 006B / 006C: PASS / PASS / PASS / PASS / PASS
- full suite: 160/160 PASS

## Stop condition

BLK-006D is complete. BLK-006E was not started.
