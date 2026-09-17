/**
 * apiClient.js
 * 3D-AICIVS API Client Module
 * 
 * Responsibilities:
 * - Direct REST API integration (/api/solve, /api/validate, /api/status, /loading/jobs)
 * - Error parsing and response normalization
 * - Polling helper for async solvers
 * - Expose window.apiClient
 */

(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.apiClient = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  function getApiBase() {
    if (root.BLK007D && typeof root.BLK007D.configuredBase === 'function') {
      try {
        return root.BLK007D.configuredBase();
      } catch (_) {}
    }
    const meta = root.document && root.document.querySelector('meta[name="loading-api-base"]');
    if (meta && meta.content) return meta.content.replace(/\/$/, '');
    return '';
  }

  function parseAPIError(error) {
    if (error && error.type && error.message) {
      return {
        type: error.type,
        message: error.message,
        status: error.status || null,
        details: error.details || null
      };
    }
    return {
      type: 'UNKNOWN_ERROR',
      message: error ? (error.message || String(error)) : 'Unknown error',
      status: null,
      details: null
    };
  }

  /**
   * Directly call solve endpoint
   */
  async function callSolveAPI(cargoList, containerType, constraints, options = {}) {
    if (root.BLK007D && typeof root.BLK007D.calculate === 'function') {
      const spec = root.stateManager ? root.stateManager.CONTAINER_SPECS[containerType] : null;
      const usable = spec ? (spec.usable || { L: spec.intL, W: spec.intW, H: spec.intH }) : { L: 12.032, W: 2.352, H: 2.698 };
      const maxPayloadKg = spec ? (spec.maxPayloadTons || 26.5) * 1000 : 26500;
      
      const payload = {
        solverVersion: 'v2',
        mode: constraints && constraints.strategy === 'mec' ? 'MAX_COMPACT' : 'BALANCED',
        timeBudgetSec: 20,
        randomSeed: 42,
        container: {
          code: containerType,
          usable: usable,
          maxPayloadKg: maxPayloadKg,
          doorZoneLengthM: 1.2,
          rearZoneLengthM: 1.0
        },
        sku: cargoList
      };
      return await root.BLK007D.calculate(payload, options);
    }

    const base = getApiBase();
    const response = await fetch(`${base}/api/solve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cargo_list: cargoList,
        container_type: containerType,
        constraints: constraints
      }),
      signal: options.signal
    });

    if (!response.ok) {
      const errJson = await response.json().catch(() => ({}));
      throw new Error(errJson.detail || errJson.message || `HTTP ${response.status}`);
    }
    return await response.json();
  }

  /**
   * Directly call validate endpoint
   */
  async function callValidateAPI(solution, options = {}) {
    const base = getApiBase();
    const response = await fetch(`${base}/api/validate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ solution }),
      signal: options.signal
    });
    if (!response.ok) {
      const errJson = await response.json().catch(() => ({}));
      throw new Error(errJson.detail || errJson.message || `HTTP ${response.status}`);
    }
    return await response.json();
  }

  /**
   * Poll status endpoint for task completion
   */
  async function pollStatus(taskId, onProgress, onComplete, onError, intervalMs = 1000) {
    const base = getApiBase();
    const interval = setInterval(async () => {
      try {
        const response = await fetch(`${base}/api/status/${encodeURIComponent(taskId)}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();

        if (data.state === 'SUCCESS' || data.status === 'SUCCESS') {
          clearInterval(interval);
          if (typeof onComplete === 'function') onComplete(data.result || data);
        } else if (data.state === 'FAILURE' || data.status === 'FAILURE') {
          clearInterval(interval);
          if (typeof onError === 'function') onError(data.error || new Error('Task execution failed'));
        } else {
          if (typeof onProgress === 'function') onProgress(data);
        }
      } catch (err) {
        clearInterval(interval);
        if (typeof onError === 'function') onError(err);
      }
    }, intervalMs);

    return interval;
  }

  return {
    callSolveAPI,
    callValidateAPI,
    pollStatus,
    parseAPIError,
    getApiBase
  };
});
