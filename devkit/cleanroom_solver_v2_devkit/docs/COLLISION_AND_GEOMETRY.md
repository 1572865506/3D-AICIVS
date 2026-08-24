# Collision / Geometry Policy

## Zero tolerance concept

Overlap is not a scoring concern. It is a hard invalid state.

## Geometry representation

Baseline:
- axis-aligned bounding boxes for rectangular cartons
- epsilon policy for touching contacts

Future extension:
- non-box geometries are outside V2 initial scope

## Commit invariant

After every committed placement:
- all boxes are within container
- no pair penetrates beyond epsilon
- spatial index agrees with placement list

## Global invariant

Final GlobalValidator must run an independent collision sweep.

Required metrics:
- overlap_pair_count
- penetration_volume
- out_of_bounds_count

Production-valid target:
all equal zero.
