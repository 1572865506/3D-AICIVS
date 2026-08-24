# Coordinate Contract

Solver V2 canonical:
- x: longitudinal / inner wall → doors
- y: width
- z: floor → roof

Origin:
(0,0,0) at far-inner-left-floor.

All adapters must use explicit conversion functions.
Never scatter axis swaps across Three.js or solver code.

Use asymmetric dimension unit tests to expose mistakes.
