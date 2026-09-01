# Algorithm Runtime Flow

```text
START
  |
  v
Load Container + SKU + Rules
  |
  v
Normalize Units / Axis
  |
  v
Constraint Compiler
  |
  v
Business Conflict Detection
  |
  v
Quantity + Reservation Planner
  |
  v
Adaptive Zone Planning
  |
  v
Pattern Generation
  |  (Block / Layer / Wall patterns)
  v
Create Empty WorldState
  |
  +-------------------------------------------------------------+
  |                                                             |
  v                                                             |
Select next Cargo / Block                                       |
  |                                                             |
  v                                                             |
Identify Placement Context                                      |
  |                                                             |
  v                                                             |
Generate legal Orientations                                     |
  |                                                             |
  v                                                             |
Generate Candidates from EMS / EP / Frontiers                   |
  |                                                             |
  v                                                             |
Hard Validation                                                 |
  |                                                             |
  +-- invalid → reject                                          |
  |                                                             |
  v                                                             |
Residual Space Analysis                                         |
  |                                                             |
  v                                                             |
Soft Scoring                                                    |
  |                                                             |
  v                                                             |
Select Candidate                                                |
  |                                                             |
  v                                                             |
Atomic Commit                                                   |
  |                                                             |
  v                                                             |
Update WorldState                                               |
  |                                                             |
  +-------------------- more cargo? -----------------------------+
  |
  v
Top Fill Phase
  |
  v
Door Closure Phase
  |
  v
Repair / Limited Backtracking / Local Search
  |
  v
Global Validator
  |
  +-- invalid → repair/search/fail
  |
  v
Final Solution + Metrics + Explainability
```

## Phase order

1. special/reserved cargo planning
2. foundation
3. main body / walls
4. controlled gap fill
5. TOP_FILL
6. door closure
7. repair/search
8. global validation

Top Fill is deliberately separated from normal main-body orientation logic.
