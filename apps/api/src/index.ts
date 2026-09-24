/**
 * Express API server for EA Bot — dengan structured logging + observability (Phase 27)
 * Phase 28: Security hardening — auth, authorization, audit logs, rate limiting, API security
 */

import { randomUUID } from 'crypto';
import { createServer } from 'http';
import express, { type Response, type Request } from 'express';
import cors from 'cors';
import helmet from 'helmet';
import { logger, createChild } from './logger';
import { getJson, postJson, putJson } from './pythonClient';
import { authenticate, authorize, generateToken, AuthRequest } from './middleware/auth';
import { auditMiddleware, fetchAuditLogs } from './middleware/audit';
import { validatePayload, sanitizeInput, securityHeaders, preventParameterPollution } from './middleware/security';
import { generalLimiter, authLimiter } from './middleware/rateLimiter';
import { validateSecrets, redactSecrets } from './middleware/secrets';
import {
  wsAuthHandler,
  setupWSConnection,
  setupWSHeartbeat,
  type SecureWebSocket,
} from './middleware/websocket';
import { attachLiveStream } from './liveStream';
// Run 18: honest supervisor status (real uptime; no fabricated zeros).
import { buildSupervisorStatus, buildUsageRows } from './supervisorStatus.js';
import {
  mapTradingOverview,
  mapMarketOverview,
  mapProvidersOverview,
  mapSystemOverview,
} from './overviewMapping.js';
import {
  register,
  httpRequestDuration,
  httpRequestsTotal,
  activeAgents,
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
// Audit P2-12: explicit CORS allowlist (never a wildcard). Origins come from
// CORS_ALLOWED_ORIGINS (comma-separated); default is local dev origins only.
const corsAllowedOrigins = (process.env.CORS_ALLOWED_ORIGINS || 'http://localhost:3000,http://localhost:4321,http://127.0.0.1:4321')
  .split(',')
  .map((o) => o.trim())
  .filter(Boolean);
app.use(
  cors({
    origin: corsAllowedOrigins,
    credentials: true,
  })
);
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
  timeoutMs?: number,
): Promise<void> {
  const traceId = traceIdFromRequest(req);
  const headers = traceId ? { 'X-Trace-Id': traceId } : undefined;
  const result = await postJson<any>(path, body ?? {}, timeoutMs, headers);
  if (!result.ok) {
    // The Python service answered with a non-2xx: preserve its status and
    // message (e.g. a 400 validation rejection like "terminal not running")
    // instead of masking it as a generic 503. Only genuinely unreachable
    // upstreams (no response at all) fall through to the 503 below.
    const upstreamStatus = result.upstreamStatus;
    if (typeof upstreamStatus === 'number' && upstreamStatus >= 400 && upstreamStatus < 500) {
      const payload =
        result.upstreamBody && typeof result.upstreamBody === 'object'
          ? (result.upstreamBody as Record<string, unknown>)
          : { error: result.error };
      res.status(upstreamStatus).json({ ...payload, source: 'live' });
      return;
    }
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

// UI/UX ide #8: trend history of REAL samples (ring buffer in the Python
// service). Read-only proxy — the sampler itself lives in Python so the
// browser never talks to MT5 directly.
app.get('/observability/trend', async (req, res) => {
  const log = (req as any).log;
  const limit = parseInt(String(req.query.limit)) || 0;
  log.info({ limit }, 'observability.trend');
  await sendProxy(res, `/observability/trend?limit=${limit}`, undefined, req);
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

  const [health, scheduler, tasksResult, modelsResult, advisorResult] = await Promise.all([
    getJson<any>('/health'),
    getJson<any>('/scheduler/status'),
    getJson<any>('/tasks'),
    getJson<any>('/ai/models'),
    getJson<any>('/ai/advisor/status'),
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
        // REAL runtime status derived from activity (idle until it has run).
        status: typeof a.status === 'string' ? a.status : 'idle',
        // Priority is the agent's routing priority (a real field, though the
        // analyst tier shares one value); activity metrics are the meaningful
        // per-agent signal.
        priority: typeof a.priority === 'number' ? a.priority : null,
        invocations: typeof a.invocations === 'number' ? a.invocations : 0,
        errors: typeof a.errors === 'number' ? a.errors : 0,
        errorRate: typeof a.error_rate === 'number' ? a.error_rate : 0,
        avgConfidence: typeof a.avg_confidence === 'number' ? a.avg_confidence : null,
        lastActive: a.last_active ?? null,
        signalCounts: a.signal_counts ?? {},
      }))
    : [];

  // Usage rows come from the LLM advisor's REAL per-model counters — only
  // models that were actually called appear. Previously this table listed
  // every registry model padded with hard-coded zeros, which read as a
  // "usage" report while containing no usage data at all.
  const registryModels = modelsResult.ok && Array.isArray(modelsResult.data.models)
    ? modelsResult.data.models
    : [];
  const advisorUsage =
    advisorResult.ok && Array.isArray(advisorResult.data.model_usage)
      ? advisorResult.data.model_usage
      : [];
  const models = buildUsageRows(advisorUsage, registryModels);

  // Run 18: assemble the supervisor block from real sources only. Unknown values
  // (token budget/usage, uptime when the Python service is down) are reported as
  // null rather than fabricated 0 / "live" strings.
  const supervisor = buildSupervisorStatus({
    health: healthData,
    scheduler: schedulerData,
    models: modelsResult.ok ? modelsResult.data.models : [],
  });

  // Only active agent count has a real source here. Token and execution metrics
  // are not recorded by this service, so do not create zero-valued observations.
  const activeCount = agents.filter((a: any) => a.status === 'active').length;
  activeAgents.set(activeCount);

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
    errors: getRecentErrors(10),
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

/**
 * PUT counterpart to {@link sendPostProxy}: forwards a JSON body to the Python
 * service and preserves upstream 4xx bodies (validation errors) verbatim so the
 * settings form (UI/UX ide #7) can show real messages.
 */
async function sendPutProxy(
  res: Response,
  path: string,
  req: Request,
  body: unknown = {},
  timeoutMs?: number,
): Promise<void> {
  const traceId = traceIdFromRequest(req);
  const headers = traceId ? { 'X-Trace-Id': traceId } : undefined;
  const result = await putJson<any>(path, body ?? {}, timeoutMs, headers);
  if (!result.ok) {
    const upstreamStatus = result.upstreamStatus;
    if (typeof upstreamStatus === 'number' && upstreamStatus >= 400 && upstreamStatus < 500) {
      const payload =
        result.upstreamBody && typeof result.upstreamBody === 'object'
          ? (result.upstreamBody as Record<string, unknown>)
          : { error: result.error };
      res.status(upstreamStatus).json({ ...payload, source: 'live' });
      return;
    }
    res.status(503).json({ error: 'python_service_unavailable', source: 'unavailable' });
    return;
  }
  res.json({ ...(result.data as Record<string, unknown>), source: 'live' });
}

app.get('/settings', async (req, res) => {
  await sendProxy(res, '/settings', undefined, req);
});

app.put('/settings', authenticate, async (req, res) => {
  await sendPutProxy(res, '/settings', req, req.body ?? {});
});

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
  const payload = mapSystemOverview(health.ok, healthData, schedulerData);
  res.json(payload);
});

// Phase 31: system certification baseline checks (proxied from Python).
app.get('/certify', async (req, res) => {
  const log = (req as any).log;
  log.info('system.certify');
  await sendProxy(res, '/certify', undefined, req);
});

// ── PRD_V2 Phase 36-56 surface (proxied from Python /v2/*) ──────────────────
// Every route below proxies REAL data from the Python service and never
// fabricates values (PRD_V2 §25/§26/§27). Read-only unless explicitly a
// control action (circuit-breaker, incidents, recovery).

app.get('/v2/circuit-breaker', async (req, res) => {
  await sendProxy(res, '/v2/circuit-breaker', undefined, req);
});

app.post('/v2/circuit-breaker/trigger', authenticate, async (req, res) => {
  await sendPostProxy(res, '/v2/circuit-breaker/trigger', req, req.body ?? {});
});

app.post('/v2/circuit-breaker/recover', authenticate, async (req, res) => {
  await sendPostProxy(res, '/v2/circuit-breaker/recover', req, req.body ?? {});
});

app.post('/v2/recovery/run', authenticate, async (req, res) => {
  await sendPostProxy(res, '/v2/recovery/run', req, req.body ?? {});
});

app.get('/v2/environment', async (req, res) => {
  await sendProxy(res, '/v2/environment', undefined, req);
});

app.get('/v2/accounts', async (req, res) => {
  await sendProxy(res, '/v2/accounts', undefined, req);
});

app.get('/v2/capital', async (req, res) => {
  await sendProxy(res, '/v2/capital', undefined, req);
});

app.get('/v2/incidents', async (req, res) => {
  await sendProxy(res, '/v2/incidents', undefined, req);
});

app.post('/v2/incidents', authenticate, async (req, res) => {
  await sendPostProxy(res, '/v2/incidents', req, req.body ?? {});
});

app.post('/v2/incidents/:id/resolve', authenticate, async (req, res) => {
  const id = encodeURIComponent(String(req.params.id));
  await sendPostProxy(res, `/v2/incidents/${id}/resolve`, req, req.body ?? {});
});

app.get('/v2/slo', async (req, res) => {
  await sendProxy(res, '/v2/slo', undefined, req);
});

app.post('/v2/slo/sample', authenticate, async (req, res) => {
  await sendPostProxy(res, '/v2/slo/sample', req, req.body ?? {});
});

app.get('/v2/execution-quality', async (req, res) => {
  await sendProxy(res, '/v2/execution-quality', undefined, req);
});

app.get('/v2/llm/telemetry', async (req, res) => {
  await sendProxy(res, '/v2/llm/telemetry', undefined, req);
});

app.get('/v2/llm/governance', async (req, res) => {
  await sendProxy(res, '/v2/llm/governance', undefined, req);
});

app.get('/v2/dashboard', async (req, res) => {
  await sendProxy(res, '/v2/dashboard', undefined, req);
});

app.get('/v2/certification/gate', async (req, res) => {
  await sendProxy(res, '/v2/certification/gate', undefined, req);
});

app.get('/v2/research/inbox', async (req, res) => {
  await sendProxy(res, '/v2/research/inbox', undefined, req);
});

app.get('/v2/lifecycle/:strategyId/:version', async (req, res) => {
  const strategyId = encodeURIComponent(String(req.params.strategyId));
  const version = encodeURIComponent(String(req.params.version));
  await sendProxy(res, `/v2/lifecycle/${strategyId}/${version}`, undefined, req);
});

app.get('/v2/decision/:decisionId/replay', async (req, res) => {
  const decisionId = encodeURIComponent(String(req.params.decisionId));
  await sendProxy(res, `/v2/decision/${decisionId}/replay`, undefined, req);
});

app.get('/v2/performance-intelligence', async (req, res) => {
  const dimension = String(req.query.dimension || 'hour');
  await sendProxy(
    res,
    `/v2/performance-intelligence?dimension=${encodeURIComponent(dimension)}`,
    undefined,
    req,
  );
});

// Phase 32: market data health / stale protection (proxied from Python).
app.get('/market/health', async (req, res) => {
  const log = (req as any).log;
  const symbol = String(req.query.symbol || 'XAUUSD');
  log.info({ symbol }, 'market.health');
  await sendProxy(res, `/market/health?symbol=${encodeURIComponent(symbol)}`, undefined, req);
});

// Phase 33: full broker symbol specification (proxied from Python).
app.get('/market/symbol-spec', async (req, res) => {
  const log = (req as any).log;
  const symbol = String(req.query.symbol || 'XAUUSD');
  log.info({ symbol }, 'market.symbol_spec');
  await sendProxy(res, `/market/symbol-spec?symbol=${encodeURIComponent(symbol)}`, undefined, req);
});

// News & economic calendar (proxied from Python). The news page needs both the
// headline feed and the upcoming economic calendar (e.g. USD / US events).
app.get('/market/news', async (req, res) => {
  const log = (req as any).log;
  const limit = Number(req.query.limit) || 20;
  const source = String(req.query.source || 'all');
  log.info({ source, limit }, 'market.news');
  await sendProxy(
    res,
    `/market/news?limit=${limit}&source=${encodeURIComponent(source)}`,
    undefined,
    req,
  );
});

app.get('/market/calendar', async (req, res) => {
  const log = (req as any).log;
  const currency = String(req.query.currency || 'USD');
  const impact = String(req.query.impact || 'all');
  const limit = Number(req.query.limit) || 30;
  log.info({ currency, impact }, 'market.calendar');
  await sendProxy(
    res,
    `/market/calendar?currency=${encodeURIComponent(currency)}&impact=${encodeURIComponent(impact)}&limit=${limit}`,
    undefined,
    req,
  );
});

app.get('/market/sentiment', async (req, res) => {
  const log = (req as any).log;
  const symbol = String(req.query.symbol || 'XAUUSD');
  log.info({ symbol }, 'market.sentiment');
  await sendProxy(res, `/market/sentiment?symbol=${encodeURIComponent(symbol)}`, undefined, req);
});

app.get('/market/summary', async (req, res) => {
  const log = (req as any).log;
  const symbol = String(req.query.symbol || 'XAUUSD');
  log.info({ symbol }, 'market.summary');
  await sendProxy(res, `/market/summary?symbol=${encodeURIComponent(symbol)}`, undefined, req);
});

app.post('/market/refresh', authenticate, async (req, res) => {
  await sendPostProxy(res, '/market/refresh', req, req.body ?? {});
});

// Upcoming economic events (future only) — USD/US by default.
app.get('/market/upcoming', async (req, res) => {
  const log = (req as any).log;
  const currency = String(req.query.currency || 'USD');
  const limit = Number(req.query.limit) || 15;
  log.info({ currency, limit }, 'market.upcoming');
  await sendProxy(
    res,
    `/market/upcoming?currency=${encodeURIComponent(currency)}&limit=${limit}`,
    undefined,
    req,
  );
});

// Learned news patterns from historical outcomes (advisory).
app.get('/market/patterns', async (req, res) => {
  const log = (req as any).log;
  const eventKey = String(req.query.event_key || '');
  log.info({ eventKey }, 'market.patterns');
  await sendProxy(
    res,
    `/market/patterns?event_key=${encodeURIComponent(eventKey)}`,
    undefined,
    req,
  );
});

app.get('/trading/overview', async (req, res) => {
  const log = (req as any).log;
  log.info('trading.overview');
  const [account, positions, scheduler] = await Promise.all([
    getJson<any>('/mt5/accounts/balance'),
    getJson<any>('/mt5/positions'),
    getJson<any>('/scheduler/status'),
  ]);
  if (!account.ok && !positions.ok) {
    res.status(503).json({ error: 'python_service_unavailable', source: 'unavailable' });
    return;
  }
  const accountData = account.ok ? account.data : {};
  const positionsData = positions.ok ? positions.data : { positions: [] };
  const schedulerData = scheduler.ok ? scheduler.data : {};
  res.json(mapTradingOverview(accountData, positionsData, schedulerData));
});

app.get('/positions', async (req, res) => {
  const log = (req as any).log;
  log.info('positions.list');
  await sendProxy(res, '/mt5/positions', undefined, req);
});

app.get('/orders', async (req, res) => {
  const log = (req as any).log;
  log.info('orders.list');
  await sendProxy(res, '/mt5/orders', undefined, req);
});

app.get('/mt5/mode', async (req, res) => {
  const log = (req as any).log;
  log.info('mt5.mode');
  await sendProxy(res, '/mt5/mode', undefined, req);
});

// Lightweight latest-tick proxy (read-only). Used by the live WebSocket
// broadcaster and any client that wants a single quote without pulling bars.
app.get('/mt5/market/tick', async (req, res) => {
  const symbol = String(req.query.symbol || '').trim().toUpperCase();
  if (!/^[A-Z0-9._#+-]{1,32}$/.test(symbol)) {
    res.status(400).json({ error: 'invalid_symbol' });
    return;
  }
  const log = (req as any).log;
  log.info({ symbol }, 'mt5.market.tick');
  await sendProxy(res, `/mt5/market/tick?symbol=${encodeURIComponent(symbol)}`, undefined, req);
});

// Read-only account info for the ACTIVE terminal (UI/UX F2): the dashboard
// shell shows login/server/trade_mode in its sidebar footer. Behind the global
// auth middleware — no mutation, no order path.
app.get('/mt5/accounts/info', async (req, res) => {
  const log = (req as any).log;
  log.info('mt5.accounts.info');
  await sendProxy(res, '/mt5/accounts/info', undefined, req);
});

// Run 24: multi-terminal registry. GET is read-only (auto-detected terminals
// merged with the config file); POST select/arm are mutations and go through
// the global auth middleware plus the general rate limiter.
app.get('/mt5/terminals', async (req, res) => {
  const log = (req as any).log;
  log.info('mt5.terminals.list');
  await sendProxy(res, '/mt5/terminals', undefined, req);
});

app.post('/mt5/terminals/select', authenticate, async (req, res) => {
  const log = (req as any).log;
  log.info('mt5.terminals.select');
  await sendPostProxy(res, '/mt5/terminals/select', req, req.body ?? {});
});

app.post('/mt5/terminals/arm', authenticate, async (req, res) => {
  const log = (req as any).log;
  log.info('mt5.terminals.arm');
  await sendPostProxy(res, '/mt5/terminals/arm', req, req.body ?? {});
});

// Probe akun (F3): read-only, memindahkan binding sementara lalu memulihkannya
// di Python. Timeout lebih longgar karena menyentuh beberapa terminal sekaligus.
app.post('/mt5/terminals/probe', authenticate, async (req, res) => {
  const log = (req as any).log;
  log.info('mt5.terminals.probe');
  await sendPostProxy(res, '/mt5/terminals/probe', req, req.body ?? {}, 30000);
});

// Daily trading report (UI/UX ide #9): REAL closed deals from the attached
// MT5 terminal via Python. Read-only — never re-binds, never orders.
app.get('/reports/daily', async (req, res) => {
  const log = (req as any).log;
  const days = Math.min(Math.max(parseInt(String(req.query.days || '7'), 10) || 7, 1), 90);
  log.info({ days }, 'reports.daily');
  await sendProxy(res, `/reports/daily?days=${days}`, undefined, req);
});

// LLM Advisor (UI/UX ide #1): advisory-only 9Router access with fail-closed
// guardrails enforced in Python. The POST preserves Python's validation
// detail via sendPostProxy.
app.get('/ai/advisor/status', async (req, res) => {
  await sendProxy(res, '/ai/advisor/status', undefined, req);
});

app.post('/ai/advisor/advise', authenticate, async (req, res) => {
  await sendPostProxy(res, '/ai/advisor/advise', req, req.body ?? {});
});

// Research Center (UI/UX ide #6): wires the existing Python ResearchEngine.
// GET routes proxy straight through; POST routes preserve Python's 4xx
// validation detail (sendPostProxy) so the UI can show honest messages.
app.get('/research/overview', async (req, res) => {
  await sendProxy(res, '/research/overview', undefined, req);
});

app.get('/research/experiments', async (req, res) => {
  await sendProxy(res, '/research/experiments', undefined, req);
});

app.post('/research/experiments', authenticate, async (req, res) => {
  await sendPostProxy(res, '/research/experiments', req, req.body ?? {});
});

app.get('/research/experiments/:id', async (req, res) => {
  await sendProxy(res, `/research/experiments/${encodeURIComponent(req.params.id)}`, undefined, req);
});

app.post('/research/experiments/:id/backtest', authenticate, async (req, res) => {
  const experimentId = String(req.params.id);
  await sendPostProxy(res, `/research/experiments/${encodeURIComponent(experimentId)}/backtest`, req, req.body ?? {}, 60000);
});

app.post('/research/compare', authenticate, async (req, res) => {
  await sendPostProxy(res, '/research/compare', req, req.body ?? {});
});

// ── Chart (Fase 1 "Pasar"): candles + indicator series ─────────────────────
app.get('/chart/candles', async (req, res) => {
  const log = (req as any).log;
  log.info('chart.candles');
  const qs = new URLSearchParams();
  for (const key of ['symbol', 'timeframe', 'bars', 'ema_fast', 'ema_slow', 'before']) {
    const v = (req.query as any)[key];
    if (v !== undefined) qs.set(key, String(v));
  }
  await sendProxy(res, `/chart/candles?${qs.toString()}`, undefined, req);
});

// Fase 2 — real engine analysis (entry/SL/TP) + open position levels.
app.get('/chart/analysis', async (req, res) => {
  const log = (req as any).log;
  log.info('chart.analysis');
  const qs = new URLSearchParams();
  for (const key of ['symbol', 'timeframe', 'bars']) {
    const v = (req.query as any)[key];
    if (v !== undefined) qs.set(key, String(v));
  }
  await sendProxy(res, `/chart/analysis?${qs.toString()}`, undefined, req);
});

app.get('/market/overview', async (req, res) => {
  const log = (req as any).log;
  log.info('market.overview');
  const symbolsResult = await getJson<any>('/mt5/symbols');
  if (!symbolsResult.ok) {
    res.status(503).json({ error: 'python_service_unavailable', source: 'unavailable' });
    return;
  }
  res.json(mapMarketOverview(symbolsResult.data));
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
    // Real risk-gate limits from the Python service (null when unavailable —
    // never a hard-coded 15% / 5% in the UI).
    risk_gate: python.ok ? (python.data?.risk_gate ?? null) : null,
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
  res.json(mapProvidersOverview(result.data));
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
      observability: 'GET /observability/metrics, GET /observability/errors, GET /observability/trend',
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

const server = createServer(app);

// Realtime stream (Fase "live"): price + open-position P&L over WebSocket at
// /ws. Auth reuses the same JWT check as HTTP; token may come as
// `?token=` query (browsers can't set headers on the WS upgrade).
const live = attachLiveStream(server, {
  authCheck: (req) => wsAuthHandler(req as Request),
  onConnection: (ws, req) => setupWSConnection(ws as SecureWebSocket, req as Request),
  intervalMs: Number(process.env.LIVE_INTERVAL_MS || 2500),
});
const heartbeat = setupWSHeartbeat(live.wss);

server.listen(PORT, () => {
  logger.info({ port: PORT, nodeEnv: process.env.NODE_ENV, serviceName: process.env.SERVICE_NAME }, 'server.started');
  console.log(`EA Bot API server running on http://localhost:${PORT}`);
  console.log(`  Metrics: http://localhost:${PORT}/metrics`);
  console.log(`  Observability JSON: http://localhost:${PORT}/observability/metrics`);
  console.log(`  Live stream (WS): ws://localhost:${PORT}/ws`);
});

// Graceful shutdown: stop the stream loop before exiting.
for (const sig of ['SIGINT', 'SIGTERM'] as const) {
  process.on(sig, () => {
    try {
      clearInterval(heartbeat as NodeJS.Timeout);
      live.close();
    } catch {
      /* ignore */
    }
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 3000).unref();
  });
}
