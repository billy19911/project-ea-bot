/**
 * Run 15: rate-limit policy regression tests.
 *
 * Guards the fix for the real self-inflicted 429: the dashboard's 10s polling of
 * read-only monitoring endpoints must not count against the global limiter, and
 * the global cap must stay a real abuse guard (600 / 15 min).
 *
 * Matches the existing test style: `node --test` over compiled `dist/` output
 * (no extra build step beyond the `npm run build` that `npm test` already runs).
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const { generalLimiter, generalLimiterOptions } = require('../dist/middleware/rateLimiter.js');
const {
  GENERAL_LIMIT_MAX,
  skipPollingRead,
} = require('../dist/middleware/rateLimitPolicy.js');

test('generalLimiter config exposes max 600 and a skip function', () => {
  assert.equal(GENERAL_LIMIT_MAX, 600);
  assert.equal(generalLimiterOptions.max, 600);
  assert.equal(generalLimiterOptions.windowMs, 15 * 60 * 1000);
  assert.equal(typeof generalLimiterOptions.skip, 'function');
  // The real middleware is still constructed (express-rate-limit v7 does not
  // expose the raw config on the returned function).
  assert.equal(typeof generalLimiter, 'function');
});

test('skip predicate exempts read-only dashboard polling GETs', () => {
  assert.equal(generalLimiterOptions.skip, skipPollingRead);
  assert.equal(skipPollingRead({ method: 'GET', path: '/observability/metrics' }), true);
  assert.equal(skipPollingRead({ method: 'GET', path: '/observability/errors' }), true);
  assert.equal(skipPollingRead({ method: 'GET', path: '/ai-control/status' }), true);
  assert.equal(skipPollingRead({ method: 'GET', path: '/system/health' }), true);
  assert.equal(skipPollingRead({ method: 'GET', path: '/metrics' }), true);
  assert.equal(skipPollingRead({ method: 'GET', path: '/health' }), true);
});

test('skip predicate does NOT exempt mutations or other routes', () => {
  assert.equal(skipPollingRead({ method: 'POST', path: '/observability/metrics' }), false);
  assert.equal(skipPollingRead({ method: 'GET', path: '/strategies' }), false);
  assert.equal(skipPollingRead({ method: 'DELETE', path: '/observability/errors' }), false);
  assert.equal(skipPollingRead({ method: 'PATCH', path: '/strategies/STR-1/active' }), false);
  assert.equal(skipPollingRead({ method: 'GET', path: '/system/overview' }), false);
});

test('authLimiter is unchanged at 5/15min (security control intact)', () => {
  const { authLimiter, authLimiterOptions } = require('../dist/middleware/rateLimiter.js');
  assert.equal(authLimiterOptions.max, 5);
  assert.equal(authLimiterOptions.skip, undefined);
  assert.equal(typeof authLimiter, 'function');
});
