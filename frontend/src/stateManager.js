// State Manager - Global state and localStorage persistence

const CACHE_PREFIX = '3D_AICIVS_PACKING_CACHE_V42_FLUSH_BULKHEAD_';
const APP_STATE_KEY = '3D_AICIVS_APP_STATE_V42_FLUSH_BULKHEAD';

const CONTAINER_SPECS = {
  '20GP': { extL:5.898, extW:2.352, extH:2.393, intL:5.895, intW:2.330, intH:2.350, intVol:32.2, cameraDist:19, code:'20GP' },
  '40GP': { extL:12.032,extW:2.352, extH:2.393, intL:12.029,intW:2.330, intH:2.350, intVol:65.9, cameraDist:32, code:'40GP' },
  '40HQ': { extL:12.032,extW:2.352, extH:2.698, intL:12.029,intW:2.330, intH:2.655, intVol:74.4, cameraDist:33, code:'40HQ' },
  '45HQ': { extL:13.556,extW:2.352, extH:2.698, intL:13.553,intW:2.330, intH:2.655, intVol:83.9, cameraDist:36, code:'45HQ' },
  '53HQ': { extL:16.154,extW:2.591, extH:2.896, intL:16.151,intW:2.569, intH:2.850, intVol:118.3,cameraDist:42, code:'53HQ' }
};

let activeContainerCode = '40HQ';
let currentSpec = CONTAINER_SPECS[activeContainerCode];
let activeManifest = [];
let activePackingResult = null;
let selectedSKUs = new Set();
let hoveredSKU = null;
let isDoorOpen = false;

const DEFAULT_ALGORITHM_WEIGHTS = {
  weightFragmentation: 10,
  weightHeightWaste: 80,
  weightUnusedLayers: 75,
  weightUnusedWidth: 90,
  weightIllegalPriority: 200,
  weightTippingPenalty: 150,
  weightFallPenalty: 50
};
let activeAlgorithmWeights = { ...DEFAULT_ALGORITHM_WEIGHTS };

function loadAppState() {
  try {
    const raw = localStorage.getItem(APP_STATE_KEY);
    if (!raw) return;
    const state = JSON.parse(raw);
    if (state.containerCode && CONTAINER_SPECS[state.containerCode]) {
      activeContainerCode = state.containerCode;
      currentSpec = CONTAINER_SPECS[activeContainerCode];
    }
    if (state.manifest && Array.isArray(state.manifest)) {
      activeManifest = state.manifest;
    }
    if (state.algorithmWeights && typeof state.algorithmWeights === 'object') {
      activeAlgorithmWeights = { ...DEFAULT_ALGORITHM_WEIGHTS, ...state.algorithmWeights };
    }
  } catch (err) {
    console.warn('[stateManager] loadAppState error:', err);
  }
}

function saveAppState() {
  try {
    const state = {
      containerCode: activeContainerCode,
      manifest: activeManifest,
      algorithmWeights: activeAlgorithmWeights
    };
    localStorage.setItem(APP_STATE_KEY, JSON.stringify(state));
  } catch (err) {
    console.warn('[stateManager] saveAppState error:', err);
  }
}

function getCacheKey(containerCode, manifest) {
  const skuSig = manifest.map(m =>
    `${m.sku}_${m.w}_${m.d}_${m.h}_${m.weight}_${m.quantity}_${m.requirement || 'MID'}`
  ).join('|');
  const hash = Array.from(skuSig).reduce((acc, c) => ((acc << 5) - acc + c.charCodeAt(0)) | 0, 0);
  return `${CACHE_PREFIX}${containerCode}_${hash}`;
}

function getCachedResult(containerCode, manifest) {
  try {
    const key = getCacheKey(containerCode, manifest);
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const cached = JSON.parse(raw);
    const age = Date.now() - (cached.timestamp || 0);
    if (age > 3600 * 24 * 7 * 1000) {
      localStorage.removeItem(key);
      return null;
    }
    return cached.result;
  } catch (err) {
    console.warn('[stateManager] getCachedResult error:', err);
    return null;
  }
}

function setCachedResult(containerCode, manifest, result) {
  try {
    const key = getCacheKey(containerCode, manifest);
    const payload = { result, timestamp: Date.now() };
    localStorage.setItem(key, JSON.stringify(payload));
  } catch (err) {
    console.warn('[stateManager] setCachedResult error:', err);
  }
}

function markManifestDirty(reason) {
  console.log('[stateManager] manifest marked dirty:', reason);
}

window.stateManager = {
  CONTAINER_SPECS,
  get activeContainerCode() { return activeContainerCode; },
  set activeContainerCode(code) {
    if (CONTAINER_SPECS[code]) {
      activeContainerCode = code;
      currentSpec = CONTAINER_SPECS[code];
    }
  },
  get currentSpec() { return currentSpec; },
  get activeManifest() { return activeManifest; },
  set activeManifest(m) { activeManifest = m; },
  get activePackingResult() { return activePackingResult; },
  set activePackingResult(r) { activePackingResult = r; },
  get selectedSKUs() { return selectedSKUs; },
  get hoveredSKU() { return hoveredSKU; },
  set hoveredSKU(s) { hoveredSKU = s; },
  get isDoorOpen() { return isDoorOpen; },
  set isDoorOpen(d) { isDoorOpen = d; },
  get activeAlgorithmWeights() { return activeAlgorithmWeights; },
  set activeAlgorithmWeights(w) { activeAlgorithmWeights = w; },
  DEFAULT_ALGORITHM_WEIGHTS,
  loadAppState,
  saveAppState,
  getCachedResult,
  setCachedResult,
  markManifestDirty
};
