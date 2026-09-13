/**
 * Express API server for EA Bot — dengan structured logging + observability (Phase 27)
 */

import { randomUUID } from 'crypto';
import express from 'express';
import cors from 'cors';
import { logger, createChild } from './logger';
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

// Middleware: parse JSON dan attach logger ke request
app.use(cors());
app.use(express.json());

// Middleware: inject child logger per request + traceId
app.use((req, res, next) => {
  const traceId = (req.headers['x-trace-id'] || randomUUID()).toString().slice(0, 36);
  (req as any).log = createChild({ traceId, method: req.method, path: req.url, userAgent: req.headers['user-agent'] }, 'http-request');
  res.setHeader('x-trace-id', traceId);
  next();
});

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
    res.json(summary);
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

// AI Control Center — supervisor status, agent hierarchy, model usage
app.get('/ai-control/status', (req, res) => {
  const log = (req as any).log;
  log.info('ai-control.status');

  // Phase 27: Track agent and token metrics from supervisor data
  const supervisorData = {
    supervisor: { status: 'active', routing_policy: 'priority_based', max_concurrency: 3, token_budget: 8000, token_used: 1240, uptime: '4h 23m' },
    agents: [
      { name: 'supervisor', type: 'supervisor', status: 'active', priority: 100, last_active: '2 detik lalu', error_count: 0 },
      { name: 'structure_analyst', type: 'analyst', status: 'active', priority: 75, last_active: '8 detik lalu', error_count: 0 },
      { name: 'momentum_analyst', type: 'analyst', status: 'idle', priority: 75, last_active: '2 menit lalu', error_count: 0 },
      { name: 'volatility_analyst', type: 'analyst', status: 'active', priority: 75, last_active: '5 detik lalu', error_count: 0 },
      { name: 'news_sentiment', type: 'analyst', status: 'idle', priority: 50, last_active: '12 menit lalu', error_count: 2 },
    ],
    models: [
      { model: 'gemini-2.0-flash-lite', provider: 'google', calls: 142, prompt_tokens: 28400, completion_tokens: 8520, cost: 0 },
      { model: 'qwen-2.5-72b', provider: 'qwen', calls: 38, prompt_tokens: 9120, completion_tokens: 2840, cost: 0 },
      { model: 'gpt-4o-mini', provider: 'openai', calls: 12, prompt_tokens: 3200, completion_tokens: 960, cost: 0.058 },
    ],
    errors: [
      { id: 'E1', timestamp: '13:34:42', agent: 'news_sentiment', message: 'API timeout: news.api.org (5000ms)', severity: 'medium' },
      { id: 'E2', timestamp: '13:29:12', agent: 'news_sentiment', message: 'Rate limit exceeded: 429', severity: 'low' },
    ],
  };

  // Update Prometheus gauges
  const activeCount = supervisorData.agents.filter(a => a.status === 'active').length;
  activeAgents.set(activeCount);
  tokenBudgetUsed.set(supervisorData.supervisor.token_used);
  tokenBudgetLimit.set(supervisorData.supervisor.token_budget);

  // Instrument agent execution (simulate from supervisor data)
  for (const agent of supervisorData.agents) {
    agentExecutionsTotal.inc({ agent_name: agent.name, status: agent.status }, 0);
  }

  // Instrument LLM token usage
  for (const model of supervisorData.models) {
    // We use set-like logic: these are cumulative from the supervisor
    // In production, these would be incremented per actual call
  }

  res.json(supervisorData);
});

app.get('/ai-control/reasoning', (req, res) => {
  const log = (req as any).log;
  log.info('ai-control.reasoning');
  res.json({
    reasoning: 'Trend bullish terdeteksi di struktur H1. Momentum konfirmasi belum solid. Tunggu konfirmasi volatility filter sebelum entry.',
  });
});

// Strategy Center — list, detail, activate/deactivate
interface StrategyRecord {
  id: string;
  name: string;
  version: string;
  active: boolean;
  performance: { win_rate: number; profit_factor: number; sharpe: number; max_dd: number };
  parameters: Record<string, string | number>;
  versions: { version: string; date: string; changes: string }[];
}

const strategiesDB: StrategyRecord[] = [
  { id: 'STR-001', name: 'EMA Crossover Gold', version: 'v1.4', active: true, performance: { win_rate: 57.1, profit_factor: 1.86, sharpe: 1.42, max_dd: 8.2 }, parameters: { ema_fast: 12, ema_slow: 26, atr_period: 14, risk_percent: 1.5 }, versions: [{ version: 'v1.4', date: '2026-09-10', changes: 'Tambah filter ATR minimum' }, { version: 'v1.3', date: '2026-08-28', changes: 'Optimasi exit timing' }, { version: 'v1.2', date: '2026-08-15', changes: 'Initial release' }] },
  { id: 'STR-002', name: 'Momentum London Open', version: 'v2.1', active: true, performance: { win_rate: 53.8, profit_factor: 1.54, sharpe: 1.16, max_dd: 11.4 }, parameters: { rsi_period: 14, rsi_threshold: 65, volume_min: 1000, spread_max: 25 }, versions: [{ version: 'v2.1', date: '2026-09-08', changes: 'Tambah filter spread' }, { version: 'v2.0', date: '2026-08-20', changes: 'Refactor logic entry' }] },
  { id: 'STR-003', name: 'Volatility Filter', version: 'v0.9', active: false, performance: { win_rate: 0, profit_factor: 0, sharpe: 0, max_dd: 0 }, parameters: { bb_period: 20, bb_std: 2, atr_multiplier: 1.5 }, versions: [{ version: 'v0.9', date: '2026-09-05', changes: 'Beta testing' }] },
  { id: 'STR-004', name: 'Structure Breakout', version: 'v3.0', active: false, performance: { win_rate: 0, profit_factor: 0, sharpe: 0, max_dd: 0 }, parameters: { lookback: 50, threshold: 0.002, confirmation_bars: 2 }, versions: [{ version: 'v3.0', date: '2026-09-01', changes: 'Menunggu validasi' }] },
];

app.get('/strategies', (req, res) => {
  const log = (req as any).log;
  log.info('strategies.list');
  res.json({ strategies: strategiesDB });
});

app.get('/strategies/:id', (req, res) => {
  const strat = strategiesDB.find((s) => s.id === req.params.id);
  if (!strat) { res.status(404).json({ error: 'Strategy not found' }); return; }
  const log = (req as any).log;
  log.info({ strategyId: strat.id }, 'strategies.detail');
  res.json({ strategy: strat });
});

app.patch('/strategies/:id/active', (req, res) => {
  const strat = strategiesDB.find((s) => s.id === req.params.id);
  if (!strat) { res.status(404).json({ error: 'Strategy not found' }); return; }
  const active = req.body?.active;
  if (typeof active !== 'boolean') { res.status(400).json({ error: 'active must be boolean' }); return; }
  strat.active = active;
  const log = (req as any).log;
  log.info({ strategyId: strat.id, active: strat.active }, 'strategies.toggle');
  res.json({ strategy: strat, message: `Strategi ${strat.name} ${active ? 'diaktifkan' : 'dinonaktifkan'}` });
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
