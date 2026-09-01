# Solver V2 Architecture

## 1. Domain

Canonical objects:
- ContainerSpec
- CargoSKU
- CargoInstance
- QuantityPlan
- PlacementRule
- OrientationPolicy
- CompressionPolicy
- StackingPolicy
- PackingRole
- PlacementContext
- CandidatePlacement
- Placement
- Solution

## 2. Constraint Compiler

Converts UI/business input into structured rules.

No core solver module may parse free-text requirements.

Rule modes:
- REQUIRED
- PREFER
- AVOID
- FORBIDDEN

## 3. WorldState

Single authoritative mutable/reversible state:

```text
placements
remaining_quantity
spatial_index
ems
extreme_points
reachable_spaces
support_graph
contact_graph
clusters
walls
zones
reservations
stability_debt
center_of_mass
weight
metrics
search_trace
```

## 4. Free Space Engine

Hybrid:
- EMS
- Extreme Points
- Reachable Space analysis
- Dead Space classification
- cavity detection
- fragmentation analysis

A free space is not assumed useful merely because its volume is non-zero.

## 5. Candidate Generator

Generates positions from:
- EMS corners
- Extreme Points
- wall frontier
- top-fill surfaces
- door-fill frontier

## 6. Hard Validation Pipeline

Order:

```text
bounds
→ collision
→ orientation legality
→ hard zone
→ stacking
→ support
→ compression
→ critical stability
→ accessibility rule where enabled
```

Any failure => INVALID.

## 7. Soft Scoring

Only valid candidates receive scores.

Core components:
- immediate volume gain
- residual space quality
- wall flatness
- surface continuity
- fragmentation penalty
- enclosed-cavity penalty
- dead-space penalty
- zone preference
- SKU grouping
- weight balance
- door readiness
- orientation preference
- robustness

## 8. Atomic Commit

A placement commit must update atomically:
- placement list
- spatial index
- EMS
- Extreme Points
- SupportGraph
- ContactGraph
- wall/cluster state
- remaining quantity
- COM/weight
- cavity/dead-space state

If any update fails, rollback the complete placement.

## 9. Independent Global Validator

The final validator must re-check the solution independently from the search path.

A solution with any overlap/penetration is invalid even if utilization is high.
