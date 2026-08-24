# API V2 Contract

Initial integration may remain synchronous.

Request:

```json
{
  "solverVersion": "v2",
  "mode": "BALANCED",
  "timeBudgetSec": 20,
  "randomSeed": 42,
  "container": {},
  "manifest": []
}
```

Response:

```json
{
  "solutionId": "sol_x",
  "version": 1,
  "solverVersion": "v2.0.0",
  "placements": [],
  "unloaded": [],
  "metrics": {},
  "telemetry": {},
  "warnings": []
}
```

Frontend rule:
backend solution version is authoritative.
