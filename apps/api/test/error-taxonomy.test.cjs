/**
 * TASK 04 — AI Control error taxonomy tests.
 *
 * Guards invariants 18/19 (MASTER_PLAN §0): a 503 must NEVER be surfaced as a
 * generic "agent error" without the real failing layer. Exercises the compiled
 * `dist/errorTaxonomy.js` so no extra build step is needed beyond the
 * `npm run build` that `npm test` already runs.
 *
 * Required taxonomy codes (all 13 must exist and be retry-classified):
 *   NODE_API_UNAVAILABLE, PYTHON_SERVICE_UNAVAILABLE, PYTHON_ENDPOINT_4XX,
 *   PYTHON_ENDPOINT_5XX, AGENT_TIMEOUT, AGENT_EXCEPTION, LLM_PROVIDER_4XX,
 *   LLM_PROVIDER_5XX, LLM_PROVIDER_503, LLM_TIMEOUT, MODEL_UNAVAILABLE,
 *   AUTH_FAILURE, DATA_GUARD_FAILURE.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  ERROR_CODES,
  ERROR_LAYER,
  classify,
  classifyProxyFailure,
  classifyHttpStatus,
  normalizeIncoming,
  isRetryable,
  shouldRetry,
} = require('../dist/errorTaxonomy.js');

const CANONICAL_FIELDS = [
  'code',
  'layer',
  'trace_id',
  'service',
  'endpoint',
  'status_code',
  'agent',
  'event_id',
  'model',
  'provider',
  'timestamp',
  'message',
  'retryable',
];

test('exposes exactly the 13 required taxonomy codes', () => {
  assert.equal(ERROR_CODES.length, 13);
  for (const code of [
    'NODE_API_UNAVAILABLE',
    'PYTHON_SERVICE_UNAVAILABLE',
    'PYTHON_ENDPOINT_4XX',
    'PYTHON_ENDPOINT_5XX',
    'AGENT_TIMEOUT',
    'AGENT_EXCEPTION',
    'LLM_PROVIDER_4XX',
    'LLM_PROVIDER_5XX',
    'LLM_PROVIDER_503',
    'LLM_TIMEOUT',
    'MODEL_UNAVAILABLE',
    'AUTH_FAILURE',
    'DATA_GUARD_FAILURE',
  ]) {
    assert.ok(ERROR_CODES.includes(code), `missing code ${code}`);
  }
});

test('every code carries all canonical fields (null when unknown)', () => {
  for (const code of ERROR_CODES) {
    const err = classify({ code });
    for (const field of CANONICAL_FIELDS) {
      assert.ok(field in err, `${code} missing field ${field}`);
    }
    assert.equal(err.code, code);
    assert.equal(typeof err.timestamp, 'string');
    assert.equal(typeof err.retryable, 'boolean');
    assert.equal(typeof err.layer, 'string');
  }
});

test('unknown optional fields default to null, never fabricated values', () => {
  const err = classify({ code: 'AGENT_EXCEPTION', message: 'boom' });
  assert.equal(err.trace_id, null);
  assert.equal(err.service, null);
  assert.equal(err.endpoint, null);
  assert.equal(err.status_code, null);
  assert.equal(err.agent, null);
  assert.equal(err.event_id, null);
  assert.equal(err.model, null);
  assert.equal(err.provider, null);
});

test('layer attribution is correct per code (503 must be llm_provider, not agent)', () => {
  assert.equal(ERROR_LAYER.LLM_PROVIDER_503, 'llm_provider');
  assert.equal(ERROR_LAYER.PYTHON_SERVICE_UNAVAILABLE, 'python_service');
  assert.equal(ERROR_LAYER.PYTHON_ENDPOINT_5XX, 'python_endpoint');
  assert.equal(ERROR_LAYER.AGENT_EXCEPTION, 'agent');
  assert.equal(ERROR_LAYER.AUTH_FAILURE, 'auth');
  assert.equal(ERROR_LAYER.DATA_GUARD_FAILURE, 'data_guard');
});

// ── Retry policy ────────────────────────────────────────────────────────────

test('retry policy: infra/5xx/timeout retryable; deterministic errors not', () => {
  // Retryable — transient / infra.
  for (const code of [
    'PYTHON_SERVICE_UNAVAILABLE',
    'PYTHON_ENDPOINT_5XX',
    'AGENT_TIMEOUT',
    'AGENT_EXCEPTION',
    'LLM_PROVIDER_5XX',
    'LLM_PROVIDER_503',
    'LLM_TIMEOUT',
    'NODE_API_UNAVAILABLE',
  ]) {
    assert.equal(isRetryable(code), true, `${code} should be retryable`);
  }
  // NOT retryable — invalid schema/4xx, auth failure, missing data, model gap.
  for (const code of [
    'PYTHON_ENDPOINT_4XX',
    'LLM_PROVIDER_4XX',
    'MODEL_UNAVAILABLE',
    'AUTH_FAILURE',
    'DATA_GUARD_FAILURE',
  ]) {
    assert.equal(isRetryable(code), false, `${code} must NOT be retryable`);
  }
});

test('classify derives retryable from the code, ignoring caller input', () => {
  const err = classify({ code: 'AUTH_FAILURE', retryable: true });
  assert.equal(err.retryable, false);
});

test('shouldRetry only allows retryable errors', () => {
  assert.equal(shouldRetry(classify({ code: 'LLM_PROVIDER_503' })), true);
  assert.equal(shouldRetry(classify({ code: 'AUTH_FAILURE' })), false);
  assert.equal(shouldRetry(null), false);
  assert.equal(shouldRetry(undefined), false);
});

// ── Proxy failure classification (Node boundary) ─────────────────────────────

test('unreachable Python → PYTHON_SERVICE_UNAVAILABLE (503, retryable)', () => {
  const err = classifyProxyFailure(
    { error: 'python_service_unavailable', status: 503, detail: 'ECONNREFUSED' },
    { endpoint: '/health', trace_id: 'tr-1' },
  );
  assert.equal(err.code, 'PYTHON_SERVICE_UNAVAILABLE');
  assert.equal(err.layer, 'python_service');
  assert.equal(err.status_code, 503);
  assert.equal(err.retryable, true);
  assert.equal(err.trace_id, 'tr-1');
});

test('proxy timeout → PYTHON_SERVICE_UNAVAILABLE with status 504', () => {
  const err = classifyProxyFailure({ error: 'python_service_timeout', status: 504 });
  assert.equal(err.code, 'PYTHON_SERVICE_UNAVAILABLE');
  assert.equal(err.status_code, 504);
});

test('upstream 4xx → PYTHON_ENDPOINT_4XX (not retryable)', () => {
  const err = classifyProxyFailure({
    error: 'python_service_error',
    status: 502,
    upstreamStatus: 422,
  });
  assert.equal(err.code, 'PYTHON_ENDPOINT_4XX');
  assert.equal(err.status_code, 422);
  assert.equal(err.retryable, false);
});

test('upstream 503 → PYTHON_ENDPOINT_5XX (NOT a generic agent error)', () => {
  const err = classifyProxyFailure({
    error: 'python_service_error',
    status: 502,
    upstreamStatus: 503,
  });
  assert.equal(err.code, 'PYTHON_ENDPOINT_5XX');
  assert.equal(err.status_code, 503);
  assert.equal(err.retryable, true);
});

test('upstream 401/403 → AUTH_FAILURE (not retryable)', () => {
  for (const status of [401, 403]) {
    const err = classifyProxyFailure({ error: 'python_service_error', status: 502, upstreamStatus: status });
    assert.equal(err.code, 'AUTH_FAILURE');
    assert.equal(err.retryable, false);
  }
});

test('malformed JSON → PYTHON_ENDPOINT_5XX', () => {
  const err = classifyProxyFailure({ error: 'python_service_invalid_json', status: 502 });
  assert.equal(err.code, 'PYTHON_ENDPOINT_5XX');
});

// ── HTTP status classification (subsystem probes) ────────────────────────────

test('classifyHttpStatus returns null for 2xx (healthy probe)', () => {
  assert.equal(classifyHttpStatus(200), null);
  assert.equal(classifyHttpStatus(204), null);
});

test('classifyHttpStatus maps 4xx/5xx/auth correctly', () => {
  assert.equal(classifyHttpStatus(404).code, 'PYTHON_ENDPOINT_4XX');
  assert.equal(classifyHttpStatus(500).code, 'PYTHON_ENDPOINT_5XX');
  assert.equal(classifyHttpStatus(503).code, 'PYTHON_ENDPOINT_5XX');
  assert.equal(classifyHttpStatus(401).code, 'AUTH_FAILURE');
});

// ── Python-emitted error normalisation ───────────────────────────────────────

test('normalizeIncoming accepts a Python-classified error verbatim', () => {
  const incoming = classify({
    code: 'LLM_PROVIDER_503',
    message: 'upstream 503',
    service: 'llm_provider',
    provider: '9router',
    model: 'codebuddy-deepseekv4.1flashfree',
    status_code: 503,
    agent: 'technical_analyst',
    event_id: 'BREAKOUT-1',
    trace_id: 'tr-x',
  });
  const norm = normalizeIncoming(incoming);
  assert.equal(norm.code, 'LLM_PROVIDER_503');
  assert.equal(norm.layer, 'llm_provider');
  assert.equal(norm.provider, '9router');
  assert.equal(norm.model, 'codebuddy-deepseekv4.1flashfree');
  assert.equal(norm.status_code, 503);
  assert.equal(norm.agent, 'technical_analyst');
  assert.equal(norm.event_id, 'BREAKOUT-1');
  assert.equal(norm.retryable, true);
});

test('normalizeIncoming rejects unknown/garbage codes (no invented code)', () => {
  assert.equal(normalizeIncoming({ code: 'MADE_UP' }), null);
  assert.equal(normalizeIncoming({ error: 'something' }), null);
  assert.equal(normalizeIncoming(null), null);
  assert.equal(normalizeIncoming('agent error'), null);
});

// ── Regression: the exact STOP GATE 04 scenarios ─────────────────────────────

test('STOP GATE: Python unavailable classifies as python_service (UI says Python, not agent)', () => {
  const err = classifyProxyFailure({ error: 'python_service_unavailable', status: 503 });
  assert.equal(err.code, 'PYTHON_SERVICE_UNAVAILABLE');
  assert.notEqual(err.code, 'AGENT_EXCEPTION');
  assert.equal(err.layer, 'python_service');
});

test('STOP GATE: LLM 503 classifies as llm_provider, never agent error', () => {
  const err = classify({ code: 'LLM_PROVIDER_503', agent: 'technical_analyst', provider: '9router', model: 'm1' });
  assert.equal(err.code, 'LLM_PROVIDER_503');
  assert.equal(err.layer, 'llm_provider');
  assert.notEqual(err.layer, 'agent');
  assert.equal(err.retryable, true);
});

test('STOP GATE: agent exception classifies as agent (carries the agent key)', () => {
  const err = classify({ code: 'AGENT_EXCEPTION', agent: 'technical_analyst', message: 'KeyError: x' });
  assert.equal(err.code, 'AGENT_EXCEPTION');
  assert.equal(err.layer, 'agent');
  assert.equal(err.agent, 'technical_analyst');
});
