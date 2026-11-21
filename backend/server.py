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
from typing import Any, Dict
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn

# Add backend directory to sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'backend'))

from industrial_packer import IndustrialSmartContainerPacker
from solver_v2.api.adapter import InputAdapter, OutputAdapter
from backend.api.service import DEFAULT_LOADING_API
from backend.api.error_response import classify_api_exception
from backend.api.security import (
    allowed_cors_origin, is_allowed_static_path, is_authorized)
from backend.api.request_limits import (
    MAX_BODY_BYTES, SolveGate, validate_alternative_budget,
    validate_alternative_profiles, validate_alternatives,
    validate_manifest_size, validate_seed, validate_time_budget)
from backend.solver_v2.loading.sequence_planner import compute_loading_order

ANNOTATIONS_DIR = os.path.join(BASE_DIR, 'data', 'annotations')
ANNOTATIONS_FILE = os.path.join(ANNOTATIONS_DIR, 'annotations.jsonl')

# 全局 solve 闸门：默认 1，避免多个 CPU-bound 求解请求互相拖死
SOLVE_GATE = SolveGate()

def get_annotations(filter_solution_id=None, filter_rating=None):
    if not os.path.exists(ANNOTATIONS_FILE):
        return []
    results = []
    with open(ANNOTATIONS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if filter_solution_id and rec.get('solutionId') != filter_solution_id:
                    continue
                if filter_rating and rec.get('rating') != filter_rating:
                    continue
                results.append(rec)
            except Exception:
                pass
    return results

def save_annotation(payload):
    os.makedirs(ANNOTATIONS_DIR, exist_ok=True)
    ann_id = payload.get('annotationId') or f"ann_{int(time.time()*1000)}_{os.urandom(3).hex()}"
    payload['annotationId'] = ann_id
    if 'timestamp' not in payload:
        payload['timestamp'] = time.time()
    with open(ANNOTATIONS_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(payload, ensure_ascii=False) + '\n')
    return payload

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""
    daemon_threads = True

class AICIVSRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # Set workspace root as document directory
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def _send_cors_headers(self):
        origin = allowed_cors_origin(self.headers.get('Origin'))
        if origin:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')

    def _send_no_cache_headers(self):
        """Prevent browser from caching HTML files so edits are always picked up."""
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')

    def _request_authorized(self) -> bool:
        """AICIVS_API_TOKEN 设置后，所有 /api/ 请求（health 除外）需 Bearer Token。"""
        token = (os.environ.get('AICIVS_API_TOKEN') or '').strip()
        if not token or not self.path.startswith('/api/'):
            return True
        return is_authorized(self.headers.get('Authorization'), token)

    def _reject_unauthorized(self):
        self.send_response(401)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        body = {'success': False, 'code': 'UNAUTHORIZED',
                'error': '缺少或无效的 Authorization Bearer Token',
                'category': 'AUTH', 'retryable': False}
        self.wfile.write(json.dumps(body, ensure_ascii=False).encode('utf-8'))

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
        if not self._request_authorized():
            self._reject_unauthorized()
            return
        if not is_allowed_static_path(self.path, BASE_DIR):
            self.send_error(404, "Not Found")
            return
        super().do_HEAD()

    def do_GET(self):
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
                'solvers': ['v1-industrial', 'v2-cleanroom'],
                'timestamp': time.time()
            }
            self.wfile.write(json.dumps(health_data).encode('utf-8'))
            return

        if not self._request_authorized():
            self._reject_unauthorized()
            return

        # 测试平台专用 API 路由
        if self.path.startswith('/api/v1/harness/'):
            from backend.harness_service import HarnessTaskManager, generate_agent_summary
            manager = HarnessTaskManager()

            if self.path == '/api/v1/harness/status':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps(manager.get_status(), ensure_ascii=False).encode('utf-8'))
                return

            if self.path == '/api/v1/harness/agent-summary':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                summary_text = generate_agent_summary()
                self.wfile.write(json.dumps({'agent_summary': summary_text}, ensure_ascii=False).encode('utf-8'))
                return

            if self.path.startswith('/api/v1/harness/case-summary'):
                from urllib.parse import urlparse, parse_qs
                from backend.harness_service import generate_single_case_summary
                query = parse_qs(urlparse(self.path).query)
                case_id = query.get('id', [''])[0]
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                res = generate_single_case_summary(case_id)
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
                return

            if self.path == '/api/v1/harness/report':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                rep_path = os.path.join(BASE_DIR, 'tests', 'harness_reports', 'latest_report.json')
                data = {}
                if os.path.exists(rep_path):
                    try:
                        with open(rep_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                    except Exception:
                        pass
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
                return

            if self.path == '/api/v1/harness/acceptance':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                acc_path = os.path.join(BASE_DIR, 'tests', 'harness_reports', 'acceptance_report.json')
                data = {}
                if os.path.exists(acc_path):
                    try:
                        with open(acc_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                    except Exception:
                        pass
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
                return

            if self.path == '/api/v1/harness/cases':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                from scripts.test_harness.runner import _get_hardcoded_cases, _discover_json_cases, _infer_tags
                cases = list(_get_hardcoded_cases())
                cases.extend(_discover_json_cases([
                    'tests/cases', 'tests/cases/generated', 'tests/cases/random',
                    'tests/cases/production', 'tests/cases/virtual']))
                case_items = []
                seen = set()
                for c in cases:
                    cid = c[2]
                    if cid in seen:
                        continue
                    seen.add(cid)
                    spec = c[0].get('usable', {})
                    case_items.append({
                        'case_id': cid,
                        'name': c[3],
                        'description': c[4],
                        'sku_count': len(c[1]),
                        'tags': _infer_tags(cid, c[4]),
                        'container': f"{spec.get('L',12):.1f}x{spec.get('W',2.4):.1f}x{spec.get('H',2.7):.1f}"
                    })
                self.wfile.write(json.dumps({'total': len(case_items), 'cases': case_items}, ensure_ascii=False).encode('utf-8'))
                return

        # 自学习状态（影子模式）：只读模型/数据摘要，不触发训练
        if self.path == '/api/v1/learning/status':
            payload_out = {'status': 'ok', 'model': {}, 'dataset': {}, 'train_report': {}}
            model_path = os.path.join(BASE_DIR, 'data', 'learning', 'policy_model.json')
            report_path = os.path.join(BASE_DIR, 'data', 'learning', 'train_report.json')
            summary_path = os.path.join(BASE_DIR, 'tests', 'harness_reports', 'learning_dataset_summary.json')
            for key, path in (('model', model_path), ('train_report', report_path),
                              ('dataset', summary_path)):
                if not os.path.exists(path):
                    continue
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if key == 'model':
                        payload_out[key] = {
                            'metrics': data.get('metrics') or {},
                            'k': data.get('k'),
                            'feature_names': data.get('feature_names') or [],
                            'sample_count': len(data.get('samples') or []),
                        }
                    else:
                        payload_out[key] = data
                except Exception as exc:
                    payload_out[key] = {'error': str(exc)}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(payload_out, ensure_ascii=False).encode('utf-8'))
            return

        # 专家打标与方案评审 API: GET /api/v1/annotations
        if self.path.startswith('/api/v1/annotations'):
            from urllib.parse import urlparse, parse_qs
            parsed_query = parse_qs(urlparse(self.path).query)
            sol_id = parsed_query.get('solutionId', [None])[0]
            rating = parsed_query.get('rating', [None])[0]
            items = get_annotations(filter_solution_id=sol_id, filter_rating=rating)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok', 'total': len(items), 'annotations': items}, ensure_ascii=False).encode('utf-8'))
            return

        loading_response = DEFAULT_LOADING_API.dispatch(self.path)
        if loading_response is not None:
            status, payload = loading_response
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
            return

        # Serve static files for all other GET paths (allowlist only)
        if not is_allowed_static_path(self.path, BASE_DIR):
            self.send_error(404, "Not Found")
            return
        super().do_GET()

    def do_POST(self):
        if not self._request_authorized():
            self._reject_unauthorized()
            return
        # 专家打标与方案评审 API: POST /api/v1/annotations
        if self.path == '/api/v1/annotations':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode('utf-8')) if body else {}
                saved = save_annotation(data)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'ok', 'annotation': saved}, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}, ensure_ascii=False).encode('utf-8'))
            return

        # 测试平台专用 POST API 路由
        if self.path.startswith('/api/v1/harness/'):
            from backend.harness_service import HarnessTaskManager
            manager = HarnessTaskManager()

            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length) if content_length > 0 else b'{}'
            payload = {}
            if body:
                try:
                    payload = json.loads(body.decode('utf-8'))
                except Exception:
                    pass

            if self.path == '/api/v1/harness/run':
                res = manager.start_test(payload)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
                return

            if self.path == '/api/v1/harness/stop':
                res = manager.stop_test()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({'stopped': res}, ensure_ascii=False).encode('utf-8'))
                return

        if self.path == '/api/v1/manifest/parse':
            import base64
            try:
                content_length = int(self.headers.get('Content-Length', 0) or 0)
                if content_length <= 0 or content_length > 20 * 1024 * 1024:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(json.dumps({'status': 'error', 'message': '无效的请求体大小'}, ensure_ascii=False).encode('utf-8'))
                    return
                body = self.rfile.read(content_length)
                data = json.loads(body.decode('utf-8')) if body else {}
                b64 = data.get('content_base64', '')
                if ',' in b64 and b64.startswith('data:'):
                    b64 = b64.split(',', 1)[1]
                raw_bytes = base64.b64decode(b64)
                from backend.importer import parse_manifest_bytes
                res = parse_manifest_bytes(
                    raw_bytes=raw_bytes,
                    filename=data.get('filename', 'manifest.xlsx'),
                    container_type=data.get('container_type', '40HQ'),
                    sheet_name=data.get('sheet_name'),
                    override_mapping=data.get('override_mapping'),
                    override_units=data.get('override_units'),
                )
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'error', 'message': f'货单解析失败: {e}'}, ensure_ascii=False).encode('utf-8'))
            return

        if self.path in ('/api/v1/pack', '/api/v2/pack', '/api/v1/loading/jobs'):
            try:
                content_length = int(self.headers.get('Content-Length', 0) or 0)
            except (TypeError, ValueError):
                content_length = -1
            if content_length < 0:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'success': False, 'code': 'INPUT_INVALID',
                    'error': 'Content-Length 非法', 'category': 'INPUT_INVALID',
                    'retryable': False}, ensure_ascii=False).encode('utf-8'))
                return
            if content_length > MAX_BODY_BYTES:
                self.send_response(413)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'success': False, 'code': 'PAYLOAD_TOO_LARGE',
                    'error': f'请求体 {content_length} 字节超过上限 {MAX_BODY_BYTES}',
                    'category': 'INPUT_INVALID', 'retryable': False},
                    ensure_ascii=False).encode('utf-8'))
                return
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
                    validate_manifest_size(cargo_skus)

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
                    seed = validate_seed(payload.get('randomSeed', 42))
                    time_budget = validate_time_budget(payload.get('timeBudgetSec', 20.0))
                    version_num = int(payload.get('version', 1))
                    solution_id = f"sol_{int(time.time()*1000)}_{os.urandom(4).hex()}"

                    from backend.solver_v2.solver.unified_solver import UnifiedSolver
                    from backend.solver_v2.evaluation import (
                        compare_plans, detect_scenario, evaluate_plan, rank_plans)
                    from backend.solver_v2.evaluation.product import build_product_options
                    solver = UnifiedSolver(container_spec)

                    # 统一目标 / 场景模型：先识别"这单该怕什么"，再决定默认策略档。
                    _scenario = detect_scenario(
                        cargo_skus, container_spec,
                        requested_policy=payload.get("policy") or payload.get("planStrategy"))
                    _policy = _scenario["policy"]
                    # 产品交付默认（算法层默认保持关闭）：按策略档生成门区选项，
                    # 请求里的显式字段优先；与验收脚本共用同一实现。
                    _solve_options = build_product_options(
                        cargo_skus, policy=_policy, payload=payload)
                    _algo_mode = str(payload.get("algorithmMode") or payload.get("algorithm_mode") or "unified").strip().lower()
                    if _algo_mode in ("unified", "proto_ems", "proto_ems_flex6"):
                        _solve_options["algorithm_mode"] = _algo_mode

                    # 货单约束可满足性预检（含门区安全容量）：把"约束组合无解"
                    # 从求解后的静默饥饿提前暴露为 422；显式 doorStepDepth=0 会绕过容量检查。
                    from backend.solver_v2.validation.config_precheck import precheck_manifest
                    _pre = precheck_manifest(
                        cargo_skus, container_spec, options=_solve_options)
                    if _pre["errors"]:
                        _first = _pre["errors"][0]
                        _code = _first.get("code", "CONFIG_UNSATISFIABLE")
                        if _code not in ("DOOR_SEAL_CAPACITY_UNSATISFIABLE",
                                         "MULTISTOP_UNSATISFIABLE"):
                            _code = "CONFIG_UNSATISFIABLE"
                        _detail = "；".join(e["message"] for e in _pre["errors"][:5])
                        raise ValueError(f"{_code}: {_detail}")
                    # 自学习建议（影子模式）：只展示，不自动改 options/交付方案
                    from backend.solver_v2.learning import suggest_policy
                    _learning = suggest_policy(cargo_skus, container_spec)

                    if not SOLVE_GATE.try_acquire():
                        self.send_response(429)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        self.send_header('Retry-After', '5')
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            'success': False, 'code': 'SOLVER_BUSY',
                            'error': '求解器正在处理其他任务，请稍后重试',
                            'category': 'CAPACITY', 'retryable': True},
                            ensure_ascii=False).encode('utf-8'))
                        return
                    try:
                        solution = solver.solve(
                            cargo_skus, mode=mode_str, seed=seed, time_budget=time_budget,
                            options=_solve_options,
                        )
                    finally:
                        SOLVE_GATE.release()
                    _sequence_report = compute_loading_order(
                        solution.placements, container_spec)
                    _main_eval = evaluate_plan(
                        solution, cargo_skus, container_spec,
                        scenario=_scenario, policy=_policy)
                    _main_label = ("安全优先"
                                   if (_solve_options["door_step_depth"] > 0
                                       or _solve_options["door_seal_confine"])
                                   else "主方案")
                    _plan_entries = [{
                        "key": "main",
                        "label": _main_label,
                        "profile": "SAFETY_FIRST" if _solve_options["door_step_depth"] > 0
                                   else "BALANCED",
                        "solution": solution,
                        "evaluation": _main_eval,
                        "sequence_report": _sequence_report,
                    }]

                    # 多方案候选：不同"约束档位"而不是不同排序参数——
                    # 业务真正要选的是"多装 3% 但开门危险"还是"安全但少装"。
                    _ALT_PROFILES = ["VOLUME_FIRST", "BALANCED", "SAFETY_FIRST"]
                    _ALT_LABELS = {
                        "VOLUME_FIRST": "装载率优先（无门端安全约束）",
                        "BALANCED": "均衡（封门件归位、不做门端台阶）",
                        "SAFETY_FIRST": "安全优先（门端台阶）",
                    }

                    def _alt_solve_options(profile: str) -> Dict[str, Any]:
                        # 备选按策略档生成，不继承主方案的请求覆盖，保证对比公平
                        return build_product_options(cargo_skus, policy=profile)

                    _alt_count = validate_alternatives(payload.get("alternatives", 0) or 0)
                    _alt_budget = validate_alternative_budget(
                        payload.get("alternativeBudgetSec",
                                    max(1.0, min(60.0, time_budget))),
                        time_budget,
                    )
                    _requested_profiles = validate_alternative_profiles(
                        payload.get("alternativeProfiles"))
                    _alt_skip_notes = []
                    # 单请求总预算上限，避免主方案+3 备选拖到前端超时
                    while _alt_count > 0 and time_budget + _alt_count * _alt_budget > 240.0:
                        _alt_count -= 1
                        _alt_skip_notes.append("备选数量因单请求总预算上限被缩减")
                    _seen_signatures = {
                        (solution.placed_count, round(solution.volume_utilization_pct, 1),
                         _main_eval.get("score"))
                    }
                    for _i in range(_alt_count):
                        _profile = (
                            _requested_profiles[_i]
                            if _i < len(_requested_profiles)
                            else _ALT_PROFILES[_i % len(_ALT_PROFILES)]
                        )
                        if not SOLVE_GATE.try_acquire():
                            _alt_skip_notes.append(f"备选 {_profile} 因求解器忙被跳过")
                            continue
                        try:
                            _alt_solver = UnifiedSolver(container_spec)
                            _alt_sol = _alt_solver.solve(
                                cargo_skus, mode=mode_str, seed=seed + _i + 1,
                                time_budget=_alt_budget,
                                options=_alt_solve_options(_profile),
                            )
                            _alt_seq = compute_loading_order(
                                _alt_sol.placements, container_spec)
                            _alt_eval = evaluate_plan(
                                _alt_sol, cargo_skus, container_spec,
                                scenario=_scenario, policy=_policy)
                        except Exception as _alt_exc:
                            print(f"[PACK-V2] alternative {_profile} skipped: {_alt_exc}")
                            continue
                        finally:
                            SOLVE_GATE.release()
                        _sig = (_alt_sol.placed_count,
                                round(_alt_sol.volume_utilization_pct, 1),
                                _alt_eval.get("score"))
                        if _sig in _seen_signatures:
                            continue
                        _seen_signatures.add(_sig)
                        _plan_entries.append({
                            "key": f"alt-{_i}",
                            "label": _ALT_LABELS.get(_profile, _profile),
                            "profile": _profile,
                            "solution": _alt_sol,
                            "evaluation": _alt_eval,
                            "sequence_report": _alt_seq,
                        })

                    _rank = rank_plans([
                        {"key": e["key"], "label": e["label"], "evaluation": e["evaluation"]}
                        for e in _plan_entries
                    ])
                    _by_key = {e["key"]: e for e in _plan_entries}
                    _chosen = _by_key.get(_rank.get("recommended_key")) or _plan_entries[0]
                    solution = _chosen["solution"]
                    _chosen_eval = _chosen["evaluation"]

                    def _plan_public(ev: Dict[str, Any]) -> Dict[str, Any]:
                        # 对外的评分子集：qa 已在 metrics.geometry_qa，避免重复传输。
                        return {k: v for k, v in (ev or {}).items() if k != "qa"}

                    _plans_meta = []
                    for _entry in _plan_entries:
                        _ev = _entry["evaluation"]
                        _m = _ev.get("metrics") or {}
                        _plans_meta.append({
                            "key": _entry["key"],
                            "label": _entry["label"],
                            "profile": _entry["profile"],
                            "recommended": _entry["key"] == _chosen["key"],
                            "score": _ev.get("score"),
                            "grade": _ev.get("grade"),
                            "utilization": _m.get("utilization_pct"),
                            "placedCount": _m.get("placed_count"),
                            "rigidRatioPct": round(float(_m.get("rigid_ratio", 0.0)) * 100.0, 2),
                            "doorMinSf": _m.get("door_min_sf"),
                            "unstableVolumeM3": _m.get("transport_unstable_volume_m3"),
                            "planQualityScore": _m.get("plan_quality_score"),
                            "gateVerdict": (_ev.get("gate") or {}).get("verdict"),
                            "deductions": _ev.get("deductions") or [],
                            "tradeoffs": ([] if _entry["key"] == _chosen["key"]
                                          else compare_plans(_chosen_eval, _ev)),
                        })

                    elapsed_ms = (time.perf_counter() - t_start) * 1000.0

                    # Output full response (includes V2 schema and visualizer placedBoxes)
                    result = OutputAdapter.to_legacy_response(
                        solution=solution,
                        container=container_spec,
                        cargo_list=cargo_skus,
                        version=version_num,
                        elapsed_ms=elapsed_ms,
                    )
                    result['solutionId'] = solution_id
                    result['planScore'] = _plan_public(_chosen_eval)
                    result['plans'] = _plans_meta
                    result['recommendedPlanKey'] = _chosen["key"]
                    result['scenario'] = _scenario
                    result['selectionNotes'] = (_rank.get("notes") or []) + _alt_skip_notes
                    result['learningSuggestion'] = _learning
                    loading_result = DEFAULT_LOADING_API.register_solver_output(
                        solution_id, solution, container_spec, cargo_skus,
                        plan_score=_plan_public(_chosen_eval),
                        plans=_plans_meta,
                        recommended_plan=_chosen["key"],
                        plan_group_id=solution_id,
                        learning_suggestion=_learning,
                        sequence_report=_chosen.get("sequence_report"),
                    )
                    DEFAULT_LOADING_API.register_alternatives(
                        solution_id,
                        [{
                            "key": _entry["key"],
                            "label": _entry["label"],
                            "solution": _entry["solution"],
                            "evaluation": _entry["evaluation"],
                            "sequence_report": _entry.get("sequence_report"),
                            "recommended": _entry["key"] == _chosen["key"],
                        } for _entry in _plan_entries],
                        container_spec, cargo_skus,
                    )
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
                    self.send_header('X-Solver-Version', 'v2.0.0')
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
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                pass
            except Exception as e:
                status, err_data = classify_api_exception(e)
                if status >= 500:
                    traceback.print_exc()
                    err_data['traceback'] = traceback.format_exc()
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

def run_server(port=8080, host="127.0.0.1"):
    if sys.platform == 'win32':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            pass

    server_address = (host, port)
    httpd = ThreadedHTTPServer(server_address, AICIVSRequestHandler)
    print(f"=================================================================")
    print(f"  3D-AICIVS Python 3 Microservice Server running on {host}:{port}")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"  ⚠️  监听非本机地址 {host}：请确认已配置 AICIVS_API_TOKEN / 反向代理")
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
    host = sys.argv[2] if len(sys.argv) > 2 else os.environ.get('AICIVS_HOST', '').strip()
    if not host:
        host = '0.0.0.0' if os.environ.get('AICIVS_ALLOW_LAN', '') == '1' else '127.0.0.1'
    run_server(port, host)
