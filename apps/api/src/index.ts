/**
 * Express API server for EA Bot — dengan structured logging + observability (Phase 27)
 * Phase 28: Security hardening — auth, authorization, audit logs, rate limiting, API security
 */

import { randomUUID } from 'crypto';
import express from 'express';
import cors from 'cors';
import helmet from 'helmet';
import { logger, createChild } from './logger';
import { authenticate, authorize, generateToken, AuthRequest } from './middleware/auth';
import { auditMiddleware, fetchAuditLogs } from './middleware/audit';
import { validatePayload, sanitizeInput, securityHeaders, preventParameterPollution } from './middleware/security';
import { generalLimiter, authLimiter } from './middleware/rateLimiter';
import { validateSecrets, redactSecrets } from './middleware/secrets';
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

// ── Phase 28: Authentication ────────────────────────────────────────────────
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

// ── EPIC 15: Control Plane endpoints ────────────────────────────────────────
app.get('/system/overview', (req, res) => {
  const log = (req as any).log;
  log.info('system.overview');
  res.json({
    mode: 'PAPER',
    status: 'healthy',
    uptime: '4h 23m',
    version: '1.0.0',
    environment: process.env.NODE_ENV || 'development',
    services: [
      { name: 'api', status: 'up', latency_ms: 12 },
      { name: 'python-engine', status: 'up', latency_ms: 28 },
      { name: 'mt5-bridge', status: 'up', latency_ms: 45 },
      { name: 'telegram-bot', status: 'up', latency_ms: 0 },
    ],
    kpis: { open_positions: 3, daily_pnl: 128.4, win_rate_today: 66.7, risk_utilization: 42.0 },
  });
});

app.get('/trading/overview', (req, res) => {
  const log = (req as any).log;
  log.info('trading.overview');
  res.json({
    today: {
      trades: 9, wins: 6, losses: 3, net_pnl: 128.4,
      gross_profit: 214.0, gross_loss: -85.6, profit_factor: 2.5,
    },
    recent_trades: [
      { id: 'T-1021', symbol: 'XAUUSD', side: 'BUY', volume: 0.10, open: 2412.5, close: 2418.2, pnl: 57.0, status: 'CLOSED' },
      { id: 'T-1020', symbol: 'EURUSD', side: 'SELL', volume: 0.20, open: 1.0842, close: 1.0826, pnl: 32.0, status: 'CLOSED' },
      { id: 'T-1019', symbol: 'GBPJPY', side: 'BUY', volume: 0.10, open: 189.42, close: 189.10, pnl: -32.0, status: 'CLOSED' },
      { id: 'T-1022', symbol: 'XAUUSD', side: 'SELL', volume: 0.10, open: 2418.2, close: 0, pnl: 0, status: 'OPEN' },
    ],
  });
});

app.get('/positions', (req, res) => {
  const log = (req as any).log;
  log.info('positions.list');
  res.json({
    positions: [
      { ticket: 50121, symbol: 'XAUUSD', side: 'SELL', volume: 0.10, open_price: 2418.2, current_price: 2415.8, sl: 2424.0, tp: 2404.0, pnl: 24.0, opened_at: '2026-09-15T13:02:11Z' },
      { ticket: 50118, symbol: 'EURUSD', side: 'BUY', volume: 0.20, open_price: 1.0821, current_price: 1.0838, sl: 1.0800, tp: 1.0870, pnl: 34.0, opened_at: '2026-09-15T11:44:03Z' },
      { ticket: 50115, symbol: 'USDJPY', side: 'BUY', volume: 0.10, open_price: 148.22, current_price: 148.05, sl: 147.80, tp: 148.90, pnl: -17.0, opened_at: '2026-09-15T09:18:47Z' },
    ],
    count: 3,
  });
});

app.get('/market/overview', (req, res) => {
  const log = (req as any).log;
  log.info('market.overview');
  res.json({
    session: 'LONDON',
    sessions: [
      { name: 'Sydney', status: 'closed' },
      { name: 'Tokyo', status: 'closed' },
      { name: 'London', status: 'open' },
      { name: 'New York', status: 'upcoming' },
    ],
    symbols: [
      { symbol: 'XAUUSD', price: 2415.8, change_pct: -0.24, spread: 18, volatility: 'HIGH' },
      { symbol: 'EURUSD', price: 1.0838, change_pct: 0.16, spread: 8, volatility: 'LOW' },
      { symbol: 'GBPUSD', price: 1.2712, change_pct: 0.08, spread: 10, volatility: 'MEDIUM' },
      { symbol: 'USDJPY', price: 148.05, change_pct: -0.11, spread: 9, volatility: 'MEDIUM' },
    ],
    regime: { label: 'TREND_UP', confidence: 0.72, volatility: 'MEDIUM' },
  });
});

app.get('/tasks', (req, res) => {
  const log = (req as any).log;
  log.info('tasks.list');
  res.json({
    tasks: [
      { id: 'TSK-401', type: 'ANALYSIS', assignee: 'structure_analyst', status: 'RUNNING', priority: 75, created_at: '13:40:02', duration_ms: 1240 },
      { id: 'TSK-400', type: 'ANALYSIS', assignee: 'momentum_analyst', status: 'COMPLETED', priority: 75, created_at: '13:38:11', duration_ms: 2210 },
      { id: 'TSK-399', type: 'RISK_CHECK', assignee: 'risk_lead', status: 'COMPLETED', priority: 90, created_at: '13:36:40', duration_ms: 380 },
      { id: 'TSK-398', type: 'EXECUTION', assignee: 'executor', status: 'QUEUED', priority: 95, created_at: '13:36:38', duration_ms: 0 },
    ],
    counts: { running: 1, queued: 1, completed: 2, failed: 0 },
  });
});

app.get('/decisions', (req, res) => {
  const log = (req as any).log;
  log.info('decisions.list');
  res.json({
    decisions: [
      { id: 'DEC-77', type: 'ENTRY', symbol: 'XAUUSD', verdict: 'APPROVED', confidence: 0.74, committee: 'market+risk', decided_at: '13:41:55', rationale: 'Breakout with momentum confirmation' },
      { id: 'DEC-76', type: 'NO_TRADE', symbol: 'EURUSD', verdict: 'REJECTED', confidence: 0.41, committee: 'market+risk', decided_at: '12:58:20', rationale: 'Range-bound; edge below threshold' },
      { id: 'DEC-75', type: 'EXIT', symbol: 'GBPJPY', verdict: 'APPROVED', confidence: 0.82, committee: 'position-monitor', decided_at: '12:31:09', rationale: 'SL proximity + adverse momentum' },
    ],
  });
});

// ── EPIC 15 (cont.): more control plane endpoints ───────────────────────────
app.get('/audit/events', (req, res) => {
  const log = (req as any).log;
  log.info('audit.events');
  res.json({
    events: [
      { id: 'AUD-901', timestamp: '13:41:55', actor: 'supervisor', action: 'DECISION_APPROVED', target: 'DEC-77', severity: 'info' },
      { id: 'AUD-900', timestamp: '13:36:40', actor: 'risk_lead', action: 'RISK_CHECK_PASSED', target: 'PROP-512', severity: 'info' },
      { id: 'AUD-899', timestamp: '13:22:10', actor: 'admin', action: 'SETTINGS_UPDATED', target: 'risk.maxDrawdown', severity: 'warning' },
      { id: 'AUD-898', timestamp: '12:58:20', actor: 'supervisor', action: 'DECISION_REJECTED', target: 'DEC-76', severity: 'info' },
      { id: 'AUD-897', timestamp: '12:04:33', actor: 'system', action: 'RECONNECT_MT5', target: 'mt5-bridge', severity: 'warning' },
    ],
    count: 5,
  });
});

app.get('/system/health', (req, res) => {
  const log = (req as any).log;
  log.info('system.health');
  res.json({
    overall: 'healthy',
    components: [
      { name: 'api', status: 'healthy', detail: 'latency p95 34ms' },
      { name: 'python-engine', status: 'healthy', detail: 'queue depth 2' },
      { name: 'mt5-bridge', status: 'healthy', detail: 'ping 45ms' },
      { name: 'redis', status: 'healthy', detail: 'memory 128MB' },
      { name: 'postgres', status: 'healthy', detail: 'connections 6/100' },
      { name: 'telegram', status: 'degraded', detail: 'rate limited, retry in 30s' },
    ],
    checked_at: new Date().toISOString(),
  });
});

app.get('/ai/providers', (req, res) => {
  const log = (req as any).log;
  log.info('ai.providers');
  res.json({
    router: { name: '9Router', status: 'up', latency_ms: 320, failover_enabled: true },
    providers: [
      { name: 'google', status: 'up', models_available: 6, priority: 1, calls_today: 142 },
      { name: 'qwen', status: 'up', models_available: 4, priority: 2, calls_today: 38 },
      { name: 'openai', status: 'up', models_available: 8, priority: 3, calls_today: 12 },
      { name: 'anthropic', status: 'down', models_available: 0, priority: 4, calls_today: 0 },
    ],
    budget: { tokens_used: 1240, tokens_limit: 8000, cost_today: 0.058 },
  });
});

app.get('/ai/models', (req, res) => {
  const log = (req as any).log;
  log.info('ai.models');
  res.json({
    models: [
      { id: 'gemini-2.0-flash-lite', provider: 'google', context: 1000000, status: 'available', role: 'analyst' },
      { id: 'qwen-2.5-72b', provider: 'qwen', context: 131072, status: 'available', role: 'supervisor' },
      { id: 'gpt-4o-mini', provider: 'openai', context: 128000, status: 'available', role: 'fallback' },
      { id: 'claude-3-5-haiku', provider: 'anthropic', context: 200000, status: 'unavailable', role: 'fallback' },
    ],
    last_discovery: '2026-09-15T13:00:00Z',
  });
});

app.get('/learning/analytics', (req, res) => {
  const log = (req as any).log;
  log.info('learning.analytics');
  res.json({
    by_hour: [
      { hour: 9, trades: 24, win_rate: 62.5, avg_pnl: 18.4 },
      { hour: 13, trades: 31, win_rate: 58.1, avg_pnl: 12.2 },
      { hour: 15, trades: 18, win_rate: 44.4, avg_pnl: -8.1 },
      { hour: 20, trades: 12, win_rate: 33.3, avg_pnl: -14.7 },
    ],
    by_regime: [
      { regime: 'TREND_UP', trades: 40, win_rate: 65.0, avg_pnl: 22.1 },
      { regime: 'RANGE', trades: 28, win_rate: 46.4, avg_pnl: -2.4 },
      { regime: 'HIGH_VOL', trades: 17, win_rate: 52.9, avg_pnl: 8.6 },
    ],
    supervisor_kpis: { win_rate: 57.1, profit_factor: 1.86, expectancy: 12.8, max_drawdown: 8.2, false_signals: 4 },
    lessons: [
      { id: 'L-12', text: 'Hindari entry pada jam 20:00+ (win rate 33%)', validated: true },
      { id: 'L-11', text: 'Setup breakout London paling konsisten', validated: true },
    ],
  });
});

app.get('/telegram/status', (req, res) => {
  const log = (req as any).log;
  log.info('telegram.status');
  res.json({
    connected: true,
    bot_username: '@ea_bot_control',
    chat_id: '[REDACTED]',
    last_message_at: '13:38:02',
    commands: ['/status', '/positions', '/risk', '/pause', '/resume'],
    messages_today: 24,
    errors_today: 0,
  });
});

app.get('/committee/trace', (req, res) => {
  const log = (req as any).log;
  log.info('committee.trace');
  res.json({
    traces: [
      {
        decision_id: 'DEC-77',
        symbol: 'XAUUSD',
        rounds: [
          { round: 1, speaker: 'structure_analyst', stance: 'BULLISH', confidence: 0.71, argument: 'H4 breakout with rising lows' },
          { round: 1, speaker: 'momentum_analyst', stance: 'BULLISH', confidence: 0.66, argument: 'RSI 61, MACD positive' },
          { round: 1, speaker: 'volatility_analyst', stance: 'NEUTRAL', confidence: 0.52, argument: 'ATR expanding but within band' },
          { round: 2, speaker: 'risk_lead', stance: 'APPROVE', confidence: 0.78, argument: 'Risk 1.2% within budget; R:R 1:2.4' },
        ],
        final: { verdict: 'APPROVED', confidence: 0.74 },
      },
    ],
  });
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
