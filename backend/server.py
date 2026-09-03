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
sys.path.insert(0, os.path.join(BASE_DIR, 'backend'))

from industrial_packer import IndustrialSmartContainerPacker

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
        if self.path == '/api/v1/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            health_data = {
                'status': 'healthy',
                'service': '3D-AICIVS Industrial Packing Kernel (Python 3)',
                'version': '1.7.0',
                'timestamp': time.time()
            }
            self.wfile.write(json.dumps(health_data).encode('utf-8'))
            return

        # Serve static files for all other GET paths
        super().do_GET()

    def do_POST(self):
        if self.path == '/api/v1/pack':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)

            try:
                payload = json.loads(body.decode('utf-8'))
                container_spec = payload.get('containerSpec', {})
                manifest = payload.get('manifest', [])
                weights = payload.get('weights', None)
                # v1.5.0 前后端参数贯通:gap 货物间距(m) / strategy 装箱策略 / enableCoGBalance 配平开关
                gap = float(payload.get('gap', 0) or 0)
                strategy = payload.get('strategy', 'cluster')
                enable_cog = bool(payload.get('enableCoGBalance', True))
                # v1.7.0 全局规划层开关(默认开启)
                use_plan = bool(payload.get('usePlan', True))

                # Log incoming request summary
                sku_summary = ', '.join([f"{m.get('sku','?')}({m.get('requirement','?')})" for m in manifest[:5]])
                print(f"[PACK] Received: {len(manifest)} SKUs, weights={weights is not None}, specs={container_spec.get('code','?')}")
                print(f"[PACK] SKUs: {sku_summary}{'...' if len(manifest) > 5 else ''}")
                print(f"[PACK] Params: strategy={strategy}, gap={gap}m, enableCoGBalance={enable_cog}")

                packer = IndustrialSmartContainerPacker(container_spec, weights,
                                                        gap=gap, strategy=strategy,
                                                        enableCoGBalance=enable_cog,
                                                        usePlan=use_plan)
                result = packer.pack(manifest)

                print(f"[PACK] Result: placed={result.get('totalCount',0)}, util={result.get('utilization',0)}%, elapsed={result.get('elapsedMs',0)}ms")

                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                traceback.print_exc()
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                err_data = {
                    'success': False,
                    'error': str(e),
                    'traceback': traceback.format_exc()
                }
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
    print(f"  REST API Endpoint: http://localhost:{port}/api/v1/pack")
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
