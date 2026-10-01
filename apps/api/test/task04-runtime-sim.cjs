/**
 * TASK 04 — AI Control / 503 diagnostics RUNTIME SIMULATION.
 *
 * Self-terminating, bounded end-to-end proof for STOP GATE 04. Spawns a stub
 * Python service plus the REAL compiled Node API (`dist/index.js`) pointed at
 * it, mints a dev bearer token, exercises the three required scenarios against
 * the live `/ai-control/status` handler, prints the observed real output for
 * each, then ALWAYS kills every child in `finally` and `process.exit()`s.
 *
 * Scenarios (STOP GATE 04):
 *   1. Python unavailable  → UI/API says Python unavailable (PYTHON_SERVICE_UNAVAILABLE)
 *   2. LLM provider 503    → UI/API says LLM provider 503 (LLM_PROVIDER_503)
 *   3. Agent exception     → UI/API says agent exception (AGENT_EXCEPTION)
 *
 * Bounded by design (this is what attempt 1 got wrong — it ran blocking
 * foreground servers). Everything is spawn-based with explicit readiness
 * polling, `AbortSignal.timeout`, a hard global watchdog, and a `finally`
 * that tears the whole process tree down.
 *
 * Run:  node apps/api/test/task04-runtime-sim.cjs
 * (Requires `npm run build` first — `dist/errorTaxonomy.js`, `dist/index.js`.)
 */

'use strict';

const http = require('node:http');
const path = require('node:path');
const { spawn } = require('node:child_process');

const apiDir = path.join(__dirname, '..');

// Hard watchdog: if anything hangs the whole script dies in < 90s (well under
// the 120s outer timeout) so it can never repeat attempt 1's stuck behavior.
const WATCHDOG_MS = 90_000;
const watchdog = setTimeout(() => {
  console.error('\n[runtime-sim] WATCHDOG FIRED — forcing exit(1)');
  process.exit(1);
}, WATCHDOG_MS);
watchdog.unref?.();

const children = new Set();

/** Spawn a child, track it for teardown, and return it. */
function spawnTracked(command, args, options) {
  const child = spawn(command, args, options);
  children.add(child);
  child.once('exit', () => children.delete(child));
  return child;
}

/** Kill every tracked child process (best-effort, synchronous tree kill). */
function killAllChildren() {
  for (const child of children) {
    try {
      if (process.platform === 'win32' && child.pid) {
        // taskkill /T kills the whole tree.
        spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
      } else {
        child.kill('SIGKILL');
      }
    } catch {
      /* ignore — teardown must never throw */
    }
  }
  children.clear();
}

// ── Free port helper ─────────────────────────────────────────────────────────
function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = http.createServer();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

// ── Node-side fetch with hard per-call timeout ───────────────────────────────
async function fetchJson(url, { method = 'GET', token, body } = {}) {
  const headers = { accept: 'application/json' };
  if (token) headers.authorization = `Bearer ${token}`;
  const init = { method, headers, signal: AbortSignal.timeout(5000) };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
    headers['content-type'] = 'application/json';
  }
  const res = await fetch(url, init);
  let parsed = null;
  try {
    parsed = await res.json();
  } catch {
    parsed = null;
  }
  return { status: res.status, body: parsed };
}

// ── Stub Python service ──────────────────────────────────────────────────────
/**
 * Realistic-enough Python stub. The behaviour is switched by the scenario:
 *   - mode 'down': server is NOT started at all → connection refused.
 *   - mode 'health', agentErrors: serves every /ai-control probe and, when
 *     requested, injects per-agent `last_error` objects (LLM 503 / exception).
 */
function startPythonStub({ agentErrors = {} } = {}) {
  const healthAgents = [
    { name: 'technical_analyst', display_name: 'TREND-SCAN', agent_type: 'analyst', priority: 5 },
    { name: 'structure_analyst', display_name: 'STRUCTURE', agent_type: 'analyst', priority: 5 },
    { name: 'momentum_analyst', display_name: 'MOMENTUM', agent_type: 'analyst', priority: 5 },
    { name: 'volatility_analyst', display_name: 'VOLATILITY', agent_type: 'analyst', priority: 5 },
    { name: 'supervisor', display_name: 'OVERWATCH', agent_type: 'supervisor', priority: 1 },
  ];

  const server = http.createServer((req, res) => {
    const url = req.url.split('?')[0];
    const json = (status, payload) => {
      const text = JSON.stringify(payload);
      res.writeHead(status, { 'content-type': 'application/json' });
      res.end(text);
    };

    switch (url) {
      case '/health':
        return json(200, {
          status: 'ok',
          environment: 'DEMO',
          uptime_seconds: 12.3,
          agents: healthAgents.map((a) => ({
            ...a,
            // Injected per-agent last_error drives scenarios 2 & 3.
            ...(agentErrors[a.name] ? { last_error: agentErrors[a.name] } : {}),
            status: agentErrors[a.name] ? 'error' : 'active',
            invocations: 3,
            errors: agentErrors[a.name] ? 1 : 0,
            error_rate: agentErrors[a.name] ? 0.33 : 0,
            avg_confidence: 0.5,
            last_active: new Date().toISOString(),
            signal_counts: { NEUTRAL: 3 },
          })),
        });
      case '/scheduler/status':
        return json(200, { running: true, mode: 'event-driven', decisions_total: 4 });
      case '/tasks':
        return json(200, { tasks: [] });
      case '/ai/models':
        return json(200, { models: [] });
      case '/ai/advisor/status':
        return json(200, { enabled: true, calls: 1, refusals: 0, limits: { max_tokens: 512, timeout_s: 20 }, usage: {}, budget: { available: true } });
      case '/supervisor/status':
        return json(200, {
          supervisor: { routing_policy: 'selective', max_concurrency: 4, token_budget: null, token_used: null, uptime: 12 },
          provider_health: { state: 'HEALTHY' },
        });
      case '/ai-control/reasoning':
      case '/decisions':
        return json(200, { decisions: [] });
      default:
        return json(404, { error: 'not_found', path: url });
    }
  });

  return new Promise((resolve, reject) => {
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      resolve({
        baseUrl: `http://127.0.0.1:${port}`,
        close: () => new Promise((done) => server.close(done)),
      });
    });
  });
}

// ── Spawn the REAL Node API ──────────────────────────────────────────────────
async function startApi(pythonBaseUrl) {
  const port = await getFreePort();
  const child = spawnTracked(process.execPath, ['dist/index.js'], {
    cwd: apiDir,
    env: {
      ...process.env,
      NODE_ENV: 'test',
      PORT: String(port),
      PYTHON_SERVICE_URL: pythonBaseUrl,
      PYTHON_SERVICE_TIMEOUT_MS: '3000',
      JWT_SECRET: process.env.JWT_SECRET || 'unit-test-secret-not-the-legacy-one',
      AUDIT_SECRET: process.env.AUDIT_SECRET || 'unit-test-audit-secret',
      DEV_AUTH_ENABLED: 'true',
      CORS_ALLOWED_ORIGINS: 'http://localhost:3000',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  // Surface child stderr for debugging without letting it run away.
  let stderrTail = '';
  child.stderr.on('data', (buf) => {
    stderrTail = (stderrTail + buf.toString()).slice(-2000);
  });

  await waitForReady(port, child, stderrTail);
  return { baseUrl: `http://127.0.0.1:${port}`, port };
}

/** Poll /health (public) with AbortSignal.timeout until the API is up. */
async function waitForReady(port, child, stderrTail) {
  const deadline = Date.now() + 20000; // max ~20 polls x 1s
  let attempt = 0;
  while (Date.now() < deadline) {
    attempt += 1;
    try {
      const res = await fetch(`http://127.0.0.1:${port}/health`, {
        signal: AbortSignal.timeout(5000),
      });
      if (res.ok) return;
    } catch {
      /* not ready yet */
    }
    if (child.exitCode !== null) {
      throw new Error(`API child exited early (code ${child.exitCode}). stderr:\n${stderrTail}`);
    }
  }
  throw new Error(`API server did not become ready within 20s. stderr:\n${stderrTail}`);
}

// ── Mint a dev token ─────────────────────────────────────────────────────────
async function mintToken(apiBase) {
  const { status, body } = await fetchJson(`${apiBase}/auth/token`, {
    method: 'POST',
    body: { userId: 'task04-sim', role: 'admin' },
  });
  if (status !== 200 || !body?.token) {
    throw new Error(`token mint failed: HTTP ${status} ${JSON.stringify(body)}`);
  }
  return body.token;
}

// ── One scenario run ─────────────────────────────────────────────────────────
/**
 * Start stub + API for a scenario, hit /ai-control/status, and return the raw
 * { status, body } plus the first classified error the UI would render.
 */
async function runScenario({ name, agentErrors = {}, pythonDown = false }) {
  let stub = null;
  if (!pythonDown) {
    stub = await startPythonStub({ agentErrors });
  } else {
    // Point at a port that is guaranteed closed → connection refused.
    const deadPort = await getFreePort();
    stub = { baseUrl: `http://127.0.0.1:${deadPort}`, close: async () => {} };
  }

  const api = await startApi(stub.baseUrl);
  try {
    const token = await mintToken(api.baseUrl);
    const { status, body } = await fetchJson(`${api.baseUrl}/ai-control/status`, { token });
    return { name, httpStatus: status, body, apiBase: api.baseUrl };
  } finally {
    await stub.close();
    // The spawned API child is tracked globally; stop it now too so scenarios
    // don't accumulate processes before the top-level teardown.
    for (const child of [...children]) {
      try {
        if (process.platform === 'win32' && child.pid) {
          spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
        } else {
          child.kill('SIGKILL');
        }
      } catch {
        /* ignore */
      }
      children.delete(child);
    }
  }
}

/** Best-effort extraction of the "UI cause" from an /ai-control/status body. */
function uiCause(body) {
  if (!body) return null;
  // Full 503 (all probes failed): top-level taxonomy.
  if (body.taxonomy?.code) return body.taxonomy;
  // Degraded but usable: first classified error.
  if (Array.isArray(body.errors) && body.errors.length) {
    // Prefer an agent-attributed error (scenarios 2 & 3) over probe errors.
    const agentErr = body.errors.find((e) => e.agent);
    return agentErr || body.errors[0];
  }
  return null;
}

/** Print one scenario result in a clear, human-readable block. */
function report(scenario, cause) {
  console.log(`\n${'='.repeat(70)}`);
  console.log(`SCENARIO: ${scenario.name}`);
  console.log(`${'='.repeat(70)}`);
  console.log(`HTTP status : ${scenario.httpStatus}`);
  console.log(`source      : ${scenario.body?.source ?? '(none)'}`);
  console.log(`trace_id    : ${scenario.body?.trace_id ?? '(none)'}`);
  if (Array.isArray(scenario.body?.subsystems)) {
    console.log('subsystems  :');
    for (const t of scenario.body.subsystems) {
      console.log(`  - ${t.name}: ${t.status}${t.code ? ` (${t.code})` : ''}${t.detail ? ` — ${t.detail}` : ''}`);
    }
  }
  if (scenario.body?.degraded) {
    console.log(`degraded    : ${JSON.stringify(scenario.body.degraded)}`);
  }
  if (cause) {
    console.log('classified cause the UI renders:');
    console.log(`  code        : ${cause.code}`);
    console.log(`  layer       : ${cause.layer}`);
    console.log(`  service     : ${cause.service}`);
    console.log(`  endpoint    : ${cause.endpoint}`);
    console.log(`  status_code : ${cause.status_code}`);
    console.log(`  agent       : ${cause.agent}`);
    console.log(`  provider    : ${cause.provider}`);
    console.log(`  model       : ${cause.model}`);
    console.log(`  event_id    : ${cause.event_id}`);
    console.log(`  retryable   : ${cause.retryable}`);
    console.log(`  trace_id    : ${cause.trace_id}`);
    console.log(`  message     : ${cause.message}`);
  } else {
    console.log('!! NO CLASSIFIED CAUSE FOUND');
  }
}

// ── Assertions ───────────────────────────────────────────────────────────────
const failures = [];
function expect(label, condition, extra = '') {
  const ok = Boolean(condition);
  console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${label}${extra ? ` — ${extra}` : ''}`);
  if (!ok) failures.push(label);
}

// ── Main ─────────────────────────────────────────────────────────────────────
async function main() {
  console.log('TASK 04 — AI Control / 503 diagnostics runtime simulation');
  console.log(`node ${process.version} · cwd ${process.cwd()}`);

  // Scenario 1 — Python unavailable.
  const s1 = await runScenario({ name: '1. Python unavailable', pythonDown: true });
  const c1 = uiCause(s1.body);
  report(s1, c1);
  expect('S1 HTTP 503', s1.httpStatus === 503, `got ${s1.httpStatus}`);
  expect('S1 top-level cause = PYTHON_SERVICE_UNAVAILABLE', s1.body?.taxonomy?.code === 'PYTHON_SERVICE_UNAVAILABLE', s1.body?.taxonomy?.code);
  expect('S1 UI cause = PYTHON_SERVICE_UNAVAILABLE', c1?.code === 'PYTHON_SERVICE_UNAVAILABLE', c1?.code);
  expect('S1 NOT a generic agent error', c1?.code !== 'AGENT_EXCEPTION' && c1?.layer !== 'agent', c1?.layer);
  expect('S1 Python tile UNAVAILABLE', (s1.body?.subsystems || []).some((t) => t.name === 'python' && t.status === 'UNAVAILABLE'));
  expect('S1 trace_id visible', typeof s1.body?.trace_id === 'string' && s1.body.trace_id.length > 0);
  expect('S1 retryable visible', c1?.retryable === true, String(c1?.retryable));

  // Scenario 2 — LLM provider 503 (Python up; agent last_error classified).
  const llmError = {
    code: 'LLM_PROVIDER_503',
    layer: 'llm_provider',
    service: 'llm_provider',
    endpoint: '/agent/technical_analyst',
    status_code: 503,
    agent: 'technical_analyst',
    event_id: 'BREAKOUT-4630a8c1',
    model: 'codebuddy-deepseekv4.1flashfree',
    provider: '9router',
    retryable: true,
    message: 'LLM provider reported 503 Service Unavailable.',
  };
  const s2 = await runScenario({
    name: '2. LLM provider 503',
    agentErrors: { technical_analyst: llmError },
  });
  const c2 = uiCause(s2.body);
  report(s2, c2);
  expect('S2 HTTP 200 (page usable with partial failure)', s2.httpStatus === 200, `got ${s2.httpStatus}`);
  expect('S2 UI cause = LLM_PROVIDER_503', c2?.code === 'LLM_PROVIDER_503', c2?.code);
  expect('S2 layer = llm_provider (NOT agent)', c2?.layer === 'llm_provider', c2?.layer);
  expect('S2 provider surfaced', c2?.provider === '9router', c2?.provider);
  expect('S2 model surfaced', !!c2?.model, c2?.model);
  expect('S2 agent surfaced', c2?.agent === 'technical_analyst', c2?.agent);
  expect('S2 status_code 503', c2?.status_code === 503, String(c2?.status_code));
  expect('S2 retryable YES', c2?.retryable === true, String(c2?.retryable));
  expect('S2 trace_id visible', typeof s2.body?.trace_id === 'string' && s2.body.trace_id.length > 0);
  expect('S2 agents still listed (page usable)', Array.isArray(s2.body?.agents) && s2.body.agents.length > 0);
  expect('S2 Python tile HEALTHY (partial failure only)', (s2.body?.subsystems || []).some((t) => t.name === 'python' && t.status === 'HEALTHY'));

  // Scenario 3 — Agent exception (authentic agent-layer failure).
  const agentExc = {
    code: 'AGENT_EXCEPTION',
    layer: 'agent',
    service: 'agent',
    endpoint: null,
    status_code: null,
    agent: 'structure_analyst',
    event_id: 'STRUCTURE_SHIFT-9f',
    model: null,
    provider: '9router',
    retryable: true,
    message: 'KeyError: structure_high',
  };
  const s3 = await runScenario({
    name: '3. Agent exception',
    agentErrors: { structure_analyst: agentExc },
  });
  const c3 = uiCause(s3.body);
  report(s3, c3);
  expect('S3 HTTP 200 (page usable)', s3.httpStatus === 200, `got ${s3.httpStatus}`);
  expect('S3 UI cause = AGENT_EXCEPTION', c3?.code === 'AGENT_EXCEPTION', c3?.code);
  expect('S3 layer = agent', c3?.layer === 'agent', c3?.layer);
  expect('S3 agent surfaced', c3?.agent === 'structure_analyst', c3?.agent);
  expect('S3 retryable YES', c3?.retryable === true, String(c3?.retryable));
  expect('S3 trace_id visible', typeof s3.body?.trace_id === 'string' && s3.body.trace_id.length > 0);

  // ── Summary ────────────────────────────────────────────────────────────────
  console.log(`\n${'='.repeat(70)}`);
  if (failures.length === 0) {
    console.log('RUNTIME SIMULATION: PASS — all 3 scenarios classified correctly.');
    console.log('No generic misleading "agent error" label for 503 / Python-unavailable.');
  } else {
    console.log(`RUNTIME SIMULATION: FAIL — ${failures.length} assertion(s) failed:`);
    for (const f of failures) console.log(`  - ${f}`);
  }
  console.log(`${'='.repeat(70)}`);
  return failures.length === 0 ? 0 : 1;
}

main()
  .then((code) => {
    killAllChildren();
    // Give taskkill a tick to run, then exit deterministically.
    setTimeout(() => process.exit(code), 300);
  })
  .catch((err) => {
    console.error('\n[runtime-sim] ERROR:', err && err.stack ? err.stack : err);
    killAllChildren();
    setTimeout(() => process.exit(1), 300);
  });
