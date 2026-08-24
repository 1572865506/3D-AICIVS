# Clean-Room Scope

## Framework retained

The following project concepts remain:
- frontend SKU editing/input
- Three.js cargo visualization
- backend HTTP entry
- project configuration
- legacy result rendering compatibility where useful

## Algorithm discarded

Solver V2 begins from an empty algorithm package.

Legacy algorithm files are not implementation references.

Recommended new package:

```text
backend/solver_v2/
  domain/
  constraints/
  geometry/
  world/
  spaces/
  orientation/
  zones/
  quantity/
  patterns/
  candidates/
  graphs/
  physics/
  stability/
  structure/
  topfill/
  door/
  search/
  feasibility/
  robustness/
  validation/
  explain/
  solver/
  api/
```

## Framework adapter boundary

```text
Existing UI / Manifest
        ↓
Input Adapter
        ↓
Solver V2 Canonical Problem
        ↓
Solver V2
        ↓
Canonical Solution
        ↓
Frontend Adapter
        ↓
Existing Three.js renderer
```

Legacy packer must not sit in this path.
