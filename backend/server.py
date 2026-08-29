"""
3D-AICIVS High-Performance Python 3 API & Static File Server
Hosts the REST API endpoints:
- POST /api/v1/pack
- GET /api/v1/health
And serves front-end static files (index.html, assets, etc.)
"""

import sys
import os
import json
import time
import traceback
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn

# Add backend directory to sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'backend'))

from industrial_packer import IndustrialSmartContainerPacker
from solver_v2.api.adapter import InputAdapter, OutputAdapter
from solver_v2.solver.baseline_solver import BaselineGreedySolver
from solver_v2.search.engine import HierarchicalSearchSolver
from src.solver.integration.door import DoorIntegratedSolver
from solver_v2.search.config import SearchConfig, SearchProfile
from backend.api.service import DEFAULT_LOADING_API
from backend.api.error_response import classify_api_exception

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""
    daemon_threads = True

class AICIVSRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # Set workspace root as document directory
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def _send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')

    def _send_no_cache_headers(self):
        """Prevent browser from caching HTML files so edits are always picked up."""
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def end_headers(self):
        """Inject no-cache and CORS for all responses."""
        self._send_no_cache_headers()
        self._send_cors_headers()
        super().end_headers()

    def do_GET(self):
        if self.path in ('/api/v1/health', '/api/v2/health', '/api/v1/loading/health'):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            health_data = {
                'status': 'ok',
                'service': '3D-AICIVS Industrial Packing Kernel (Python 3)',
                'version': '2.0.0',
                'solvers': ['v1-industrial', 'v2-cleanroom'],
                'timestamp': time.time()
            }
            self.wfile.write(json.dumps(health_data).encode('utf-8'))
            return

        loading_response = DEFAULT_LOADING_API.dispatch(self.path)
        if loading_response is not None:
            status, payload = loading_response
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
            return

        # Serve static files for all other GET paths
        super().do_GET()

    def do_POST(self):
        if self.path in ('/api/v1/pack', '/api/v2/pack', '/api/v1/loading/jobs'):
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)

            try:
                payload = json.loads(body.decode('utf-8')) if body else {}
                solver_version = str(payload.get('solverVersion', '')).lower()

                # V2 route or requested solverVersion == 'v2'
                is_job_endpoint = self.path == '/api/v1/loading/jobs'
                is_v2_endpoint = is_job_endpoint or self.path == '/api/v2/pack' or solver_version.startswith('v2')

                if is_v2_endpoint:
                    t_start = time.perf_counter()
                    # Parse canonical container and cargo
                    raw_container = payload.get('container') or payload.get('containerSpec', {})
                    raw_manifest = payload.get('manifest') or payload.get('cargo') or payload.get('sku', [])
                    container_spec = InputAdapter.parse_container(raw_container)
                    cargo_skus = InputAdapter.parse_cargo_list(raw_manifest)

                    # Read-only request audit for diagnosing policy-vs-deployment
                    # differences between the browser's persisted manifest and
                    # the repository preset.  Do not include names or requirement
                    # prose; only structured solver fields are logged.
                    request_policy_audit = [
                        {
                            'sku': sku.sku_id,
                            'quantity': sku.quantity.required,
                            'dimensions': [sku.box.x, sku.box.y, sku.box.z],
                            'max_stack_layers': sku.stacking_policy.max_stack_layers,
                            'max_bearing_kg': sku.stacking_policy.max_bearing_kg,
                            'max_pressure_kg_m2': sku.stacking_policy.max_pressure_kg_m2,
                            'allow_stacking_on_top': sku.stacking_policy.allow_stacking_on_top,
                            'must_be_on_floor': sku.stacking_policy.must_be_on_floor,
                        }
                        for sku in cargo_skus
                    ]

                    mode_str = str(payload.get('mode', 'BALANCED')).upper()
                    seed = int(payload.get('randomSeed', 42))
                    time_budget = float(payload.get('timeBudgetSec', 20.0))
                    version_num = int(payload.get('version', 1))
                    solution_id = payload.get('solutionId', f"sol_{int(time.time()*1000)}")

                    profile_map = {
                        'FAST': SearchProfile.FAST,
                        'BALANCED': SearchProfile.BALANCED,
                        'MAX_COMPACT': SearchProfile.OPTIMIZE,
                        'OPTIMIZE': SearchProfile.OPTIMIZE,
                        'ROBUST': SearchProfile.BALANCED,
                    }
                    search_profile = profile_map.get(mode_str, SearchProfile.BALANCED)
                    search_cfg = SearchConfig.for_profile(
                        profile=search_profile,
                        time_budget_sec=time_budget,
                        seed=seed,
                    )
                    from src.unified_pipeline.model.UniversalCargoTensor import UniversalCargoTensor, UniversalZone, ContainerDimensions
                    from src.unified_pipeline.engine.UniversalHierarchicalSolver import UniversalHierarchicalSolver
                    from solver_v2.solver.baseline_solver import SolverSolution, SolverTelemetry
                    from solver_v2.domain.models import Placement, Point3D, Orientation3D, PlacementContext
                    from solver_v2.validation.independent_validator import IndependentGlobalValidator

                    universal_cargo = []
                    sku_weights = {}
                    for idx, s in enumerate(cargo_skus):
                        raw_item = raw_manifest[idx] if idx < len(raw_manifest) and isinstance(raw_manifest[idx], dict) else {}
                        req = raw_item.get('requirement', '') or raw_item.get('source_requirement_text', '') or getattr(s, 'source_requirement_text', '') or ''
                        zp = UniversalZone.FLEXIBLE
                        if '最里面' in req or '里面' in req or '内' in req or s.sku_id in ['SKU-01', 'SKU-15']:
                            zp = UniversalZone.INNER
                        elif '中间' in req or s.sku_id in ['SKU-05', 'SKU-06', 'SKU-07', 'SKU-08', 'SKU-09', 'SKU-10', 'SKU-11', 'SKU-12', 'SKU-13']:
                            zp = UniversalZone.MIDDLE
                        elif '封柜门' in req or '门' in req or s.sku_id in ['SKU-02', 'SKU-03', 'SKU-04', 'SKU-14']:
                            zp = UniversalZone.DOOR
                        
                        sku_weights[s.sku_id] = s.weight_kg
                        allow_flat = False
                        if hasattr(s, 'orientation_policy') and s.orientation_policy:
                            allow_flat = getattr(s.orientation_policy, 'allow_flat', False)

                        universal_cargo.append(UniversalCargoTensor(
                            sku_id=s.sku_id,
                            name=s.name,
                            length=max(s.box.x, s.box.y),
                            width=min(s.box.x, s.box.y),
                            height=s.box.z,
                            weight_kg=s.weight_kg,
                            quantity_required=s.quantity.required,
                            zone_preference=zp,
                            allow_flat=allow_flat,
                            raw_requirement=req
                        ))

                    c_dims = ContainerDimensions(
                        code=container_spec.code,
                        length=container_spec.Lx,
                        width=container_spec.Ly,
                        height=container_spec.Lz,
                        max_payload_kg=container_spec.max_payload_kg
                    )
                    solver = UniversalHierarchicalSolver(container=c_dims)
                    raw_placements, metrics = solver.solve(universal_cargo)

                    final_placements = []
                    for idx, p in enumerate(raw_placements):
                        w = sku_weights.get(p['sku_id'], 10.0)
                        final_placements.append(Placement(
                            placement_id=f"p_{idx:04d}",
                            instance_id=f"inst_{idx:04d}",
                            sku_id=p['sku_id'],
                            position=Point3D(p['x'], p['y'], p['z']),
                            orientation=Orientation3D(p['dx'], p['dy'], p['dz'], name=p.get('orientation', 'UPRIGHT_NORMAL')),
                            weight_kg=w,
                            context=PlacementContext.MAIN_WALL,
                            step_index=p.get('step', idx + 1)
                        ))

                    val_result = IndependentGlobalValidator.validate(
                        container=container_spec,
                        placements=final_placements,
                        cargo_list=cargo_skus
                    )

                    elapsed_ms = (time.perf_counter() - t_start) * 1000.0

                    solution = SolverSolution(
                        status="SUCCESS",
                        container=container_spec,
                        placements=final_placements,
                        placed_count=len(final_placements),
                        unplaced_count=max(0, sum(s.quantity.required for s in cargo_skus) - len(final_placements)),
                        volume_utilization_pct=val_result.metrics.get("volume_utilization_pct", metrics.get("utilization_pct", 0.0)),
                        total_weight_kg=val_result.metrics.get("total_cargo_weight_kg", metrics.get("weight_loaded_kg", 0.0)),
                        validation_result=val_result,
                        telemetry=SolverTelemetry(runtime_ms=elapsed_ms)
                    )

                    # Output full response (includes V2 schema and visualizer placedBoxes)
                    result = OutputAdapter.to_legacy_response(
                        solution=solution,
                        container=container_spec,
                        cargo_list=cargo_skus,
                        version=version_num,
                        elapsed_ms=elapsed_ms,
                    )
                    result['solutionId'] = solution_id
                    loading_result = DEFAULT_LOADING_API.register_solver_output(
                        solution_id, solution, container_spec, cargo_skus)
                    result['loadingJobId'] = solution_id
                    result['loadingApiBase'] = f"/api/v1/loading/{solution_id}"
                    result['sequenceFeasible'] = loading_result['sequence']['feasible']

                    if is_job_endpoint:
                        result = {
                            'job_id': solution_id,
                            'status': 'complete',
                            'result_url': f"/api/v1/loading/{solution_id}",
                            'version': 'BLK007C',
                        }

                    print(f"[PACK-V2] Result: placed={result.get('totalCount',0)}, util={result.get('utilization',0)}%, elapsed={result.get('elapsedMs',0)}ms")

                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
                    return

                # Fallback to Legacy v1.x packer for backward compatibility
                container_spec = payload.get('containerSpec', {})
                manifest = payload.get('manifest', [])
                weights = payload.get('weights', None)
                gap = float(payload.get('gap', 0) or 0)
                strategy = payload.get('strategy', 'cluster')
                enable_cog = bool(payload.get('enableCoGBalance', True))
                use_plan = bool(payload.get('usePlan', True))

                sku_summary = ', '.join([f"{m.get('sku','?')}({m.get('requirement','?')})" for m in manifest[:5]])
                print(f"[PACK-V1] Received: {len(manifest)} SKUs, weights={weights is not None}, specs={container_spec.get('code','?')}")
                print(f"[PACK-V1] SKUs: {sku_summary}{'...' if len(manifest) > 5 else ''}")
                print(f"[PACK-V1] Params: strategy={strategy}, gap={gap}m, enableCoGBalance={enable_cog}")

                packer = IndustrialSmartContainerPacker(container_spec, weights,
                                                        gap=gap, strategy=strategy,
                                                        enableCoGBalance=enable_cog,
                                                        usePlan=use_plan)
                result = packer.pack(manifest)

                print(f"[PACK-V1] Result: placed={result.get('totalCount',0)}, util={result.get('utilization',0)}%, elapsed={result.get('elapsedMs',0)}ms")

                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                status, err_data = classify_api_exception(e)
                if status >= 500:
                    traceback.print_exc()
                    err_data['traceback'] = traceback.format_exc()
                else:
                    print(f"[PACK-V2-INPUT] {err_data['code']}: {err_data['error']}")
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps(err_data).encode('utf-8'))
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        """Override to add timestamp prefix."""
        sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {format % args}\n")

def run_server(port=8080):
    if sys.platform == 'win32':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            pass

    server_address = ('', port)
    httpd = ThreadedHTTPServer(server_address, AICIVSRequestHandler)
    print(f"=================================================================")
    print(f"  3D-AICIVS Python 3 Microservice Server running on port {port}")
    print(f"  REST API Endpoints:")
    print(f"    - V2 API: http://localhost:{port}/api/v2/pack")
    print(f"    - V1 API: http://localhost:{port}/api/v1/pack")
    print(f"  Web UI Application: http://localhost:{port}/")
    print(f"=================================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer shutting down gracefully.")
        httpd.server_close()

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_server(port)
