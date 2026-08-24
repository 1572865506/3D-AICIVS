# BLK-007F-8A Test Report

## Result

- Door/wall/transport targeted tests: `34/34 PASS`
- Recomposition/dimension/WIRE targeted tests: `21/21 PASS`
- Full Python regression suite: `322/322 PASS` in `205.054s`
- Frontend Node regression suite: `8/8 PASS`
- Total final regression checks: `330 PASS`, `0 FAIL`

## New and revised coverage

- Tall shallow door columns are hard rejected after door opening.
- Corrected door wall uses a deep, upright, self-stable base.
- Closed-door `+X`, `-X`, `±Y`, and `Z` validation remains active.
- Door-open tipping margin is validated per physical column.
- Mixed-SKU walls use compatible inventory and orientations.
- MAIN display Layer Completion cannot choose the door-only deep orientation.
- Top Fill proves contact against actual supporting cartons.
- Final actual rear restraint is mandatory in the production pipeline.

## Safety regression

- GlobalValidator: `VALID`
- Collision overlap / penetration / OOB / hard violations: `0`
- Door wall lock preservation: `PASS`
- Backend health after restart: `status=ok`, port `8091`
