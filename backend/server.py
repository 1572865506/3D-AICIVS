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
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn

# Add backend directory to sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'backend'))

from backend.api.service import DEFAULT_LOADING_API
from backend.api.jobs import JobManager, TERMINAL
from backend.api.static_files import public_file
from backend.api.error_response import classify_api_exception

JOBS = JobManager()

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""
    daemon_threads = True
    request_slots = threading.BoundedSemaphore(32)

    def process_request(self, request, client_address):
        if not self.request_slots.acquire(blocking=False):
            try: request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            finally: self.shutdown_request(request)
            return
        try: super().process_request(request, client_address)
        except Exception:
            self.request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try: super().process_request_thread(request, client_address)
        finally: self.request_slots.release()

class AICIVSRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # Set workspace root as document directory
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def translate_path(self, path):
        return public_file(BASE_DIR, path) or os.path.join(BASE_DIR, '__not_public__', '404')

    def _send_cors_headers(self):
        origin = self.headers.get('Origin')
        allowed = os.environ.get('AICIVS_ALLOWED_ORIGINS', '').split(',')
        if origin and origin in allowed:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
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

    def do_HEAD(self):
        if self.path in ('/api/v1/pack', '/api/v2/pack', '/api/v1/loading/jobs'):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            if self.path == '/api/v2/pack':
                self.send_header('X-Solver-Version', 'v2.0.0')
            self.end_headers()
            return
        if self.path in ('/api/v1/health', '/api/v2/health', '/api/v1/loading/health'):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            if self.path == '/api/v2/health':
                self.send_header('X-Solver-Version', 'v2.0.0')
            self.end_headers()
            return
        super().do_HEAD()

    def _json(self, status, payload):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8'))

    def do_GET(self):
        parts=self.path.split('?')[0].strip('/').split('/')
        if len(parts)>=4 and parts[:3]==['api','v1','loading'] and parts[3]!='health':
            job=JOBS.get(parts[3])
            if job is not None:
                if len(parts)==5 and parts[4]=='status':
                    return self._json(200,{k:v for k,v in job.items() if k!='result'})
                if job['result'] is None:
                    return self._json(202 if job['status'] not in TERMINAL else 409,
                                      {k:v for k,v in job.items() if k!='result'})
                # 有效结果按现有产品路由读取；任务管理器持有有界生命周期。
                from backend.api.service import LoadingAPIService
                service=LoadingAPIService()
                service.put_result(job['result']['loading'])
                response=service.dispatch(self.path)
                if response is not None:return self._json(*response)

        if self.path in ('/api/v1/health', '/api/v2/health', '/api/v1/loading/health'):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            if self.path == '/api/v2/health':
                self.send_header('X-Solver-Version', 'v2.0.0')
            self.end_headers()
            health_data = {
                'status': 'ok',
                'service': '3D-AICIVS Industrial Packing Kernel (Python 3)',
                'version': '2.0.0',
                'solvers': ['v2-cleanroom'],
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
        parts=self.path.strip('/').split('/')
        if len(parts)==5 and parts[:3]==['api','v1','loading'] and parts[4]=='cancel':
            return self._json(202 if JOBS.cancel(parts[3]) else 404, {'job_id':parts[3], 'cancel_requested':True})

        if self.path in ('/api/v1/pack', '/api/v2/pack', '/api/v1/loading/jobs'):
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length < 0 or content_length > 2*1024*1024:
                    raise ValueError('请求体不得超过 2 MiB')
                self.connection.settimeout(15)
                body = self.rfile.read(content_length)
                payload = json.loads(body.decode('utf-8')) if body else {}
                if not isinstance(payload, dict):
                    raise ValueError('请求必须为 JSON 对象')
                solver_version = str(payload.get('solverVersion', '')).lower()

                # V2 route or requested solverVersion == 'v2'
                is_job_endpoint = self.path == '/api/v1/loading/jobs'
                is_v2_endpoint = is_job_endpoint or self.path == '/api/v2/pack' or solver_version.startswith('v2')

                if is_v2_endpoint:
                    job_id = JOBS.submit(payload)
                    if is_job_endpoint:
                        return self._json(202, {'job_id':job_id,'status':'QUEUED',
                                              'result_url':f'/api/v1/loading/{job_id}','version':'BLK007C'})
                    # 兼容同步 pack 接口；计算同样运行于受限进程。
                    while True:
                        job=JOBS.get(job_id)
                        if job['status'] in TERMINAL:break
                        time.sleep(.02)
                    if job['result'] is not None:
                        return self._json(200,job['result']['legacy'])
                    return self._json(504 if job['status']=='TIMED_OUT' else 422,
                                      {'success':False,'status':job['status'],'error':job['error']})

                return self._json(410, {'success':False,'error':'旧版求解入口已停用，请使用 /api/v2/pack 或 /api/v1/loading/jobs'})
            except OverflowError:
                self._json(429, {"error":"任务队列已满，请稍后重试"})
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                pass
            except Exception as e:
                status, err_data = classify_api_exception(e)
                if status >= 500:
                    traceback.print_exc()
                    err_data['error'] = '内部计算失败，请使用服务端日志定位'
                    err_data['details'] = {}
                else:
                    print(f"[PACK-V2-INPUT] {err_data['code']}: {err_data['error']}")
                try:
                    self.send_response(status)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(json.dumps(err_data).encode('utf-8'))
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                    pass
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

    server_address = (os.environ.get('AICIVS_HOST', '127.0.0.1'), port)
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
        JOBS.close()
        httpd.server_close()

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_server(port)
