/**
 * Phase 28 / Run 15: Plain-JS rate limit policy.
 *
 * The dashboard auto-refreshes every 10s and, across its ~40 pages, polls a
 * large set of read-only monitoring/query endpoints (each page hits several).
 * With a modest global cap that self-inflicted polling traffic produced real
 * HTTP 429s ("Too Many Requests" on /v2/circuit-breaker, /settings, etc.).
 *
 * This module keeps the policy in plain JS so it can be unit-tested directly
 * (no TypeScript build step needed) and imported by `rateLimiter.ts`.
 */

/**
 * Global cap per IP: 600 requests / 15 min. This is still a real abuse guard
 * (≈40 req/min sustained) for MUTATING requests. Idempotent read-only GETs are
 * exempt via `skip` (see `skipPollingRead`) so the API never 429s its own UI.
 */
const GENERAL_LIMIT_MAX = 600;

/**
 * Idempotent, read-only GET endpoints the dashboard polls continuously.
 *
 * Kept for documentation/telemetry and for callers that want the "known
 * polling" subset explicitly. The `skip` predicate below is broader: ANY GET is
 * exempt (see rationale), so a page that adds a new read endpoint never
 * regresses into 429s. This set lists the historically hot ones.
 */
const POLLING_READ_PATHS = new Set([
  '/observability/metrics',
  '/observability/errors',
  '/observability/trend',
  '/ai-control/status',
  '/system/health',
  '/system/overview',
  '/trading/overview',
  '/settings',
  '/mt5/accounts/info',
  '/mt5/terminals',
  '/mt5/mode',
  '/orders',
  '/positions',
  '/strategies',
  '/reconciliation/status',
  '/sltp/status',
  '/v2/circuit-breaker',
  '/v2/capital',
  '/v2/accounts',
  '/v2/slo',
  '/v2/incidents',
  '/v2/execution-quality',
  '/v2/environment',
  '/v2/certification/gate',
  '/metrics',
  '/health',
]);

/**
 * express-rate-limit `skip` predicate: true → request bypasses `generalLimiter`.
 *
 * Skip for EVERY GET request. Rationale: every route we expose over GET is an
 * idempotent, read-only proxy/query (monitoring, market data, status) — the
 * dashboard polls them continuously and they must never 429. Instead of
 * maintaining a brittle allowlist that breaks whenever a page adds an endpoint
 * (the cause of the observed 429 storm), we exempt the whole idempotent
 * read-only class and keep the limiter focused on MUTATIONS (POST/PATCH/PUT/
 * DELETE), which is where the real abuse risk lives. `authLimiter` continues to
 * protect authentication regardless.
 *
 * @param {{ method?: string, path?: string }} req
 * @returns {boolean}
 */
function skipPollingRead(req) {
  if (!req || req.method !== 'GET') return false;
  // Optional safety net: never skip a GET that is explicitly flagged as
  // non-idempotent (e.g. a route adding side effects but using GET). Currently
  // none, but future-proofs the exemption.
  if (req.__skipRateLimitExempt === false) return false;
  return true;
}

module.exports = { GENERAL_LIMIT_MAX, POLLING_READ_PATHS, skipPollingRead };
