# Search Strategy

Do not search all 1,845 cartons deeply as independent objects.

## Hierarchy

```text
SKU
→ repeated pattern
→ Block
→ Layer
→ Wall
→ residual individual cartons
```

## FAST
- pattern-first greedy
- small multi-start
- strict candidate pruning

## BALANCED
- pattern-first
- bounded beam
- limited backtracking
- local repair

## OPTIMIZE
- broader pattern pool
- larger bounded beam
- local search
- explicit time budget

## Search rule

Hard-invalid states are never kept in beam/search pools.

## Anytime output

Search engine may emit best legal solution whenever improved.
