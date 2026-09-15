/**
 * Run 18: supervisor-status honesty regression tests.
 *
 * Guards against two fabricated-data defects in the `/ai-control/status` and
 * `/system/overview` responses:
 *
 *   1. "Uptime" was not uptime — the old code returned the string 'live'/'unknown'
 *      (or null) instead of real seconds, so the UI printed "live" or blank.
 *   2. Fabricated zeros — token_budget/token_used/max_concurrency were hard-coded
 *      to 0 even though no runtime source exists. 0 is invented data and must be
 *      reported as null instead.
 *
 * The helper also maps the model registry to per-model usage rows, tagging
 * whether each model is free (is_free === true) so the web cost column never
 * mislabels an unused paid model as "Gratis".
 *
 * Matches the existing test style: `node --test` over compiled `dist/` output
 * (no extra build step beyond the `npm run build` that `npm test` already runs).
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const { buildSupervisorStatus } = require('../dist/supervisorStatus.js');

test('uptime comes from health.uptime_seconds when it is a finite number', () => {
  const out = buildSupervisorStatus({
    health: { uptime_seconds: 42.5, trading_engine: 'deterministic' },
    scheduler: { running: true, stats: { max_concurrency: 4 } },
    models: [],
  });
  assert.equal(out.uptime, 42.5);
});

test('uptime is null when health.uptime_seconds is missing or non-finite', () => {
  assert.equal(
    buildSupervisorStatus({ health: { trading_engine: 'deterministic' } }).uptime,
    null,
  );
  assert.equal(buildSupervisorStatus({ health: {} }).uptime, null);
  assert.equal(buildSupervisorStatus({}).uptime, null);
  assert.equal(buildSupervisorStatus({ health: { uptime_seconds: 'live' } }).uptime, null);
  assert.equal(buildSupervisorStatus({ health: { uptime_seconds: NaN } }).uptime, null);
  assert.equal(buildSupervisorStatus({ health: { uptime_seconds: Infinity } }).uptime, null);
});

test('max_concurrency is null when the scheduler source is absent', () => {
  assert.equal(buildSupervisorStatus({ scheduler: {} }).max_concurrency, null);
  assert.equal(buildSupervisorStatus({ scheduler: { stats: {} } }).max_concurrency, null);
  assert.equal(buildSupervisorStatus({}).max_concurrency, null);
  assert.equal(
    buildSupervisorStatus({ scheduler: { stats: { max_concurrency: 'x' } } }).max_concurrency,
    null,
  );
  assert.equal(
    buildSupervisorStatus({ scheduler: { stats: { max_concurrency: 3 } } }).max_concurrency,
    3,
  );
});

test('token_budget and token_used are always null (no runtime source, never invent 0)', () => {
  const out = buildSupervisorStatus({
    health: { uptime_seconds: 1 },
    scheduler: { running: true, stats: { max_concurrency: 2 } },
    models: [{ id: 'gpt-4o', provider: 'openai', is_free: false }],
  });
  assert.equal(out.token_budget, null);
  assert.equal(out.token_used, null);
});

test('status and routing_policy derive from scheduler.running and health.trading_engine', () => {
  const active = buildSupervisorStatus({
    health: { trading_engine: 'deterministic' },
    scheduler: { running: true },
  });
  assert.equal(active.status, 'active');
  assert.equal(active.routing_policy, 'priority_based');

  const idle = buildSupervisorStatus({ health: {}, scheduler: { running: false } });
  assert.equal(idle.status, 'idle');
  assert.equal(idle.routing_policy, 'unknown');

  const none = buildSupervisorStatus({});
  assert.equal(none.status, 'idle');
  assert.equal(none.routing_policy, 'unknown');
});

test('models map to usage rows with zeros and isFree only when is_free === true', () => {
  const out = buildSupervisorStatus({
    models: [
      { id: 'gpt-4o', provider: 'openai', is_free: false },
      { name: 'llama-local', provider: 'ollama', is_free: true },
      { id: 'mystery', provider: 'unknown' },
      { id: 'falsy', provider: 'x', is_free: false },
    ],
  });
  assert.equal(out.models.length, 4);

  const [paid, free, missing, falsy] = out.models;
  assert.deepEqual(paid, {
    model: 'gpt-4o',
    provider: 'openai',
    calls: 0,
    promptTokens: 0,
    completionTokens: 0,
    cost: 0,
    isFree: false,
  });
  // name fallback when id absent.
  assert.equal(free.model, 'llama-local');
  assert.equal(free.isFree, true);
  // is_free missing → treated as paid (never silently "Gratis").
  assert.equal(missing.isFree, false);
  // is_free false → paid.
  assert.equal(falsy.isFree, false);
});

test('models defaults to an empty array when the source is absent', () => {
  assert.deepEqual(buildSupervisorStatus({}).models, []);
  assert.deepEqual(buildSupervisorStatus({ models: null }).models, []);
});
