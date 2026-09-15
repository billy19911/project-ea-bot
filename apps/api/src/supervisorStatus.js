/**
 * Run 18: Supervisor status assembly — honest over invented.
 *
 * `/ai-control/status` previously reported:
 *   - `uptime: health.ok ? 'live' : 'unknown'` — a status string, not uptime;
 *   - `token_budget: 0`, `token_used: 0`,
 *     `max_concurrency: scheduler.stats?.max_concurrency ?? 0` — hard-coded zeros.
 *
 * There is no runtime source for token accounting (the SupervisorAgent class is
 * never instantiated in the API service), so 0 is fabricated data. This module
 * assembles the supervisor block from real sources only and reports `null` when
 * a value is genuinely unknown, never a made-up 0.
 *
 * Kept as plain JS (like `middleware/rateLimitPolicy.js`) so it is unit-testable
 * directly and can be imported by `index.ts`.
 */

/**
 * True only for a real, finite number (rejects NaN, Infinity, strings, null).
 *
 * @param {unknown} value
 * @returns {boolean}
 */
function isFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

/**
 * Normalise the raw model registry from `/ai/models` into per-model usage rows.
 *
 * Usage counters (calls/tokens/cost) have no runtime source in the API service,
 * so they are reported as 0 — but the free/paid flag is taken from the registry's
 * real `is_free` field, so the web cost column never mislabels an unused paid
 * model as "Gratis".
 *
 * @param {unknown} models
 * @returns {Array<{model: string, provider: unknown, calls: number, promptTokens: number, completionTokens: number, cost: number, isFree: boolean}>}
 */
function mapModels(models) {
  if (!Array.isArray(models)) return [];
  return models.map((m) => ({
    model: m?.id ?? m?.name,
    provider: m?.provider,
    calls: 0,
    promptTokens: 0,
    completionTokens: 0,
    cost: 0,
    // Only an explicit `is_free === true` marks a model free.
    isFree: m?.is_free === true,
  }));
}

/**
 * Build the supervisor block for `/ai-control/status` (and the `uptime` field
 * for `/system/overview`).
 *
 * @param {{ health?: any, scheduler?: any, models?: any }} [input]
 * @returns {{
 *   status: string,
 *   routing_policy: string,
 *   max_concurrency: number | null,
 *   token_budget: null,
 *   token_used: null,
 *   uptime: number | null,
 *   models: ReturnType<typeof mapModels>,
 * }}
 */
function buildSupervisorStatus(input) {
  const { health, scheduler, models } = input || {};

  return {
    status: scheduler?.running ? 'active' : 'idle',
    routing_policy: health?.trading_engine ? 'priority_based' : 'unknown',
    // Real source or null — never a fabricated 0.
    max_concurrency: isFiniteNumber(scheduler?.stats?.max_concurrency)
      ? scheduler.stats.max_concurrency
      : null,
    // No runtime source exists → honest null, not 0.
    token_budget: null,
    token_used: null,
    uptime: isFiniteNumber(health?.uptime_seconds) ? health.uptime_seconds : null,
    models: mapModels(models),
  };
}

module.exports = { buildSupervisorStatus, mapModels, isFiniteNumber };
