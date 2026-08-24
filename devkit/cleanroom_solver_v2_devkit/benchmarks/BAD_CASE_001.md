# BAD CASE 001 — Wall Hollow + Collision

Asset:
`assets/bad_case_001_wall_hollow_collision.png`

Observed failure classes:
1. large fragmented cavities inside/among cargo walls
2. local cargo overlap/interpenetration
3. residual space created without future fillability awareness
4. wall construction apparently not governed by one authoritative geometry state

Regression purpose:
Solver V2 must never reproduce overlap.
It must expose and minimize enclosed/unreachable cavities.

This case is not a request to visually imitate the old layout. It is a negative test.
