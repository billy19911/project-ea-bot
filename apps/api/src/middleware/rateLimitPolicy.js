/**
 * Phase 28 / Run 15: Plain-JS rate limit policy.
 *
 * The dashboard (see apps/web/app/observability/page.tsx) auto-refreshes every
 * 10s and hits three read-only monitoring endpoints, i.e. 18 req/min → 270
 * req/15 min for a user who merely leaves a tab open. With the old global limit
 * of 100/15 min that self-inflicted traffic produced real HTTP 429s
 * ("Gagal memuat strategi (HTTP 429)" on the Strategy page).
 *
 * This module keeps the policy in plain JS so it can be unit-tested directly
 * (no TypeScript build step needed) and imported by `rateLimiter.ts`.
 */

/**
 * Global cap per IP: 600 requests / 15 min. This is still a real abuse guard
 * (≈40 req/min sustained) but comfortably above legitimate dashboard polling
 * (which peaks at 18 req/min) so normal use never trips it, while a misbehaving
 * or hostile client is still throttled.
 */
const GENERAL_LIMIT_MAX = 600;

/**
 * Idempotent, read-only monitoring endpoints the dashboard polls continuously.
 * Exempting these GETs from the global limiter stops the API from 429-ing its
 * own UI. Mutations (POST/PATCH/DELETE) and every other route stay limited.
 */
const POLLING_READ_PATHS = new Set([
  '/observability/metrics',
  '/observability/errors',
  '/ai-control/status',
  '/system/health',
  '/metrics',
  '/health',
]);

/**
 * express-rate-limit `skip` predicate: true → request bypasses `generalLimiter`.
 *
 * Skip only when ALL hold:
 *   - the method is GET (idempotent, no side effects), and
 *   - the path is a known read-only monitoring endpoint polled by the dashboard.
 *
 * Rationale: these endpoints are idempotent read-only monitoring endpoints
 * polled by the dashboard; mutations and everything else stay limited.
 *
 * @param {{ method?: string, path?: string }} req
 * @returns {boolean}
 */
function skipPollingRead(req) {
  if (!req || req.method !== 'GET') return false;
  const path = req.path || req.url || '';
  // Normalise a trailing slash so '/health/' matches '/health'.
  const normalised = path.length > 1 ? path.replace(/\/+$/, '') : path;
  return POLLING_READ_PATHS.has(normalised);
}

module.exports = { GENERAL_LIMIT_MAX, POLLING_READ_PATHS, skipPollingRead };
