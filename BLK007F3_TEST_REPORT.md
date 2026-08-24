# BLK-007F-3 Test Report

## Result

`PASS`

- new BLK-007F-3 tests: 8/8 PASS
- full suite: 256/256 PASS
- full-suite runtime: 83.995 s
- acceptance minimum: >=255 tests
- existing tests modified to hide failures: no

## Required cases

- TOP-001: unused-height top regions detected — PASS (17)
- TOP-002: SKU-02 explicit conditional-flat maps to `TOP_HORIZONTAL` — PASS
- TOP-003: region-local one/two/three layers, maximum <=3 — PASS
- TOP-004: unsupported candidate rejected — PASS
- TOP-005: projected top-load overflow rejected — PASS
- TOP-006: canonical 14-SKU utilization exceeds BLK-007F-2 — PASS (71.3574%)

Additional gates:

- locked structural-wall fingerprint preserved — PASS
- Top Fill loading steps depend on supporting wall completion — PASS

## Real-case regression

| Gate | Result |
|---|---:|
| GlobalValidator | VALID |
| overlap pairs | 0 |
| penetration | 0.0 m³ |
| OOB | 0 |
| hard violations | 0 |
| enclosed cavity | 0 |
| support ratio | 1.0 |
| max local top layers | 3 |
| AUTO flat | 0 |
| Door Wall locked count | 28 |
| LoadingSequence feasible | true |
