# BLK-007C Three.js mock

`demo_loading_result.json` uses the same contract as `/api/v1/loading/{id}/layout`.
Import `loading_mock.js`, call `loadDemo()`, then pass the result to
`createThreeScene(THREE, result)`. Coordinates are already Solver canonical
coordinates; do not swap axes or mirror X. `playLoading()` reveals cargo in the
authoritative sequence order.
