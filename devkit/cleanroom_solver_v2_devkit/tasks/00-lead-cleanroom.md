# Lead Agent — Clean-Room Integration

Goal:
create Solver V2 without reusing legacy placement algorithms.

First actions:
1. record current baseline commit
2. create `feature/v2-cleanroom-solver`
3. run existing tests
4. capture legacy bad cases/metrics
5. add `backend/solver_v2/` skeleton
6. enforce clean-room rule in CONTRIBUTING/migration notes
7. do not modify default solver behavior yet

Reject PRs that copy legacy placement/scoring code into V2.
