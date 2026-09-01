# Residual Space / Hollow-Space Model

The legacy bad case shows large internal voids. Solver V2 must optimize the shape of future free space, not only current occupied volume.

## Space classes

- OPEN_USEFUL
- OPEN_LOW_QUALITY
- REACHABLE_CAVITY
- UNREACHABLE_CAVITY
- SLIVER
- DEAD_SPACE

## Required attributes

Each free-space object should expose or derive:
- geometry
- volume
- minimum opening
- connectivity to door-side free-space network
- insertion directions
- blocking faces
- candidate SKU fit count
- dimension fit quality
- future wall continuity impact

## Enclosed cavity

A cavity is high-risk when:
- it is geometrically empty
- it is enclosed/blocked by committed cargo
- remaining cargo cannot reach/enter it

This should receive strong penalty or be rejected when created above configured threshold.

## Residual quality

Suggested conceptual score:

```text
ResidualQuality =
  useful_open_volume
+ reachable_volume
+ large_regular_space_bonus
- enclosed_cavity_volume
- fragmentation
- sliver_volume
- unreachable_volume
```

Exact weights are tunable; geometry legality is not.
