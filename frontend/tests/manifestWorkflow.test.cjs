const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const workflow = require('../src/manifestWorkflow.js');

test('FEUX-001A index exposes exactly one user-triggered solver call', () => {
  const html = fs.readFileSync(path.join(__dirname, '../../index.html'), 'utf8');
  const calls = html.match(/runSmartPackingAlgorithm\(true\)/g) || [];
  assert.equal(calls.length, 1);
  assert.match(html, /onclick="runSmartPackingAlgorithm\(true\)"/);
  assert.match(html, /let activeManifest = \[\]/);
});

test('MANIFEST-001 toolbar contains batch operations', () => {
  const html = fs.readFileSync(path.join(__dirname, '../../index.html'), 'utf8');
  ['全选', '反选', '删除选中', '清空货单'].forEach(label => assert.match(html, new RegExp(label)));
});

test('FEUX-001 calculation statuses include manual draft lifecycle', () => {
  assert.deepEqual(Object.keys(workflow.CalculationStatus), ['EMPTY', 'DRAFT', 'DIRTY', 'RUNNING', 'READY', 'FAILED']);
});

test('MANIFEST-003 batch delete removes exactly selected SKU IDs and allows empty manifest', () => {
  const manifest = [{ sku: 'A' }, { sku: 'B' }, { sku: 'C' }];
  assert.deepEqual(workflow.deleteSelected(manifest, new Set(['A', 'C'])), [{ sku: 'B' }]);
  assert.deepEqual(workflow.deleteSelected(manifest, new Set(['A', 'B', 'C'])), []);
});

test('IMPORT-005 manifest validation rejects duplicate IDs and invalid support fields', () => {
  const result = workflow.validateManifest([
    { sku: 'A', w: 1, d: 1, h: 1, weight: 1, quantity: 1 },
    { sku: 'A', w: 1, d: 1, h: 1, weight: 1, quantity: 1, minSupportRatio: 1.2 }
  ]);
  assert.equal(result.valid, false);
  assert.ok(result.errors.some(error => error.includes('重复')));
  assert.ok(result.errors.some(error => error.includes('minSupportRatio')));
});

test('PROFILE-002 self layer limit is independent from allowing other cargo above', () => {
  const profile = workflow.buildCargoProfile({}, {
    allowedOrientation: 'upright', maxStackLayers: 3, allowStackingOnTop: true,
    minSupportRatio: 0.8, maxUnsupportedSpanM: 0.08, topFillState: 'AUTO'
  });
  assert.equal(profile.stackPolicy.maxStackLayers, 3);
  assert.equal(profile.stackPolicy.allowStackingOnTop, true);
});

test('PROFILE-004 conditional flat is explicit and limited to TOP_FILL', () => {
  const profile = workflow.buildCargoProfile({}, {
    allowedOrientation: 'allow_flat', keepUpright: false, topFillState: 'ALLOW',
    topFillMaxLayers: 3, minSupportRatio: 0.8
  });
  const flat = profile.orientationPolicy.rules.find(rule => rule.orientation === 'FLAT');
  assert.deepEqual(flat.allowedRegions, ['TOP_FILL']);
  assert.equal(flat.maxTopFillLayers, 3);
  assert.equal(profile.topFillPolicy.state, 'ALLOW');
});

test('PROFILE-005 saved profile fields are explicitly USER_DEFINED', () => {
  const profile = workflow.buildCargoProfile({}, { allowedOrientation: 'upright' });
  Object.values(profile).forEach(policy => assert.equal(policy.source, 'USER_DEFINED'));
});

test('DOOR-PREFLIGHT explicit legacy door rule is accepted without SKU-name guessing', () => {
  const result = workflow.validateDoorWallAdmission([
    { sku: 'A', w: .5, d: .1, h: .4, weight: 8, quantity: 20, requirement: '封柜门; 可以减少点' }
  ], { intW: 2.35, intH: 2.69 });
  assert.equal(result.valid, true);
  assert.equal(result.wallFormableCandidates[0].sku, 'A');
});

test('DOOR-PREFLIGHT missing door policy is an actionable configuration failure', () => {
  const result = workflow.validateDoorWallAdmission([
    { sku: 'A', w: .5, d: .4, h: .4, weight: 8, quantity: 20, requirement: '放中间' }
  ], { intW: 2.35, intH: 2.69 });
  assert.equal(result.valid, false);
  assert.equal(result.code, 'NO_EXPLICIT_DOOR_CARGO');
});

test('DOOR-PREFLIGHT explicit CargoProfile overrides contradictory requirement text', () => {
  const result = workflow.validateDoorWallAdmission([{
    sku: 'A', w: .5, d: .1, h: .4, weight: 8, quantity: 20, requirement: '封柜门',
    cargoProfile: { placementPolicy: { packingRoles: ['MAIN_WALL'] }, zonePolicy: { preferred: ['MIDDLE'] } }
  }], { intW: 2.35, intH: 2.69 });
  assert.equal(result.valid, false);
  assert.equal(result.code, 'DOOR_PROFILE_CONFLICT');
});
