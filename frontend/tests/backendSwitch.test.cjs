const test = require('node:test');
const assert = require('node:assert/strict');

global.__VITE_LOADING_API_URL__ = 'http://test/api/v1';
const api = require('../src/backendSwitch.js');
const fixture = structuredClone(require('../mock/demo_loading_result.json'));
Object.assign(fixture, {contract_version:'audit-repair-1',layout_status:'VALID',
  validation:{is_valid:true,violations:[]},executable:true,sequence_status:'FEASIBLE'});

test('FEAPI-001 health check', async () => {
  global.fetch = async url => ({ ok: true, status: 200, json: async () => ({ status: url.endsWith('/loading/health') ? 'ok' : 'bad' }) });
  assert.equal(await api.checkHealth(), api.BackendStatus.ONLINE);
});

test('FEAPI-002 loading fetch', async () => {
  global.fetch = async url => ({ ok: true, status: 200, json: async () => url.endsWith('/status') ? {status:'COMPLETED'} : fixture });
  assert.equal((await api.getResult('demo')).version, 'BLK007C');
});

test('FEAPI-003 schema validate', () => {
  assert.equal(api.validateLoadingResult(fixture).id, fixture.id);
  assert.throws(() => api.validateLoadingResult({ version: 'BLK007B' }), error => error.type === 'SCHEMA_ERROR');
});

test('FEAPI-004 network error', async () => {
  global.fetch = async () => { throw new Error('offline'); };
  await assert.rejects(api.requestJson('/loading/x'), error => error.type === 'NETWORK_ERROR');
});

test('FEAPI-005 404 job', async () => {
  global.fetch = async () => ({ ok: false, status: 404, json: async () => ({ error: 'LOADING_JOB_NOT_FOUND' }) });
  await assert.rejects(api.getResult('missing'), error =>
    error.type === 'SERVER_ERROR' && error.status === 404 && error.message.includes('LOADING_JOB_NOT_FOUND'));
});

test('door policy admission failure is exposed as INPUT_CONSTRAINT, not SERVER_ERROR', async () => {
  global.fetch = async () => ({
    ok: false, status: 422,
    json: async () => ({ error: 'NO_VALID_DOOR_WALL: none', category: 'INPUT_CONSTRAINT', action: '配置门墙 SKU' })
  });
  await assert.rejects(api.requestJson('/loading/jobs'), error =>
    error.type === 'INPUT_CONSTRAINT' && error.status === 422 && error.details.action === '配置门墙 SKU');
});

test('backend traceback is preserved for developer error reports', async () => {
  global.fetch = async () => ({
    ok: false, status: 500,
    json: async () => ({ error: 'WALL_OPTIMIZATION_FAILED', traceback: 'Traceback: solver.py:42' })
  });
  await assert.rejects(api.requestJson('/loading/jobs'), error =>
    error.message.includes('WALL_OPTIMIZATION_FAILED') && error.stack.includes('solver.py:42'));
});

test('integration: LoadingResult -> scene/animation preserves authoritative data', () => {
  const objects = api.sceneObjects(fixture);
  const frames = api.animationFrames(fixture);
  assert.equal(objects.length, fixture.cargo.length);
  assert.deepEqual(objects[0].position, fixture.scene.objects[0].position);
  assert.deepEqual(objects[0].scale, fixture.scene.objects[0].scale);
  assert.deepEqual(objects[0].rotation, fixture.scene.objects[0].rotation);
  assert.equal(objects[0].metadata.orientation, fixture.cargo[0].rotation.orientation);
  assert.deepEqual(frames[0].movements, fixture.animation.frames[0].movements);
  assert.ok(fixture.sequence.steps.every(step => step.placements.every(id => objects.some(object => object.uuid === id))));
});

test('BLK007F77 product dimensions and occupied AABB remain distinct', () => {
  const sku14 = structuredClone(fixture);
  sku14.cargo[0].sku = 'SKU-14';
  sku14.cargo[0].productDimensions = { length: 0.488, width: 0.080, height: 0.336 };
  sku14.cargo[0].occupiedDimensions = { width: 0.080, depth: 0.488, height: 0.336 };
  sku14.scene.objects[0].scale = [0.080, 0.488, 0.336];
  const detail = api.cargoDetail(sku14.cargo[0]);
  const exported = api.cargoExportRows(sku14)[0];
  const scene = api.sceneObjects(sku14)[0];
  assert.deepEqual(detail.productDimensions, { length: 0.488, width: 0.080, height: 0.336 });
  assert.deepEqual(detail.occupiedDimensions, { width: 0.080, depth: 0.488, height: 0.336 });
  assert.deepEqual(scene.scale, [0.080, 0.488, 0.336]);
  assert.equal(exported['产品长(mm)'], 488);
  assert.equal(exported['产品宽(mm)'], 80);
  assert.equal(exported['产品高(mm)'], 336);
});

test('mode is BACKEND unless mock is explicit', () => {
  assert.equal(api.getMode(''), api.CalculationMode.BACKEND);
  assert.equal(api.getMode('?mode=anything'), api.CalculationMode.BACKEND);
  assert.equal(api.getMode('?mode=mock'), api.CalculationMode.MOCK);
});

// 旧缓存和无效验证不得恢复成成功方案。
test('拒绝缺失或无效的验证状态', () => {
  const invalid=structuredClone(fixture);invalid.validation.is_valid=false;
  assert.throws(()=>api.validateLoadingResult(invalid));
  const old=structuredClone(fixture);delete old.contract_version;
  assert.throws(()=>api.validateLoadingResult(old));
});
test('未验证序列不可导出或播放', () => {
  const preview=structuredClone(fixture);preview.executable=false;preview.sequence_status='NOT_EVALUATED';
  assert.equal(api.sceneObjects(preview).length,preview.cargo.length);
  assert.throws(()=>api.animationFrames(preview));
  assert.throws(()=>api.cargoExportRows(preview));
});

test('异步任务完成后读取权威结果',async()=>{
  global.fetch=async url=>({ok:true,status:200,json:async()=>
    url.endsWith('/jobs') ? {job_id:'test-job'} :
    url.endsWith('/status') ? {job_id:'test-job',status:'COMPLETED'} : fixture});
  assert.equal((await api.calculate({})).id,fixture.id);
});
test('已取消的调用获得任务ID后取消后台任务',async()=>{
  const controller=new AbortController();controller.abort();const paths=[];
  global.fetch=async url=>{paths.push(url);return {ok:true,status:202,json:async()=>({job_id:'cancel-job'})};};
  await assert.rejects(api.calculate({},{signal:controller.signal}));
  assert.ok(paths.some(path=>path.endsWith('/cancel-job/cancel')));
});
