(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ErrorLogReporter = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const DEFAULT_MAX_ENTRIES = 50;
  const DEDUPE_WINDOW_MS = 2000;

  function stringifyPart(value) {
    if (value instanceof Error) return value.message || value.name;
    if (typeof value === 'string') return value;
    try { return JSON.stringify(value); }
    catch (_) { return String(value); }
  }

  function normalizeError(error, context, now) {
    const details = context || {};
    const candidate = error instanceof Error
      ? error
      : (Array.isArray(error) ? error.find(part => part instanceof Error) : null);
    const message = candidate
      ? (candidate.message || candidate.name)
      : (Array.isArray(error) ? error.map(stringifyPart).join(' ') : stringifyPart(error));
    const type = details.type || (candidate && candidate.type) || 'RUNTIME_ERROR';
    const status = details.status != null ? details.status : (candidate && candidate.status);
    return {
      id: '',
      timestamp: new Date(now == null ? Date.now() : now).toISOString(),
      source: details.source || 'APPLICATION',
      operation: details.operation || '',
      type: String(type),
      status: status == null ? null : Number(status),
      message: message || 'Unknown error',
      stack: candidate && candidate.stack ? String(candidate.stack) : '',
      count: 1,
    };
  }

  function createStore(options) {
    const config = options || {};
    const maxEntries = Math.max(1, Number(config.maxEntries) || DEFAULT_MAX_ENTRIES);
    const now = typeof config.now === 'function' ? config.now : Date.now;
    let entries = [];
    let serial = 0;
    const subscribers = new Set();

    function snapshot() { return entries.map(entry => Object.assign({}, entry)); }
    function notify() {
      const value = snapshot();
      subscribers.forEach(fn => fn(value));
    }
    function add(error, context) {
      const instant = now();
      const entry = normalizeError(error, context, instant);
      const previous = entries[0];
      const previousTime = previous ? Date.parse(previous.timestamp) : 0;
      if (previous && previous.message === entry.message && instant - previousTime <= DEDUPE_WINDOW_MS) {
        const isContextUpgrade = previous.source === 'CONSOLE' && entry.source !== 'CONSOLE';
        const richerSource = isContextUpgrade ? entry.source : previous.source;
        const richerType = ['CONSOLE_ERROR', 'RUNTIME_ERROR'].includes(previous.type) && !['CONSOLE_ERROR', 'RUNTIME_ERROR'].includes(entry.type)
          ? entry.type : previous.type;
        entries[0] = Object.assign({}, previous, entry, {
          id: previous.id,
          source: richerSource,
          type: richerType,
          operation: entry.operation || previous.operation,
          stack: entry.stack || previous.stack,
          count: previous.count + (isContextUpgrade ? 0 : 1),
        });
      } else {
        entry.id = `ERR-${String(++serial).padStart(4, '0')}`;
        entries.unshift(entry);
        if (entries.length > maxEntries) entries = entries.slice(0, maxEntries);
      }
      notify();
      return entries[0];
    }
    function clear() { entries = []; notify(); }
    function subscribe(fn) {
      subscribers.add(fn);
      fn(snapshot());
      return function unsubscribe() { subscribers.delete(fn); };
    }
    return { add, clear, entries: snapshot, subscribe };
  }

  function formatReport(entries, metadata) {
    const info = metadata || {};
    const lines = [
      '3D-AICIVS 前端错误日志',
      `生成时间: ${new Date().toISOString()}`,
      `页面: ${info.url || ''}`,
      `User-Agent: ${info.userAgent || ''}`,
      `错误数: ${(entries || []).length}`,
      '',
    ];
    (entries || []).forEach(entry => {
      lines.push(`[${entry.timestamp}] ${entry.id} ${entry.type}${entry.status == null ? '' : ` HTTP ${entry.status}`}`);
      lines.push(`来源: ${entry.source}${entry.operation ? ` / ${entry.operation}` : ''}`);
      lines.push(`信息: ${entry.message}${entry.count > 1 ? ` (重复 ${entry.count} 次)` : ''}`);
      if (entry.stack) lines.push(entry.stack);
      lines.push('');
    });
    return lines.join('\n');
  }

  function installGlobalCapture(target, store, options) {
    const config = options || {};
    const cleanups = [];
    if (target && typeof target.addEventListener === 'function') {
      const onError = event => store.add(event.error || event.message, {
        source: 'WINDOW', operation: 'UNCAUGHT_ERROR', type: 'UNCAUGHT_ERROR'
      });
      const onRejection = event => store.add(event.reason, {
        source: 'PROMISE', operation: 'UNHANDLED_REJECTION', type: 'UNHANDLED_REJECTION'
      });
      target.addEventListener('error', onError);
      target.addEventListener('unhandledrejection', onRejection);
      cleanups.push(() => target.removeEventListener('error', onError));
      cleanups.push(() => target.removeEventListener('unhandledrejection', onRejection));
    }
    if (config.captureConsole !== false && target && target.console && typeof target.console.error === 'function') {
      const original = target.console.error.bind(target.console);
      target.console.error = function capturedConsoleError() {
        const parts = Array.from(arguments);
        store.add(parts, { source: 'CONSOLE', operation: 'console.error', type: (parts.find(x => x && x.type) || {}).type || 'CONSOLE_ERROR' });
        return original.apply(null, parts);
      };
      cleanups.push(() => { target.console.error = original; });
    }
    return function uninstall() { cleanups.reverse().forEach(cleanup => cleanup()); };
  }

  return { normalizeError, createStore, formatReport, installGlobalCapture };
});
