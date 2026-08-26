const test = require('node:test');
const assert = require('node:assert/strict');
const reporter = require('../src/errorLogReporter.js');

test('error reporter normalizes BackendError metadata', () => {
  const error = Object.assign(new Error('HTTP 500'), { type: 'SERVER_ERROR', status: 500 });
  const entry = reporter.normalizeError(error, { source: 'BACKEND_API', operation: 'CALCULATE' }, 0);
  assert.equal(entry.type, 'SERVER_ERROR');
  assert.equal(entry.status, 500);
  assert.equal(entry.message, 'HTTP 500');
  assert.equal(entry.source, 'BACKEND_API');
  assert.match(entry.stack, /HTTP 500/);
});

test('error reporter deduplicates repeated errors and keeps richer context', () => {
  let time = 1000;
  const store = reporter.createStore({ now: () => time });
  store.add(new Error('solver failed'), { source: 'CONSOLE', type: 'SERVER_ERROR' });
  time += 100;
  store.add(new Error('solver failed'), { source: 'BACKEND_API', operation: 'CALCULATE', type: 'SERVER_ERROR' });
  const entries = store.entries();
  assert.equal(entries.length, 1);
  assert.equal(entries[0].count, 1);
  assert.equal(entries[0].source, 'BACKEND_API');
  assert.equal(entries[0].operation, 'CALCULATE');
});

test('handled renderer error upgrades its console entry instead of duplicating it', () => {
  let time = 1000;
  const store = reporter.createStore({ now: () => time });
  store.add(new Error('mesh failed'), { source: 'CONSOLE', type: 'CONSOLE_ERROR' });
  time += 20;
  store.add(new Error('mesh failed'), { source: 'THREE_RENDERER', operation: 'APPLY_LOADING_RESULT', type: 'RENDER_ERROR' });
  assert.equal(store.entries().length, 1);
  assert.equal(store.entries()[0].type, 'RENDER_ERROR');
  assert.equal(store.entries()[0].count, 1);
});

test('error reporter caps entries and clears them', () => {
  let time = 0;
  const store = reporter.createStore({ maxEntries: 2, now: () => (time += 3000) });
  store.add('one'); store.add('two'); store.add('three');
  assert.deepEqual(store.entries().map(item => item.message), ['three', 'two']);
  store.clear();
  assert.equal(store.entries().length, 0);
});

test('formatted report contains useful diagnostics without request payloads', () => {
  const store = reporter.createStore({ now: () => 0 });
  store.add(Object.assign(new Error('bad response'), { type: 'SCHEMA_ERROR' }), { source: 'ADAPTER' });
  const report = reporter.formatReport(store.entries(), { url: 'http://localhost:8080/' });
  assert.match(report, /SCHEMA_ERROR/);
  assert.match(report, /bad response/);
  assert.match(report, /localhost:8080/);
});
