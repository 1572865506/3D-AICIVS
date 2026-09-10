(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.BLK007D = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  const CalculationMode = Object.freeze({ BACKEND: 'BACKEND', MOCK: 'MOCK' });
  const BackendStatus = Object.freeze({ ONLINE: 'ONLINE', OFFLINE: 'OFFLINE', CHECKING: 'CHECKING' });
  // 前端轮询上限；计算硬超时由后台工作进程执行。
  const LOADING_JOB_TIMEOUT_MS = 300000;
  const ErrorType = Object.freeze({
    NETWORK_ERROR: 'NETWORK_ERROR', TIMEOUT: 'TIMEOUT', SERVER_ERROR: 'SERVER_ERROR',
    INVALID_RESULT: 'INVALID_RESULT', SCHEMA_ERROR: 'SCHEMA_ERROR',
    INPUT_CONSTRAINT: 'INPUT_CONSTRAINT'
  });

  class BackendError extends Error {
    constructor(type, message, status, details) {
      super(message);
      this.name = 'BackendError';
      this.type = type;
      this.status = status;
      this.details = details || null;
      if (details && details.traceback) this.stack = `${this.stack || message}\nBackend traceback:\n${details.traceback}`;
    }
  }

  function getMode(search) {
    const query = new URLSearchParams(search === undefined ? (root.location ? root.location.search : '') : search);
    return query.get('mode') === 'mock' ? CalculationMode.MOCK : CalculationMode.BACKEND;
  }

  function configuredBase() {
    if (root.__VITE_LOADING_API_URL__) return String(root.__VITE_LOADING_API_URL__).replace(/\/$/, '');
    const meta = root.document && root.document.querySelector('meta[name="loading-api-base"]');
    if (meta && meta.content) return meta.content.replace(/\/$/, '');
    throw new BackendError(ErrorType.SCHEMA_ERROR, 'VITE_LOADING_API_URL is not configured');
  }

  function validateLoadingResult(value) {
    if (!value || typeof value !== 'object') throw new BackendError(ErrorType.SCHEMA_ERROR, 'LoadingResult must be an object');
    const missing = ['version', 'container', 'cargo', 'scene', 'sequence', 'repair'].filter(key => !(key in value));
    if (missing.length) throw new BackendError(ErrorType.SCHEMA_ERROR, `LoadingResult missing: ${missing.join(', ')}`);
    if (value.version !== 'BLK007C') throw new BackendError(ErrorType.SCHEMA_ERROR, `Unsupported LoadingResult version: ${value.version}`);
    if (!Array.isArray(value.cargo) || !value.scene || !Array.isArray(value.scene.objects)) {
      throw new BackendError(ErrorType.SCHEMA_ERROR, 'Invalid cargo or scene.objects');
    }
    if (!value.sequence || !Array.isArray(value.sequence.steps) || !value.repair || !Array.isArray(value.repair.groups)) {
      throw new BackendError(ErrorType.SCHEMA_ERROR, 'Invalid sequence or repair groups');
    }
    if (!(getMode() === CalculationMode.MOCK && value.demo === true) &&
        (value.contract_version !== 'audit-repair-1' || value.layout_status !== 'VALID' ||
        !value.validation || value.validation.is_valid !== true)) {
      throw new BackendError(ErrorType.INVALID_RESULT, '布局未通过当前版本验证，请重新计算', undefined, value.validation);
    }
    value.cargo.forEach(item => {
      const product = item.productDimensions;
      const occupied = item.occupiedDimensions;
      const axes = item.axisDefinition;
      if (!product || !occupied || !axes ||
          !['length', 'width', 'height'].every(key => Number(product[key]) > 0) ||
          !['width', 'depth', 'height'].every(key => Number(occupied[key]) > 0)) {
        throw new BackendError(ErrorType.SCHEMA_ERROR, `Invalid cargo dimensions: ${item.sku || item.id || 'unknown'}`);
      }
    });
    return value;
  }

  async function requestJson(path, init, timeoutMs) {
    const controller = new AbortController();
    const userSignal = init && init.signal;
    const abortListener=()=>controller.abort();
    if (userSignal) {
      if (userSignal.aborted) {
        throw new BackendError(ErrorType.ABORTED || 'ABORTED', '用户已终止算柜推演');
      }
      userSignal.addEventListener('abort', abortListener, {once:true});
    }
    const timer = setTimeout(() => controller.abort(), timeoutMs || LOADING_JOB_TIMEOUT_MS);
    try {
      let response;
      const fetchInit = Object.assign({ cache: 'no-store' }, init || {}, { signal: controller.signal });
      delete fetchInit.signal; // ensure single signal attached
      fetchInit.signal = controller.signal;
      try { response = await root.fetch(`${configuredBase()}${path}`, fetchInit); }
      catch (error) {
        if (userSignal && userSignal.aborted) {
          throw new BackendError(ErrorType.ABORTED || 'ABORTED', '用户已终止算柜推演');
        }
        if (error && error.name === 'AbortError') throw new BackendError(ErrorType.TIMEOUT, 'Backend request timed out');
        throw new BackendError(ErrorType.NETWORK_ERROR, error && error.message ? error.message : 'Network request failed');
      }
      if (!response.ok) {
        let details = null;
        try { details = await response.json(); } catch (_) { /* non-JSON error response */ }
        const message = details && (details.error || details.message)
          ? `HTTP ${response.status}: ${details.error || details.message}`
          : `HTTP ${response.status}`;
        const type = response.status === 422 || (details && details.category === 'INPUT_CONSTRAINT')
          ? ErrorType.INPUT_CONSTRAINT : ErrorType.SERVER_ERROR;
        throw new BackendError(type, message, response.status, details);
      }
      try { return await response.json(); }
      catch (_) { throw new BackendError(ErrorType.INVALID_RESULT, 'Backend returned non-JSON content'); }
    } finally {
      clearTimeout(timer);
      if(userSignal) userSignal.removeEventListener('abort',abortListener);
    }
  }

  async function checkHealth() {
    try {
      const value = await requestJson('/loading/health', {}, 5000);
      return value.status === 'ok' || value.status === 'healthy' ? BackendStatus.ONLINE : BackendStatus.OFFLINE;
    } catch (_) { return BackendStatus.OFFLINE; }
  }

  async function createJob(payload, options = {}) {
    const result = await requestJson('/loading/jobs', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      signal: options.signal
    }, LOADING_JOB_TIMEOUT_MS);
    if (!result || typeof result.job_id !== 'string') throw new BackendError(ErrorType.INVALID_RESULT, 'Create-job response has no job_id');
    return result.job_id;
  }

  async function getResult(jobId, options = {}) {
    const path=`/loading/${encodeURIComponent(jobId)}`;
    const deadline=Date.now()+LOADING_JOB_TIMEOUT_MS;
    while (Date.now()<deadline) {
      const job=await requestJson(`${path}/status`,{signal:options.signal},10000);
      if (job.status === 'COMPLETED' || job.status === 'TIMED_OUT') {
        try {
          return validateLoadingResult(await requestJson(path,{signal:options.signal},10000));
        } catch(error) {
          if (job.status === 'TIMED_OUT') throw new BackendError(ErrorType.TIMEOUT,'计算超时，尚无可用的验证结果');
          throw error;
        }
      }
      if (!['QUEUED','RUNNING','FAILED','CANCELLED'].includes(job.status)) {
        throw new BackendError(ErrorType.SCHEMA_ERROR,'未知任务状态');
      }
      if (job.status==='FAILED' || job.status==='CANCELLED') {
        throw new BackendError(ErrorType.INVALID_RESULT,job.error && job.error.error || `任务 ${job.status}`);
      }
      await new Promise(resolve=>setTimeout(resolve,200));
    }
    throw new BackendError(ErrorType.TIMEOUT,'等待计算结果超时');
  }

  async function getHighlight(jobId, type, id) {
    return requestJson(`/loading/${encodeURIComponent(jobId)}/highlight?type=${encodeURIComponent(type)}&id=${encodeURIComponent(id)}`, {}, 10000);
  }

  async function loadMock() {
    let response;
    try { response = await root.fetch('/frontend/mock/demo_loading_result.json', { cache: 'no-store' }); }
    catch (error) { throw new BackendError(ErrorType.NETWORK_ERROR, error.message || 'Mock file unavailable'); }
    if (!response.ok) throw new BackendError(ErrorType.SERVER_ERROR, `Mock HTTP ${response.status}`, response.status);
    const demo = await response.json();
    demo.demo = true; demo.executable = false; demo.sequence_status = 'NOT_EVALUATED';
    return validateLoadingResult(demo);
  }

  async function calculate(payload, options = {}) {
    if (getMode() === CalculationMode.MOCK) return loadMock();
    // 提交不使用用户信号，确保能取得任务 ID 后发送显式取消。
    const jobId = await createJob(payload);
    const cancel=()=>requestJson(`/loading/${encodeURIComponent(jobId)}/cancel`,{method:'POST'},5000).catch(()=>{});
    if (options.signal && options.signal.aborted) {
      await cancel(); throw new BackendError('ABORTED','用户已终止算柜推演');
    }
    if (options.signal) options.signal.addEventListener('abort',cancel,{once:true});
    try { return await getResult(jobId, options); }
    catch(error) { await cancel(); throw error; }
    finally { if (options.signal) options.signal.removeEventListener('abort',cancel); }
  }

  function sceneObjects(result) {
    const validated = validateLoadingResult(result);
    const cargoById = new Map(validated.cargo.map(item => [item.id, item]));
    return validated.scene.objects.map(object => {
      const metadata = Object.assign({}, object.metadata);
      const cargo = cargoById.get(object.uuid);
      if (!metadata.orientation && cargo && cargo.rotation) metadata.orientation = cargo.rotation.orientation;
      return {
        uuid: object.uuid, position: object.position.slice(), scale: object.scale.slice(),
        rotation: object.rotation.slice(), material: Object.assign({}, object.style), metadata
      };
    });
  }

  function assertExecutable(result) {
    validateLoadingResult(result);
    if (result.executable !== true || result.sequence_status !== 'FEASIBLE') {
      throw new BackendError(ErrorType.INVALID_RESULT, '装载顺序尚未验证通过，暂不可执行或导出');
    }
  }

  function animationFrames(result) {
    assertExecutable(result);
    return validateLoadingResult(result).animation.frames.map(frame => ({
      step: frame.step, objects: frame.objects.slice(), from: frame.from.slice(), to: frame.to.slice(),
      duration: frame.duration, movements: (frame.movements || []).map(m => ({ object: m.object, from: m.from.slice(), to: m.to.slice() }))
    }));
  }

  function cargoDetail(cargo) {
    const product = cargo.productDimensions;
    const occupied = cargo.occupiedDimensions;
    return {
      productDimensions: Object.assign({}, product),
      occupiedDimensions: Object.assign({}, occupied),
      axisDefinition: Object.assign({}, cargo.axisDefinition),
      productLabel: '规格尺寸(长×宽×高)',
      occupiedLabel: '占用空间'
    };
  }

  // Export-facing rows deliberately use physical product dimensions. Placement
  // AABB remains available under the explicitly named occupied-space columns.
  function cargoExportRows(result) {
    assertExecutable(result);
    return validateLoadingResult(result).cargo.map(cargo => ({
      SKU: cargo.sku,
      '产品长(mm)': Math.round(cargo.productDimensions.length * 1000),
      '产品宽(mm)': Math.round(cargo.productDimensions.width * 1000),
      '产品高(mm)': Math.round(cargo.productDimensions.height * 1000),
      '占用宽(mm)': Math.round(cargo.occupiedDimensions.width * 1000),
      '占用深(mm)': Math.round(cargo.occupiedDimensions.depth * 1000),
      '占用高(mm)': Math.round(cargo.occupiedDimensions.height * 1000)
    }));
  }

  return { CalculationMode, BackendStatus, ErrorType, BackendError, getMode, configuredBase,
    validateLoadingResult, requestJson, checkHealth, createJob, getResult, getHighlight,
    loadMock, calculate, sceneObjects, animationFrames, cargoDetail, cargoExportRows };
});
