# Geometry Test Requirements

Required unit/property tests:
- non-overlap touching faces
- epsilon touching
- full overlap
- partial overlap
- containment
- out-of-bounds
- atomic commit rollback
- spatial index consistency
- asymmetric orientation transforms

Property:
after every committed placement, pairwise penetration must remain zero.
