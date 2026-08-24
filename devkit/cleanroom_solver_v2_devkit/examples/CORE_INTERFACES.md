# Core Interface Sketches

```python
class WorldState:
    def can_commit(self, placement) -> bool: ...
    def commit(self, placement) -> "StateDelta": ...
    def rollback(self, delta: "StateDelta") -> None: ...
```

```python
class FreeSpaceEngine:
    def candidate_spaces(self, cargo, state): ...
    def classify_residuals(self, state): ...
```

```python
class OrientationPolicyEngine:
    def legal_orientations(self, cargo, context, state, space): ...
```

```python
class CandidateValidator:
    def validate(self, candidate, state) -> ValidationResult: ...
```

```python
class CandidateScorer:
    def score(self, candidate, projected_state) -> ScoreBreakdown: ...
```

```python
class GlobalValidator:
    def validate(self, problem, solution) -> GlobalValidationReport: ...
```

Suggested score breakdown:

```text
volume_gain
wall_flatness
surface_continuity
reachable_residual_bonus
zone_preference
weight_balance
door_readiness
-
fragmentation_penalty
enclosed_cavity_penalty
dead_space_penalty
sliver_penalty
orientation_penalty
```
