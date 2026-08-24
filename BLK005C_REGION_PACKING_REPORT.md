# BLK-005C — Top Fill Region Packing & Multi-SKU Deployment

## Outcome

The deployment collapse is removed. Every safely admitted SKU/orientation is retained in a region-local pool, ranked against non-overlapping residual rectangles, and evaluated with depth-two local lookahead. Every attempted placement—including upper layers—still passes the existing HardValidator, SupportGraph/load propagation, compression, stability, collision, bounds, and cavity path before commit. CargoProfile, Safe Admission, Global Search Objective, Door, and hard thresholds were not changed.

| mode | placed count | placed volume m³ | Top Fill utilization | SKU diversity |
| --- | ---: | ---: | ---: | ---: |
| BALANCED | 12 → 36 | 1.07671 → 3.44373 | 2.73% → 8.73% | 1 → 3 |
| OPTIMIZE | 16 → 48 | 1.43561 → 4.36597 | 3.66% → 11.14% | 1 → 4 |

## Deployment funnel

| mode | admitted pool entries | generated | ranked | attempted | committed |
| --- | ---: | ---: | ---: | ---: | ---: |
| BALANCED | 222 | 1346 | 1346 | 36 | 36 |
| OPTIMIZE | 232 | 1912 | 1912 | 50 | 48 |

`BLK005C_DEPLOYMENT_FUNNEL.json` preserves every elimination stage, including NOT_GENERATED, PRUNED, RANKED_OUT, ATTEMPT_FAILED, COLLISION, SUPPORT, STABILITY, LAYER_LIMIT, INVENTORY, REGION_EXHAUSTED, and COMMITTED. `BLK005C_REGION_PLANS.json` contains per-region pools, placements, SKU/orientation mixes, residual rectangles, utilization, layers, and rejection reasons.

## Safety regression

Both modes retain zero overlap, penetration, OOB, hard violations, enclosed cavities, and bridge voids; door_ready remains true. MAIN_BODY conditional-flat and AUTO flat counts remain zero. SKU-02 minBaseHeight=2.5m and SKU-14 minBaseHeight=1.3m, and the normalized USER_DEFINED fingerprint is unchanged.

- TOP-001~012: PASS
- WALL-001~010: PASS
- BLK-005B AUTO admission: PASS
- BLK-005C region packing: PASS
- Full suite: 146/146 PASS

## Stop condition

BLK-005C is complete. BLK-006 was not started.
