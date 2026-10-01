import test from 'node:test';
import assert from 'node:assert/strict';
import { ERROR_CODES, ERROR_LAYER, CAUSE_LABEL, isRetryable, causeLabel } from './errorTaxonomy.ts';

// TASK 04 — web-side taxonomy helpers. Guarantees the UI labels and retry
// policy match the backend so a 503 is never shown as a generic "agent error".

test('exposes all 13 codes with a label and a layer', () => {
  assert.equal(ERROR_CODES.length, 13);
  for (const code of ERROR_CODES) {
    assert.ok(CAUSE_LABEL[code], `missing label for ${code}`);
    assert.ok(ERROR_LAYER[code], `missing layer for ${code}`);
  }
});

test('503-cause labels name the real layer, never a generic "agent error"', () => {
  assert.equal(CAUSE_LABEL.LLM_PROVIDER_503.toLowerCase().includes('agent'), false);
  assert.equal(CAUSE_LABEL.PYTHON_SERVICE_UNAVAILABLE.toLowerCase().includes('agent'), false);
  assert.equal(CAUSE_LABEL.PYTHON_ENDPOINT_5XX.toLowerCase().includes('agent'), false);
});

test('retry policy: only transient/infra errors are retryable', () => {
  for (const code of ['LLM_PROVIDER_503', 'LLM_PROVIDER_5XX', 'LLM_TIMEOUT', 'AGENT_TIMEOUT', 'AGENT_EXCEPTION', 'PYTHON_SERVICE_UNAVAILABLE', 'PYTHON_ENDPOINT_5XX', 'NODE_API_UNAVAILABLE']) {
    assert.equal(isRetryable(code), true, `${code} should be retryable`);
  }
  for (const code of ['LLM_PROVIDER_4XX', 'PYTHON_ENDPOINT_4XX', 'AUTH_FAILURE', 'DATA_GUARD_FAILURE', 'MODEL_UNAVAILABLE']) {
    assert.equal(isRetryable(code), false, `${code} must NOT be retryable`);
  }
});

test('isRetryable is false for unknown/empty codes', () => {
  assert.equal(isRetryable(undefined), false);
  assert.equal(isRetryable(''), false);
  assert.equal(isRetryable('NOT_A_CODE'), false);
});

test('causeLabel falls back honestly for a missing code', () => {
  assert.equal(causeLabel(undefined), 'Penyebab tidak diketahui');
  assert.equal(causeLabel('LLM_PROVIDER_503'), CAUSE_LABEL.LLM_PROVIDER_503);
});
