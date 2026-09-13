/**
 * Prometheus-style metrics for EA Bot API — Phase 27 Observability.
 *
 * Exposes counters, histograms, and gauges for:
 *   - HTTP request latency & status codes
 *   - Agent execution latency
 *   - LLM token usage
 *   - Error tracking (in-memory recent errors store)
 */

import client from 'prom-client';

// ── Prometheus registry ─────────────────────────────────────────────────────
export const register = new client.Registry();

// Collect default Node.js metrics (event loop lag, heap, GC, etc.)
client.collectDefaultMetrics({ register });

// ── HTTP metrics ────────────────────────────────────────────────────────────
export const httpRequestDuration = new client.Histogram({
  name: 'http_request_duration_seconds',
  help: 'Duration of HTTP requests in seconds',
  labelNames: ['method', 'route', 'status_code'] as const,
  buckets: [0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
  registers: [register],
});

export const httpRequestsTotal = new client.Counter({
  name: 'http_requests_total',
  help: 'Total number of HTTP requests',
  labelNames: ['method', 'route', 'status_code'] as const,
  registers: [register],
});

// ── Agent metrics ───────────────────────────────────────────────────────────
export const agentExecutionDuration = new client.Histogram({
  name: 'agent_execution_duration_seconds',
  help: 'Duration of agent execution in seconds',
  labelNames: ['agent_name'] as const,
  buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30],
  registers: [register],
});

export const agentExecutionsTotal = new client.Counter({
  name: 'agent_executions_total',
  help: 'Total number of agent executions',
  labelNames: ['agent_name', 'status'] as const,
  registers: [register],
});

// ── LLM token metrics ──────────────────────────────────────────────────────
export const llmTokensTotal = new client.Counter({
  name: 'llm_tokens_total',
  help: 'Total LLM tokens consumed',
  labelNames: ['model', 'type'] as const,  // type: prompt | completion
  registers: [register],
});

export const llmCallsTotal = new client.Counter({
  name: 'llm_calls_total',
  help: 'Total LLM API calls',
  labelNames: ['model'] as const,
  registers: [register],
});

export const llmCostTotal = new client.Counter({
  name: 'llm_cost_usd_total',
  help: 'Total LLM cost in USD',
  labelNames: ['model'] as const,
  registers: [register],
});

// ── System gauges ───────────────────────────────────────────────────────────
export const activeAgents = new client.Gauge({
  name: 'active_agents',
  help: 'Number of currently active agents',
  registers: [register],
});

export const tokenBudgetUsed = new client.Gauge({
  name: 'token_budget_used',
  help: 'Current token budget usage',
  registers: [register],
});

export const tokenBudgetLimit = new client.Gauge({
  name: 'token_budget_limit',
  help: 'Token budget limit',
  registers: [register],
});

// ── In-memory error store ───────────────────────────────────────────────────
export interface ErrorRecord {
  id: string;
  timestamp: string;
  source: string;      // agent name or 'api'
  message: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  path?: string;
  statusCode?: number;
  traceId?: string;
}

const MAX_ERRORS = 100;
const recentErrors: ErrorRecord[] = [];

export function recordError(error: Omit<ErrorRecord, 'id' | 'timestamp'>): void {
  const record: ErrorRecord = {
    id: `ERR-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    timestamp: new Date().toISOString(),
    ...error,
  };
  recentErrors.unshift(record);
  if (recentErrors.length > MAX_ERRORS) {
    recentErrors.length = MAX_ERRORS;
  }
}

export function getRecentErrors(limit = 50): ErrorRecord[] {
  return recentErrors.slice(0, limit);
}

export function clearErrors(): void {
  recentErrors.length = 0;
}

// ── Latency snapshots (for JSON endpoint) ───────────────────────────────────
export interface LatencySnapshot {
  route: string;
  method: string;
  count: number;
  avgMs: number;
  p50Ms: number;
  p95Ms: number;
  p99Ms: number;
}

/**
 * Build a JSON-friendly summary of current metrics for the frontend.
 */
export async function getMetricsSummary() {
  const metricsText = await register.metrics();

  // Parse http request histogram for latency summary
  const httpMetrics = await httpRequestDuration.get();
  const requestMetrics = await httpRequestsTotal.get();
  const agentMetrics = await agentExecutionDuration.get();
  const tokenMetrics = await llmTokensTotal.get();
  const callMetrics = await llmCallsTotal.get();
  const costMetrics = await llmCostTotal.get();

  // Build latency summaries per route
  const latencies: Record<string, { count: number; sum: number }> = {};
  for (const val of httpMetrics.values) {
    const route = (val.labels as any).route || 'unknown';
    const method = (val.labels as any).method || 'GET';
    const key = `${method} ${route}`;
    if (!latencies[key]) latencies[key] = { count: 0, sum: 0 };
    if ((val.labels as any).le === '+Inf' || (val as any).metricName?.includes('count')) {
      // sum and count are separate entries
    }
  }

  // Aggregate token usage per model
  const tokensByModel: Record<string, { prompt: number; completion: number; calls: number; cost: number }> = {};
  for (const val of tokenMetrics.values) {
    const model = String((val.labels as any).model || 'unknown');
    const type = String((val.labels as any).type || 'prompt');
    if (!tokensByModel[model]) tokensByModel[model] = { prompt: 0, completion: 0, calls: 0, cost: 0 };
    if (type === 'prompt') tokensByModel[model].prompt += val.value;
    else tokensByModel[model].completion += val.value;
  }
  for (const val of callMetrics.values) {
    const model = String((val.labels as any).model || 'unknown');
    if (!tokensByModel[model]) tokensByModel[model] = { prompt: 0, completion: 0, calls: 0, cost: 0 };
    tokensByModel[model].calls += val.value;
  }
  for (const val of costMetrics.values) {
    const model = String((val.labels as any).model || 'unknown');
    if (!tokensByModel[model]) tokensByModel[model] = { prompt: 0, completion: 0, calls: 0, cost: 0 };
    tokensByModel[model].cost += val.value;
  }

  // Aggregate request counts per route
  const requestCounts: Record<string, Record<string, number>> = {};
  for (const val of requestMetrics.values) {
    const route = String((val.labels as any).route || 'unknown');
    const method = String((val.labels as any).method || 'GET');
    const status = String((val.labels as any).status_code || '200');
    const key = `${method} ${route}`;
    if (!requestCounts[key]) requestCounts[key] = {};
    requestCounts[key][status] = (requestCounts[key][status] || 0) + val.value;
  }

  // Agent execution stats
  const agentStats: Record<string, { count: number; sumSeconds: number }> = {};
  for (const val of agentMetrics.values) {
    const name = String((val.labels as any).agent_name || 'unknown');
    if (!agentStats[name]) agentStats[name] = { count: 0, sumSeconds: 0 };
  }

  return {
    uptime: process.uptime(),
    timestamp: new Date().toISOString(),
    requests: requestCounts,
    tokenUsage: tokensByModel,
    agentStats,
    recentErrors: getRecentErrors(20),
    errorCount: recentErrors.length,
  };
}
