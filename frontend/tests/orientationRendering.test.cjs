const test = require('node:test');
const assert = require('node:assert/strict');
const orientation = require('../src/orientationRendering.js');

class MockUvAttribute {
  constructor(count) { this.values = Array.from({ length: count }, (_, i) => [i % 2, Math.floor(i / 2) % 2]); this.needsUpdate = false; }
  getX(i) { return this.values[i][0]; }
  getY(i) { return this.values[i][1]; }
  setXY(i, u, v) { this.values[i] = [u, v]; }
}
class MockBoxGeometry {
  constructor() {
    this.groups = Array.from({ length: 6 }, (_, face) => ({ start: face * 6, count: 6, materialIndex: face }));
    const pattern = [0, 2, 1, 2, 3, 1];
    this.index = { getX: pointer => Math.floor(pointer / 6) * 4 + pattern[pointer % 6] };
    this.attributes = { uv: new MockUvAttribute(24) };
    this.userData = {};
  }
}
const THREE = { BoxGeometry: MockBoxGeometry };

test('VISORI-001 upright normal retains physical product faces', () => {
  const mapping = orientation.getFaceMapping('UPRIGHT_NORMAL');
  assert.deepEqual(mapping.faces.map(face => face.materialIndex), [0, 1, 2, 3, 4, 5]);
  assert.deepEqual(mapping.productUpThree, [0, 1, 0]);
});

test('VISORI-002 upright rotated moves label faces without rotating AABB', () => {
  const mapping = orientation.getFaceMapping('UPRIGHT_ROTATED');
  assert.deepEqual(mapping.faces.slice(0, 2).map(face => face.materialIndex), [4, 5]);
  assert.deepEqual(mapping.productUpThree, [0, 1, 0]);
  assert.equal(mapping.orientation, 'UPRIGHT_ROTATED');
});

test('VISORI-003 flat orientation makes original product-up horizontal', () => {
  assert.deepEqual(orientation.getFaceMapping('FLAT_XZ').productUpThree, [0, 0, 1]);
  assert.deepEqual(orientation.getFaceMapping('FLAT_ZX').productUpThree, [1, 0, 0]);
});

test('VISORI-004 side orientation maps product-up to a horizontal scene axis', () => {
  assert.deepEqual(orientation.getFaceMapping('SIDE_YZ').productUpThree, [0, 0, 1]);
  assert.deepEqual(orientation.getFaceMapping('SIDE_ZY').productUpThree, [1, 0, 0]);
});

test('VISORI-005 same SKU orientations share materials without array-state pollution', () => {
  const cache = new orientation.OrientationMaterialCache();
  const base = [{ id: 'side+' }, { id: 'side-' }, { id: 'top' }, { id: 'bottom' }, { id: 'label+' }, { id: 'label-' }];
  const upright = cache.get('SKU-14', 'UPRIGHT_NORMAL', base);
  const flat = cache.get('SKU-14', 'FLAT_XZ', base);
  assert.notEqual(upright, flat);
  assert.equal(upright[4], flat[4]);
  assert.equal(upright[4], base[4]);
  assert.throws(() => upright.push({}), TypeError);
  assert.equal(flat.length, 6);
});

test('VISORI-006 texture registry count follows SKU entries, not placements', () => {
  const registry = new orientation.PackageTextureRegistry();
  const textureSet = { label: {} };
  registry.set('SKU-14', textureSet);
  for (let i = 0; i < 500; i++) assert.equal(registry.get('SKU-14'), textureSet);
  assert.equal(registry.diagnostics().entries, 1);
  assert.equal(registry.diagnostics().hits, 500);
});

test('VISORI-007 geometry cache contains at most six shared variants', () => {
  const cache = new orientation.OrientationGeometryCache(THREE);
  orientation.ORIENTATIONS.forEach(name => {
    assert.equal(cache.get(name), cache.get(name));
  });
  assert.equal(cache.diagnostics().entries, 6);
  assert.equal(cache.diagnostics().misses, 6);
  assert.equal(cache.diagnostics().hits, 6);
});

test('VISORI-008 face mapping changes UV/material data only', () => {
  const geometry = orientation.createOrientationGeometry(THREE, 'FLAT_XZ');
  assert.equal(geometry.userData.orientation, 'FLAT_XZ');
  assert.equal(geometry.groups.length, 6);
  assert.equal(geometry.attributes.uv.needsUpdate, true);
  assert.ok(geometry.groups.every(group => group.start >= 0 && group.count === 6));
});

test('VISORI-009 display modes are explicit and physical is available', () => {
  assert.deepEqual(orientation.DisplayMode, { PHYSICAL: 'PHYSICAL', ASSIST: 'ASSIST' });
});

test('VISORI-010 unknown legacy orientation falls back compatibly', () => {
  assert.equal(orientation.normalizeOrientation(undefined), 'UPRIGHT_NORMAL');
  assert.equal(orientation.normalizeOrientation('legacy'), 'UPRIGHT_NORMAL');
});
