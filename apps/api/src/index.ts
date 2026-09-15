/**
 * Express API server for EA Bot — dengan structured logging + observability (Phase 27)
 * Phase 28: Security hardening — auth, authorization, audit logs, rate limiting, API security
 */

import { randomUUID } from 'crypto';
import express, { type Response, type Request } from 'express';
import cors from 'cors';
import helmet from 'helmet';
import { logger, createChild } from './logger';
import { getJson, postJson } from './pythonClient';
import { authenticate, authorize, generateToken, AuthRequest } from './middleware/auth';
import { auditMiddleware, fetchAuditLogs } from './middleware/audit';
import { validatePayload, sanitizeInput, securityHeaders, preventParameterPollution } from './middleware/security';
import { generalLimiter, authLimiter } from './middleware/rateLimiter';
import { validateSecrets, redactSecrets } from './middleware/secrets';
// Run 18: honest supervisor status (real uptime; no fabricated zeros).
import { buildSupervisorStatus } from './supervisorStatus.js';
import {
  register,
  httpRequestDuration,
  httpRequestsTotal,
  agentExecutionDuration,
  agentExecutionsTotal,
  llmTokensTotal,
  llmCallsTotal,
  llmCostTotal,
  activeAgents,
  tokenBudgetUsed,
  tokenBudgetLimit,
  recordError,
  getRecentErrors,
  clearErrors,
  getMetricsSummary,
} from './metrics';

const app = express();
const PORT = process.env.PORT || 3001;

// Phase 28: Validate secrets on startup
validateSecrets();

// Phase 28: Security headers via helmet
app.use(helmet({
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      scriptSrc: ["'self'", "'unsafe-inline'"],
      styleSrc: ["'self'", "'unsafe-inline'"],
    },
  },
}));

// Middleware: parse JSON dan attach logger ke request
app.use(cors());
app.use(express.json({ limit: '1mb' }));

// Phase 28: Security middleware
app.use(securityHeaders);
app.use(validatePayload);
app.use(sanitizeInput);
app.use(preventParameterPollution);

// Phase 28: Audit logging
app.use(auditMiddleware);

// Middleware: inject child logger per request + traceId
app.use((req, res, next) => {
  const traceId = (req.headers['x-trace-id'] || randomUUID()).toString().slice(0, 36);
  (req as any).log = createChild({ traceId, method: req.method, path: req.url, userAgent: req.headers['user-agent'] }, 'http-request');
  res.setHeader('x-trace-id', traceId);
  next();
});

// Phase 28: Rate limiting after trace context
app.use(generalLimiter);

// ── Phase 27: HTTP metrics middleware ────────────────────────────────────────
app.use((req, res, next) => {
  // Skip metrics endpoint itself to avoid self-reporting noise
  if (req.path === '/metrics' || req.path === '/observability/metrics') {
    next();
    return;
  }

  const start = process.hrtime.bigint();

  res.on('finish', () => {
    const durationNs = Number(process.hrtime.bigint() - start);
    const durationSec = durationNs / 1e9;
    const route = normalizeRoute(req.route?.path || req.path);
    const method = req.method;
    const statusCode = String(res.statusCode);

    httpRequestDuration.observe({ method, route, status_code: statusCode }, durationSec);
    httpRequestsTotal.inc({ method, route, status_code: statusCode });

    // Track errors
    if (res.statusCode >= 500) {
      recordError({
        source: 'api',
        message: `HTTP ${res.statusCode} on ${method} ${req.path}`,
        severity: res.statusCode >= 500 ? 'high' : 'medium',
        path: req.path,
        statusCode: res.statusCode,
        traceId: (req as any).log?.bindings?.()?.traceId,
      });
    }
  });

  next();
});

/** Normalize dynamic route segments for metric labels */
function normalizeRoute(path: string): string {
  return path
    .replace(/\/[a-f0-9-]{36}/g, '/:id')       // UUIDs
    .replace(/\/\d+/g, '/:id')                  // numeric IDs
    .replace(/\/STR-\d+/g, '/:id')              // strategy IDs
    .replace(/\/sig_\d+/g, '/:id');             // signal IDs
}

// ── Python service proxy ────────────────────────────────────────────────────
//
// Every control-plane endpoint below proxies REAL data from the Python FastAPI
// service and labels the response with `source`. When the service is
// unreachable we return HTTP 503 `{ error, source: "unavailable" }` — we NEVER
// invent numbers (PRD_V2 §25/§26/§27).
type ProxyTransform = (data: any) => Record<string, unknown>;

/**
 * Extract the request trace id (PRD §26/§27), falling back to the id assigned
 * by the request-scoped logger middleware.
 */
function traceIdFromRequest(req?: Request): string | undefined {
  if (!req) return undefined;
  const header = req.headers['x-trace-id'];
  const value = Array.isArray(header) ? header[0] : header;
  if (value && String(value).trim()) return String(value).trim();
  const fromLog = (req as any).log?.bindings?.()?.traceId;
  return typeof fromLog === 'string' && fromLog.trim() ? fromLog : undefined;
}

/** Build the optional `X-Trace-Id` forward header from a request, if present. */
function headersForTrace(req?: Request): { 'X-Trace-Id': string } | undefined {
  const traceId = traceIdFromRequest(req);
  return traceId ? { 'X-Trace-Id': traceId } : undefined;
}

async function sendProxy(
  res: Response,
  path: string,
  transform?: ProxyTransform,
  req?: Request,
): Promise<void> {
  const traceId = traceIdFromRequest(req);
  const headers = traceId ? { 'X-Trace-Id': traceId } : undefined;
  const result = await getJson<any>(path, undefined, headers);
  if (!result.ok) {
    res.status(503).json({ error: 'python_service_unavailable', source: 'unavailable' });
    return;
  }
  const payload = transform ? transform(result.data) : result.data;
  const body: Record<string, unknown> = { ...(payload as Record<string, unknown>), source: 'live' };
  if (traceId) body.trace_id = traceId;
  res.json(body);
}

/**
 * POST counterpart to {@link sendProxy}: forwards `body` (and the incoming
 * `X-Trace-Id`) to the Python service. Non-2xx upstream responses preserve the
 * Python status via passthrough; an unreachable service returns 503
 * `{ error, source: 'unavailable' }` matching the existing proxy style.
 */
async function sendPostProxy(
  res: Response,
  path: string,
  req: Request,
  body: unknown = {},
): Promise<void> {
  const traceId = traceIdFromRequest(req);
  const headers = traceId ? { 'X-Trace-Id': traceId } : undefined;
  const result = await postJson<any>(path, body ?? {}, undefined, headers);
  if (!result.ok) {
    res.status(503).json({ error: 'python_service_unavailable', source: 'unavailable' });
    return;
  }
  const payload =
    result.data && typeof result.data === 'object'
      ? (result.data as Record<string, unknown>)
      : { data: result.data };
  const responseBody: Record<string, unknown> = { ...payload, source: 'live' };
  // Ensure the trace id round-trips even when the Python service omitted it.
  if (traceId && responseBody.trace_id === undefined) responseBody.trace_id = traceId;
  // Passthrough the upstream status when it carries one (2xx preserved).
  const status = typeof result.status === 'number' && result.status >= 200 ? result.status : 200;
  res.status(status).json(responseBody);
}

// ── Phase 28: Authentication ────────────────────────────────────────────────
// PRD_V2 §28 Security: authentication is applied to ALL routes except a small
// explicit public allowlist. Public: /health, /metrics, /auth/token. Everything
// else (including /system/*, /trading/*, /strategies, /signals, /observability/*)
// now requires a valid Bearer token.
const PUBLIC_PATHS = new Set<string>(['/health', '/metrics', '/auth/token']);

app.use((req, res, next) => {
  // Normalise trailing slash so '/health/' matches '/health'.
  const path = req.path.length > 1 ? req.path.replace(/\/+$/, '') : req.path;
  if (PUBLIC_PATHS.has(path)) {
    next();
    return;
  }
  authenticate(req, res, next);
});

app.post('/auth/token', authLimiter, (req, res) => {
  // Development-only token minting. Production must use an external IdP.
  if (process.env.NODE_ENV === 'production' || process.env.DEV_AUTH_ENABLED !== 'true') {
    res.status(404).json({ error: 'Not found' });
    return;
  }
  const { userId, role } = req.body || {};
  if (typeof userId !== 'string' || !['admin', 'user', 'readonly'].includes(role)) {
    res.status(400).json({ error: 'userId and valid role required' });
    return;
  }
  res.json({ token: generateToken(userId, role) });
});

// ── Phase 28: Audit log access (admin only) ─────────────────────────────────
app.get('/audit-logs', authenticate, authorize('admin'), async (req, res) => {
  const limit = Math.min(Math.max(parseInt(String(req.query.limit || '100'), 10) || 100, 1), 1000);
  res.json({ logs: await fetchAuditLogs(limit), count: limit });
});

// ── Prometheus /metrics endpoint ────────────────────────────────────────────
app.get('/metrics', async (_req, res) => {
  try {
    res.set('Content-Type', register.contentType);
    res.end(await register.metrics());
  } catch (err) {
    res.status(500).end(String(err));
  }
});

// ── Phase 27: JSON metrics summary for frontend ─────────────────────────────
app.get('/observability/metrics', async (req, res) => {
  const log = (req as any).log;
  log.info('observability.metrics');
  try {
    const summary = await getMetricsSummary();
    // P2-20: merge the REAL Python MetricsRegistry snapshot so the dashboard
    // shows Python-side metrics, not only the Node summary. The existing Node
    // fields are preserved for backwards compatibility; when Python is down we
    // add `python: { available: false }` and never fail (no 500).
    const pythonResult = await getJson<{ metrics?: unknown }>(
      '/observability/metrics',
      undefined,
      headersForTrace(req),
    );
    const python = pythonResult.ok
      ? { available: true, metrics: pythonResult.data?.metrics ?? {} }
      : { available: false };
    res.json({ ...summary, python });
  } catch (err) {
    log.error({ err }, 'observability.metrics.error');
    res.status(500).json({ error: 'Failed to collect metrics' });
  }
});

app.get('/observability/errors', (req, res) => {
  const log = (req as any).log;
  const limit = parseInt(String(req.query.limit)) || 50;
  log.info({ limit }, 'observability.errors');
  res.json({ errors: getRecentErrors(limit), count: getRecentErrors(limit).length });
});

app.delete('/observability/errors', (req, res) => {
  clearErrors();
  res.json({ message: 'Errors cleared' });
});

// PRD §26/§27: recent real pipeline traces proxied from the Python service.
app.get('/observability/traces', async (req, res) => {
  const log = (req as any).log;
  const limit = parseInt(String(req.query.limit)) || 50;
  log.info({ limit }, 'observability.traces');
  await sendProxy(res, `/observability/traces?limit=${limit}`, undefined, req);
});

// PRD §26/§27: trigger one autonomous pipeline cycle via the Python service.
// Proxies POST /pipeline/run, forwarding the body and the X-Trace-Id header so
// the dashboard can run a cycle and receive the Python trace_id.
app.post('/pipeline/run', authenticate, async (req, res) => {
  const log = (req as any).log;
  log.info('pipeline.run');
  await sendPostProxy(res, '/pipeline/run', req, req.body ?? {});
});

// PRD_V2 §14: reconciliation status proxied from the Python service (real data).
app.get('/reconciliation/status', async (req, res) => {
  const log = (req as any).log;
  log.info('reconciliation.status');
  await sendProxy(res, '/reconciliation/status', undefined, req);
});

// AI Control Center — supervisor status, agent hierarchy, model usage
app.get('/ai-control/status', async (req, res) => {
  const log = (req as any).log;
  log.info('ai-control.status');

  const [health, scheduler, tasksResult, modelsResult] = await Promise.all([
    getJson<any>('/health'),
    getJson<any>('/scheduler/status'),
    getJson<any>('/tasks'),
    getJson<any>('/ai/models'),
  ]);

  if (!health.ok && !scheduler.ok && !tasksResult.ok && !modelsResult.ok) {
    res.status(503).json({ error: 'python_service_unavailable', source: 'unavailable' });
    return;
  }

  const healthData = health.ok ? health.data : {};
  const schedulerData = scheduler.ok ? scheduler.data : {};
  const tasksData = tasksResult.ok ? tasksResult.data : { tasks: [] };

  const agents = Array.isArray(healthData.agents)
    ? healthData.agents.map((a: any) => ({
        name: a.name,
        type: a.agent_type ?? a.type ?? 'agent',
        status: 'active',
        priority: typeof a.priority === 'number' ? a.priority : 50,
        lastActive: undefined,
        errorCount: 0,
      }))
    : [];

  const models = modelsResult.ok && Array.isArray(modelsResult.data.models)
    ? buildSupervisorStatus({ models: modelsResult.data.models }).models
    : [];

  // Run 18: assemble the supervisor block from real sources only. Unknown values
  // (token budget/usage, uptime when the Python service is down) are reported as
  // null rather than fabricated 0 / "live" strings.
  const supervisor = buildSupervisorStatus({
    health: healthData,
    scheduler: schedulerData,
    models: modelsResult.ok ? modelsResult.data.models : [],
  });

  // Update Prometheus gauges from real (or absent) data.
  const activeCount = agents.filter((a: any) => a.status === 'active').length;
  activeAgents.set(activeCount);
  tokenBudgetUsed.set(0);
  tokenBudgetLimit.set(0);
  for (const agent of agents) {
    agentExecutionsTotal.inc({ agent_name: agent.name, status: agent.status }, 0);
    agentExecutionDuration.observe({ agent_name: agent.name }, 0);
  }
  for (const model of models) {
    llmCallsTotal.inc({ model: model.model }, 0);
    llmTokensTotal.inc({ model: model.model, type: 'prompt' }, 0);
    llmCostTotal.inc({ model: model.model }, 0);
  }

  res.json({
    supervisor: {
      status: supervisor.status,
      routing_policy: supervisor.routing_policy,
      max_concurrency: supervisor.max_concurrency,
      token_budget: supervisor.token_budget,
      token_used: supervisor.token_used,
      uptime: supervisor.uptime,
    },
    agents,
    models,
    tasks: Array.isArray(tasksData.tasks) ? tasksData.tasks : [],
    errors: [],
    source: 'live',
  });
});

app.get('/ai-control/reasoning', async (req, res) => {
  const log = (req as any).log;
  log.info('ai-control.reasoning');
  const result = await getJson<any>('/decisions');
  if (!result.ok) {
    res.status(503).json({ error: 'python_service_unavailable', source: 'unavailable' });
    return;
  }
  const decisions = Array.isArray(result.data.decisions) ? result.data.decisions : [];
  const latest = decisions[0];
  res.json({
    reasoning: latest
      ? latest.risk_reason || latest.status || `${latest.decision ?? 'NO_DATA'}`
      : 'No decisions recorded yet.',
    source: 'live',
  });
});

// Strategy Center — list, detail, activate/deactivate.
//
// These routes proxy the REAL StrategyRegistry exposed by the Python service
// (EPIC 13). The previous hard-coded `strategiesDB` seed data has been removed;
// when Python is unreachable we return 503 `source: "unavailable"` and never
// fabricate rows.
interface MappedStrategy {
  id: string;
  name: string;
  version: string;
  active: boolean;
  performance: { win_rate: number; profit_factor: number; sharpe: number; max_dd: number };
  parameters: Record<string, string | number>;
  versions: { version: string; date: string; changes: string }[];
}

/**
 * Map a Python `VersionedStrategy.to_dict()` record to the shape the web page
 * already consumes. `versions` defaults to just this record; the list handler
 * overrides it with every sibling version of the same strategy name.
 */
function mapStrategyRecord(py: any): MappedStrategy {
  const metrics = py?.metrics_summary ?? {};
  return {
    id: py?.strategy_id,
    name: py?.name,
    version: py?.version,
    active: py?.status === 'ACTIVE',
    performance: {
      win_rate: metrics.win_rate ?? 0,
      profit_factor: metrics.profit_factor ?? 0,
      sharpe: metrics.sharpe_ratio ?? 0,
      max_dd: metrics.max_drawdown ?? 0,
    },
    parameters: py?.parameters ?? {},
    versions: [
      { version: py?.version, date: py?.created_at, changes: py?.description ?? '' },
    ],
  };
}

/** Build the per-name version history the strategy detail page renders. */
function buildVersionHistory(records: any[]): Map<string, MappedStrategy['versions']> {
  const byName = new Map<string, MappedStrategy['versions']>();
  for (const record of records) {
    const entry = { version: record?.version, date: record?.created_at, changes: record?.description ?? '' };
    const list = byName.get(record?.name) ?? [];
    list.push(entry);
    byName.set(record?.name, list);
  }
  return byName;
}

app.get('/strategies', async (req, res) => {
  const log = (req as any).log;
  log.info('strategies.list');
  const result = await getJson<any>('/strategies', undefined, headersForTrace(req));
  if (!result.ok) {
    res.status(503).json({ error: 'python_service_unavailable', source: 'unavailable' });
    return;
  }
  const records: any[] = Array.isArray(result.data?.strategies) ? result.data.strategies : [];
  const versionHistory = buildVersionHistory(records);
  const strategies = records.map((record: any) => ({
    ...mapStrategyRecord(record),
    versions: versionHistory.get(record?.name) ?? mapStrategyRecord(record).versions,
  }));
  res.json({ strategies, source: 'live' });
});

app.get('/strategies/:id', async (req, res) => {
  const log = (req as any).log;
  log.info({ strategyId: req.params.id }, 'strategies.detail');
  const result = await getJson<any>(`/strategies/${req.params.id}`, undefined, headersForTrace(req));
  if (!result.ok) {
    res.status(503).json({ error: 'python_service_unavailable', source: 'unavailable' });
    return;
  }
  res.json({ strategy: mapStrategyRecord(result.data?.strategy ?? {}), source: 'live' });
});

app.patch('/strategies/:id/active', async (req, res) => {
  const log = (req as any).log;
  const active = req.body?.active;
  if (typeof active !== 'boolean') {
    res.status(400).json({ error: 'active must be boolean' });
    return;
  }
  log.info({ strategyId: req.params.id, active }, 'strategies.toggle');
  const result = await postJson<any>(
    `/strategies/${req.params.id}/active`,
    { active },
    undefined,
    headersForTrace(req),
  );
  if (!result.ok) {
    res.status(503).json({ error: 'python_service_unavailable', source: 'unavailable' });
    return;
  }
  res.json({
    strategy: mapStrategyRecord(result.data?.strategy ?? {}),
    message: result.data?.message ?? '',
  });
});

// ── EPIC 15: Control Plane endpoints ────────────────────────────────────────
// All of these proxy REAL data from the Python service (see pythonClient.ts).
// On failure they return 503 with source="unavailable".

app.get('/system/overview', async (req, res) => {
  const log = (req as any).log;
  log.info('system.overview');
  const [health, scheduler] = await Promise.all([
    getJson<any>('/health'),
    getJson<any>('/scheduler/status'),
  ]);
  if (!health.ok && !scheduler.ok) {
    res.status(503).json({ error: 'python_service_unavailable', source: 'unavailable' });
    return;
  }
  const healthData = health.ok ? health.data : {};
  const schedulerData = scheduler.ok ? scheduler.data : {};
  // Run 18: real uptime (seconds) from the Python service, or null when absent.
  const { uptime } = buildSupervisorStatus({ health: healthData, scheduler: schedulerData });
  res.json({
    mode: 'PAPER',
    status: health.ok ? (healthData.status ?? 'unknown') : 'degraded',
    uptime,
    version: healthData.version ?? null,
    environment: healthData.environment ?? (process.env.NODE_ENV || 'development'),
    services: [
      { name: 'api', status: 'up', latency_ms: 0 },
      { name: 'python-engine', status: health.ok ? 'up' : 'down', latency_ms: null },
      { name: 'scheduler', status: schedulerData.running ? 'up' : 'idle', latency_ms: null },
    ],
    agents_registered: healthData.agents_registered ?? 0,
    kpis: {},
    source: 'live',
  });
});

app.get('/trading/overview', async (req, res) => {
  const log = (req as any).log;
  log.info('trading.overview');
  const [account, positions] = await Promise.all([
    getJson<any>('/mt5/accounts/balance'),
    getJson<any>('/mt5/positions'),
  ]);
  if (!account.ok && !positions.ok) {
    res.status(503).json({ error: 'python_service_unavailable', source: 'unavailable' });
    return;
  }
  const accountData = account.ok ? account.data : {};
  const positionsData = positions.ok ? positions.data : { positions: [] };
  const openPositions = Array.isArray(positionsData.positions) ? positionsData.positions : [];
  res.json({
    today: {
      trades: 0,
      wins: 0,
      losses: 0,
      net_pnl: accountData.total_unrealized_pnl ?? 0,
      gross_profit: 0,
      gross_loss: 0,
      profit_factor: 0,
    },
    account: accountData.account ?? null,
    open_positions: openPositions.length,
    recent_trades: [],
    source: 'live',
  });
});

app.get('/positions', async (req, res) => {
  const log = (req as any).log;
  log.info('positions.list');
  await sendProxy(res, '/mt5/positions', undefined, req);
});

app.get('/market/overview', async (req, res) => {
  const log = (req as any).log;
  log.info('market.overview');
  const symbolsResult = await getJson<any>('/mt5/symbols');
  if (!symbolsResult.ok) {
    res.status(503).json({ error: 'python_service_unavailable', source: 'unavailable' });
    return;
  }
  const symbols = Array.isArray(symbolsResult.data.symbols) ? symbolsResult.data.symbols : [];
  res.json({
    session: null,
    sessions: [],
    symbols,
    regime: null,
    source: 'live',
  });
});

app.get('/tasks', async (req, res) => {
  const log = (req as any).log;
  log.info('tasks.list');
  await sendProxy(res, '/tasks', undefined, req);
});

app.get('/decisions', async (req, res) => {
  const log = (req as any).log;
  log.info('decisions.list');
  await sendProxy(res, '/decisions', undefined, req);
});

// ── EPIC 15 (cont.): more control plane endpoints ───────────────────────────
app.get('/audit/events', async (req, res) => {
  const log = (req as any).log;
  log.info('audit.events');
  await sendProxy(res, '/audit/events', undefined, req);
});

app.get('/system/health', async (req, res) => {
  const log = (req as any).log;
  log.info('system.health');

  const started = Date.now();
  const python = await getJson<any>('/health');
  const pythonLatency = Date.now() - started;

  const components = [
    {
      name: 'api',
      status: 'healthy',
      detail: `up ${Math.round(process.uptime())}s`,
    },
    {
      name: 'python-engine',
      status: python.ok ? 'healthy' : 'down',
      detail: python.ok ? `latency ${pythonLatency}ms` : 'unreachable',
    },
  ];

  res.json({
    overall: python.ok ? 'healthy' : 'degraded',
    components,
    checked_at: new Date().toISOString(),
    source: 'live',
  });
});

app.get('/ai/providers', async (req, res) => {
  const log = (req as any).log;
  log.info('ai.providers');
  const result = await getJson<any>('/ai/models');
  if (!result.ok) {
    res.status(503).json({ error: 'python_service_unavailable', source: 'unavailable' });
    return;
  }
  const models = Array.isArray(result.data.models) ? result.data.models : [];
  const byProvider = new Map<string, number>();
  for (const model of models) {
    const provider = model.provider ?? 'unknown';
    byProvider.set(provider, (byProvider.get(provider) ?? 0) + 1);
  }
  const providers = Array.from(byProvider.entries()).map(([name, models_available], index) => ({
    name,
    status: result.data.health?.state === 'CONNECTED' ? 'up' : 'degraded',
    models_available,
    priority: index + 1,
    calls_today: 0,
  }));
  res.json({
    router: {
      name: '9Router',
      status: result.data.health?.state === 'CONNECTED' ? 'up' : 'degraded',
      latency_ms: null,
      failover_enabled: true,
    },
    providers,
    budget: { tokens_used: 0, tokens_limit: 0, cost_today: 0 },
    source: 'live',
  });
});

app.get('/ai/models', async (req, res) => {
  const log = (req as any).log;
  log.info('ai.models');
  await sendProxy(res, '/ai/models', undefined, req);
});

app.get('/learning/analytics', async (req, res) => {
  const log = (req as any).log;
  log.info('learning.analytics');
  await sendProxy(res, '/learning/analytics', undefined, req);
});

app.get('/telegram/status', async (req, res) => {
  const log = (req as any).log;
  log.info('telegram.status');
  await sendProxy(res, '/telegram/status', undefined, req);
});

app.get('/committee/trace', async (req, res) => {
  const log = (req as any).log;
  log.info('committee.trace');
  const result = await getJson<any>('/decisions');
  if (!result.ok) {
    res.status(503).json({ error: 'python_service_unavailable', source: 'unavailable' });
    return;
  }
  const decisions = Array.isArray(result.data.decisions) ? result.data.decisions : [];
  const traces = decisions.map((d: any) => ({
    decision_id: d.decision_id ?? d.event_id ?? null,
    symbol: d.symbol ?? null,
    rounds: Array.isArray(d.trace) ? d.trace : [],
    final: { verdict: d.decision ?? 'UNKNOWN', confidence: null },
  }));
  res.json({ traces, source: 'live' });
});

// Health check
app.get('/health', (req, res) => {
  const log = (req as any).log;
  log.info({ statusCode: 200 }, 'health.check');
  res.json({
    status: 'healthy',
    timestamp: Date.now(),
    uptime: process.uptime(),
  });
});

// Root endpoint
app.get('/', (req, res) => {
  const log = (req as any).log;
  log.info('root.requested');
  res.json({
    message: 'EA Bot API',
    version: '1.0.0',
    service: process.env.SERVICE_NAME || 'api',
    endpoints: {
      health: 'GET /health',
      signals: 'GET /signals, POST /signals',
      metrics: 'GET /metrics',
      observability: 'GET /observability/metrics, GET /observability/errors',
    },
  });
});

// Trade signals endpoints
const signals: any[] = [];

app.get('/signals', (req, res) => {
  const log = (req as any).log;
  log.info({ count: signals.length }, 'signals.list');
  res.json({ signals, count: signals.length });
});

app.post('/signals', (req, res) => {
  const log = (req as any).log;
  const signal = {
    id: `sig_${Date.now()}`,
    ...req.body,
    timestamp: Date.now(),
  };
  signals.push(signal);
  log.info({ signalId: signal.id }, 'signal.created');
  res.status(201).json(signal);
});

// 404 handler
app.use((req, res) => {
  const log = (req as any).log;
  log.warn({ path: req.path, method: req.method }, 'route.not_found');
  res.status(404).json({ error: 'Not found' });
});

// Error handler
app.use((err: any, req: any, res: any, _next: any) => {
  const log = req?.log || logger;
  log.error({ err: err?.stack, path: req?.path }, 'server.error');

  // Phase 27: Record error to observability store
  recordError({
    source: 'api',
    message: err?.message || 'Internal server error',
    severity: 'high',
    path: req?.path,
    statusCode: 500,
  });

  res.status(500).json({ error: 'Internal server error' });
});

app.listen(PORT, () => {
  logger.info({ port: PORT, nodeEnv: process.env.NODE_ENV, serviceName: process.env.SERVICE_NAME }, 'server.started');
  console.log(`EA Bot API server running on http://localhost:${PORT}`);
  console.log(`  Metrics: http://localhost:${PORT}/metrics`);
  console.log(`  Observability JSON: http://localhost:${PORT}/observability/metrics`);
});
