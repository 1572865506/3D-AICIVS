# BLK-005A — Policy / Eligibility Bottleneck Audit

## Audit boundary

This is a read-only audit. No CargoProfile value, Search Objective, eligibility gate, or Hard Constraint was changed. Counts use the BLK-004B metric-compatible snapshot: final solution minus TOP_FILL placements. One candidate means one `TopFillRegion × SKU` eligibility combination.

## Executive result

Top Fill is primarily **Policy-bottlenecked** at candidate admission. Search/deployment remains a secondary bottleneck after admission, but it cannot access most of the reported 39m³ because only 17 of 770 region/SKU combinations pass policy across both modes.

| metric | BALANCED | OPTIMIZE |
| --- | ---: | ---: |
| regions | 28 | 27 |
| Region×SKU pairs | 392 | 378 |
| policy compatible | 9 | 8 |
| policy incompatible | 383 | 370 |
| eligible | 9 | 8 |
| policy pass rate | 2.30% | 2.12% |
| usable volume | 39.43731m³ | 39.208m³ |
| policy-exposed unique-region volume | 10.26893m³ | 10.03962m³ |
| placed / exposed-region volume | 1.53% | 2.09% |

The last row shows why Search is still secondary rather than irrelevant: conversion inside policy-exposed regions is low and the bounded deployment placed 12/16 cartons. But the first-order loss happens before Search sees candidates.

## Largest rejection contributors

- `topFillPolicy.enabled`: 660 rejections
- `topFillPolicy.minBaseHeight`: 93 rejections

- DEFAULT-sourced primary blocks: 660
- USER_DEFINED-sourced primary blocks: 93

Primary attribution is non-overlapping. For default profiles, `enabled=false` is counted first; their `maxLayers=0` and empty orientation list are recorded in the JSON but not double-counted.

## USER_DEFINED restrictions

- SKU-02 topFillPolicy.minBaseHeight=2.5m and matching TOP_FILL orientation-rule base height
- SKU-14 topFillPolicy.minBaseHeight=1.3m and matching conditional-flat orientation-rule base height

These limits account for the high-base filtering of SKU-02 and SKU-14. They were not changed.

## Conservative DEFAULT restrictions

- REAR_UPRIGHT_DEFAULT, MIDDLE_UPRIGHT_DEFAULT, and DOOR_UPRIGHT_DEFAULT set topFillPolicy.enabled=false
- Those default profiles also declare maxLayers=0 and no Top Fill orientation list, but primary attribution stops at enabled=false

No DEFAULT was automatically relaxed. If all DEFAULT-sourced admission blocks were hypothetically removed while every USER_DEFINED rule, geometry, physics, and inventory fact stayed fixed, the upper bound is **183 additional combinations in BALANCED and 192 in OPTIMIZE, 375 across both modes**. This is an audit ceiling, not an executable policy proposal.

## Best actual Top Fill fillers

Under the active profiles, the ranking is: SKU-14 (17). SKU-14 is the only SKU with actual eligible Top Fill regions in both modes. Counterfactual default-profile geometry/physics candidates rank: SKU-04 (39), SKU-08 (39), SKU-03 (37), SKU-13 (37), SKU-10 (37), SKU-07 (37), SKU-12 (37), SKU-11 (35).

## Answers

1. Primary bottleneck: Policy. Search/deployment is secondary within the small admitted set.
2. Largest rejection fields: `topFillPolicy.enabled`, then `topFillPolicy.minBaseHeight`.
3. USER_DEFINED restrictions: SKU-02 2.5m minimum base; SKU-14 1.3m minimum base and their context-bound orientation rules.
4. Conservative DEFAULT: Top Fill disabled for the three default profile families, with maxLayers=0/empty Top Fill orientations behind that primary gate.
5. Maximum theoretical DEFAULT-only release: 183 BALANCED + 192 OPTIMIZE = 375 Region×SKU combinations.
6. Actual filler: SKU-14. Other SKU rankings are counterfactual only and must not be interpreted as permission.

## Stop condition

BLK-005A audit is complete. No policy was modified and no next BLK was started.
