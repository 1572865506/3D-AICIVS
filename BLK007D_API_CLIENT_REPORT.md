# BLK-007D API Client Report

## Result

The frontend now has a BLK007C-compatible client boundary under `frontend/src/api/` and a non-bundled browser runtime at `frontend/src/backendSwitch.js` for the existing single-file application.

## Configuration and mode

- `VITE_LOADING_API_URL=/api/v1` is defined in `.env`.
- TypeScript reads `import.meta.env.VITE_LOADING_API_URL`; the current non-Vite page reads the equivalent configurable meta/runtime value.
- `CalculationMode.BACKEND` is the default.
- `CalculationMode.MOCK` is entered only by the exact query `?mode=mock`.
- No API hostname or port is embedded in client code.

## Endpoints

- Health: `GET /api/v1/loading/health`.
- Create job: `POST /api/v1/loading/jobs` -> `{job_id,status,result_url,version}`.
- Complete result: `GET /api/v1/loading/{job_id}`.
- Highlight: `GET /api/v1/loading/{job_id}/highlight?type=...&id=...`.
- Existing BLK007C subresources remain unchanged.

The create-job handler reuses the existing solver invocation and `DEFAULT_LOADING_API.register_solver_output`. The new base-result GET returns the already validated BLK007C record; no Packing Solver, sequence, repair, or schema semantics were changed.

## Validation and errors

Every result must contain `version`, `container`, `cargo`, `scene`, `sequence`, and `repair`; `version` must equal `BLK007C`. Errors are normalized to:

- `NETWORK_ERROR`
- `TIMEOUT`
- `SERVER_ERROR`
- `INVALID_RESULT`
- `SCHEMA_ERROR`

Backend errors terminate the calculation. They never invoke the deprecated local packer.

## Health state

`BackendStatus` supports `CHECKING`, `ONLINE`, and `OFFLINE`. The UI shows the corresponding yellow, green, or red status. Explicit Mock Mode is displayed separately in purple.

## HTTP smoke

A real two-carton FAST job was submitted to the local server. POST returned a BLK007C job id; the base GET returned a complete result with two cargo records, two scene objects, two sequence steps, animation frames, camera, metrics, and `version=BLK007C`.
