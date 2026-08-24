# BLK-006E — Terminal Top-Fill Repair & Solution Neighborhood Optimization

## Outcome

BLK-006E is complete. Terminal repair is opt-in and runs strictly after `MAIN → TRANSITION → DOOR → TOP_FILL`. It does not alter Global Search, CargoProfile, Orientation, Door, collision, support, compression, or stability semantics. Every trial uses an isolated state; only a strict volume improvement with full Independent GlobalValidator, physics, cavity, inventory, orientation, and Door validation is accepted. Otherwise the exact parent is retained.

- Stage A gain: **1.270959 m³**
- Stage A runtime: **16.703s**; repair total **17.902s**
- Stage B activated: **False**; gain **0.000000 m³**
- Stage C activated: **False**; gain **0.000000 m³**
- Repair accepted over GLOBAL parent: **True**
- Best repaired GLOBAL utilization: **41.881038%**
- Production incumbent utilization: **41.745603%**
- Reproduced Legacy reference utilization: **41.343100%**
- Returned solution: **GLOBAL_SEARCH**, **41.881038%**
- `GLOBAL_BEATS_INCUMBENT = true`
- Remaining quality gap: **0.000000 percentage points**

## Stage behavior

Stage A froze all MAIN and DOOR placements and generated eight deterministic plan families per TopFillRegion. Region-local alternatives were ranked using generic volume, footprint, height, residual shape, layer completion, support, inventory, and fragmentation terms. Inventory was reconciled at commit across regions. Stage B and Stage C are conditionally gated and contain only bounded terminal-wall width/height/repack operators; a failed or non-monotonic neighborhood is rolled back.

Stage B and Stage C were not activated because Stage A already produced a strictly better COMPLETE_LEGAL solution and exceeded the accepted production incumbent. Activating wall replacement after that success would violate the conditional-stage rule and spend compute without a demonstrated repair need.

## Volume decomposition and quality gap

The GLOBAL parent contained **27.316747 m³** non-TopFill cargo and **3.389059 m³** Top Fill. The selected repaired candidate contained **27.316747 m³** non-TopFill cargo and **4.660018 m³** Top Fill. Remaining waste is reported by exact Region geometry and the rejection Pareto; no policy or hard threshold was relaxed to close it.

Compared with the accepted production incumbent, repaired GLOBAL is **0.135435 percentage points higher**. The residual TopFill funnel is dominated by **fragmentation/ranking exclusions** rather than hard physics failure: **3114 / 3133 (99.39%)** recorded exclusions were ranked-out alternatives, while support rejected **12 / 3133 (0.38%)**. Final unused container volume is **44.374650 m³** and TopFill utilization is **12.1954%**; these are descriptive residuals, not grounds for weakening constraints.

Primary remaining cause: **NONE_GLOBAL_REPAIRED_SOLUTION_BEATS_INCUMBENT**. The next repair target, if needed, is **NONE_REQUIRED**. This report does not enter BLK-007 and does not implement unrestricted Local Search, random perturbation, Swap, or loading sequence work.

## Safety and regression

- COMPLETE_LEGAL: **True**
- door_ready: **True**
- GlobalValidator: **True**
- overlap / penetration / OOB / hard violations: **0 / 0 / 0 / 0**
- enclosed cavity / bridge void: **0 / 0**
- AUTO flat / MAIN conditional-flat: **0 / 0**
- deterministic replay: **PASS** (TFR-012 plus preserved GLOBAL replay tests)
- branch isolation / rollback: **PASS**
- full suite: **PASS (172 tests)**
