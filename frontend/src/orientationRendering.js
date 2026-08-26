(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.BLK007F78 = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const DisplayMode = Object.freeze({ PHYSICAL: 'PHYSICAL', ASSIST: 'ASSIST' });
  const ORIENTATIONS = Object.freeze([
    'UPRIGHT_NORMAL', 'UPRIGHT_ROTATED', 'FLAT_XZ', 'FLAT_ZX', 'SIDE_YZ', 'SIDE_ZY'
  ]);
  const FACE_ORDER = Object.freeze(['PX', 'NX', 'PY', 'NY', 'PZ', 'NZ']);

  // Product axes expressed in solver-canonical XYZ. Signs make every mapping
  // right-handed; occupied dimensions already contain the corresponding AABB.
  const PRODUCT_AXES = Object.freeze({
    UPRIGHT_NORMAL:  { L: [ 1, 0, 0], W: [0,  1, 0], H: [0, 0, 1] },
    UPRIGHT_ROTATED: { L: [ 0,-1, 0], W: [1,  0, 0], H: [0, 0, 1] },
    FLAT_XZ:         { L: [ 1, 0, 0], W: [0,  0,-1], H: [0, 1, 0] },
    FLAT_ZX:         { L: [ 0, 1, 0], W: [0,  0, 1], H: [1, 0, 0] },
    SIDE_YZ:         { L: [ 0, 0, 1], W: [1,  0, 0], H: [0, 1, 0] },
    SIDE_ZY:         { L: [ 0, 0,-1], W: [0,  1, 0], H: [1, 0, 0] }
  });

  // THREE scene uses canonical X/Z/Y as its X/Y/Z axes.
  function canonicalToThree(v) { return [v[0], v[2], v[1]]; }
  function negate(v) { return [-v[0], -v[1], -v[2]]; }
  function equal(a, b) { return a[0] === b[0] && a[1] === b[1] && a[2] === b[2]; }
  function normalizeOrientation(value) {
    const name = String(value || 'UPRIGHT_NORMAL').toUpperCase();
    return PRODUCT_AXES[name] ? name : 'UPRIGHT_NORMAL';
  }
  function faceForVector(v) {
    const faces = { PX: [1,0,0], NX: [-1,0,0], PY: [0,1,0], NY: [0,-1,0], PZ: [0,0,1], NZ: [0,0,-1] };
    return FACE_ORDER.find(face => equal(v, faces[face]));
  }

  // BoxGeometry's physical directions for increasing texture U (right) and V
  // (up) on each face. UV quarter-turns rotate the sampled texture, not mesh.
  const UV_BASIS = Object.freeze({
    PX: { right: [0,0,-1], up: [0,1,0] }, NX: { right: [0,0,1],  up: [0,1,0] },
    PY: { right: [1,0,0],  up: [0,0,-1] }, NY: { right: [1,0,0], up: [0,0,1] },
    PZ: { right: [1,0,0],  up: [0,1,0] }, NZ: { right: [-1,0,0], up: [0,1,0] }
  });
  function quarterTurns(face, desiredUp) {
    const basis = UV_BASIS[face];
    if (equal(desiredUp, basis.up)) return 0;
    if (equal(desiredUp, basis.right)) return 1;
    if (equal(desiredUp, negate(basis.up))) return 2;
    if (equal(desiredUp, negate(basis.right))) return 3;
    throw new Error(`Desired texture-up vector is not tangent to ${face}`);
  }

  function getFaceMapping(orientationValue) {
    const orientation = normalizeOrientation(orientationValue);
    const axes = PRODUCT_AXES[orientation];
    const three = { L: canonicalToThree(axes.L), W: canonicalToThree(axes.W), H: canonicalToThree(axes.H) };
    // Semantic material slots retain the existing registry contract:
    // +L, -L, +H(top), -H(bottom), +W(label), -W(label).
    const productFaces = [
      ['POSITIVE_LENGTH', three.L, 0, three.H], ['NEGATIVE_LENGTH', negate(three.L), 1, three.H],
      ['POSITIVE_HEIGHT', three.H, 2, three.W], ['NEGATIVE_HEIGHT', negate(three.H), 3, three.W],
      ['POSITIVE_WIDTH', three.W, 4, three.H], ['NEGATIVE_WIDTH', negate(three.W), 5, three.H]
    ];
    const mapped = {};
    productFaces.forEach(([productFace, normal, materialIndex, desiredUp]) => {
      const worldFace = faceForVector(normal);
      mapped[worldFace] = {
        worldFace, productFace, materialIndex,
        uvQuarterTurns: quarterTurns(worldFace, desiredUp)
      };
    });
    return {
      orientation,
      faces: FACE_ORDER.map(face => mapped[face]),
      productUpThree: three.H.slice()
    };
  }

  function rotateUv(u, v, turns) {
    switch ((turns % 4 + 4) % 4) {
      case 1: return [1 - v, u];
      case 2: return [1 - u, 1 - v];
      case 3: return [v, 1 - u];
      default: return [u, v];
    }
  }

  function createOrientationGeometry(THREE, orientation) {
    if (!THREE || !THREE.BoxGeometry) throw new Error('THREE.BoxGeometry is required');
    const geometry = new THREE.BoxGeometry(1, 1, 1);
    const mapping = getFaceMapping(orientation);
    const uv = geometry.attributes.uv;
    geometry.groups.forEach((group, groupIndex) => {
      const face = mapping.faces[groupIndex];
      group.materialIndex = face.materialIndex;
      if (!face.uvQuarterTurns || !uv) return;
      const vertexIds = new Set();
      for (let offset = 0; offset < group.count; offset++) {
        const pointer = group.start + offset;
        vertexIds.add(geometry.index ? geometry.index.getX(pointer) : pointer);
      }
      vertexIds.forEach(vertex => {
        const rotated = rotateUv(uv.getX(vertex), uv.getY(vertex), face.uvQuarterTurns);
        uv.setXY(vertex, rotated[0], rotated[1]);
      });
    });
    if (uv) uv.needsUpdate = true;
    geometry.userData.orientation = mapping.orientation;
    geometry.userData.faceMapping = mapping.faces;
    return geometry;
  }

  class PackageTextureRegistry extends Map {
    constructor() { super(); this.hits = 0; this.misses = 0; }
    get(key) {
      if (super.has(key)) this.hits += 1;
      return super.get(key);
    }
    set(key, value) {
      if (!super.has(key)) this.misses += 1;
      return super.set(key, value);
    }
    diagnostics() { return { entries: this.size, hits: this.hits, misses: this.misses }; }
  }

  class OrientationGeometryCache {
    constructor(THREE) { this.THREE = THREE; this.cache = new Map(); this.hits = 0; this.misses = 0; }
    get(value) {
      const orientation = normalizeOrientation(value);
      if (this.cache.has(orientation)) { this.hits += 1; return this.cache.get(orientation); }
      this.misses += 1;
      const geometry = createOrientationGeometry(this.THREE, orientation);
      this.cache.set(orientation, geometry);
      return geometry;
    }
    diagnostics() { return { entries: this.cache.size, hits: this.hits, misses: this.misses }; }
  }

  class OrientationMaterialCache {
    constructor() { this.cache = new Map(); this.hits = 0; this.misses = 0; }
    get(sku, orientationValue, baseMaterials) {
      const key = `${sku}::${normalizeOrientation(orientationValue)}`;
      if (this.cache.has(key)) { this.hits += 1; return this.cache.get(key); }
      this.misses += 1;
      // A distinct immutable array prevents array-level mutation while every
      // entry still references the SKU's shared material/texture objects.
      const materials = Object.freeze(baseMaterials.slice());
      this.cache.set(key, materials);
      return materials;
    }
    clear() { this.cache.clear(); this.hits = 0; this.misses = 0; }
    diagnostics() { return { entries: this.cache.size, hits: this.hits, misses: this.misses }; }
  }

  return {
    DisplayMode, ORIENTATIONS, FACE_ORDER, normalizeOrientation, getFaceMapping,
    rotateUv, createOrientationGeometry, PackageTextureRegistry,
    OrientationGeometryCache, OrientationMaterialCache
  };
});
