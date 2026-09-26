/**
 * FIX-503 / T3: regression test for the missing `GET /research/strategies`
 * proxy route.
 *
 * The Backtest page (apps/web/app/backtest/page.tsx) loads supported strategy
 * types from `GET /research/strategies`. Python already serves it (200), but
 * the Node API had no matching route -> the request fell through to the 404
 * handler (4x in the console). This test boots the compiled server against an
 * in-process stub Python service to prove the route is registered AND proxies
 * through (including query-string pass-through), mirroring the existing
 * spawn-a-fresh-node-process style used by load-env.test.cjs.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const path = require('node:path');
const { spawn } = require('node:child_process');

const apiDir = path.join(__dirname, '..');

/** Start an HTTP stub that records requests and answers with `body`. */
function withPythonStub(handler) {
  return new Promise((resolve) => {
    const server = http.createServer(handler);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      resolve({
        baseUrl: `http://127.0.0.1:${port}`,
        close: () => new Promise((done) => server.close(done)),
      });
    });
  });
}

function getFreePort() {
  return new Promise((resolve) => {
    const server = http.createServer();
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

/** Spawn the compiled API server pointed at the stub Python service. */
async function startApi(pythonBaseUrl) {
  const port = await getFreePort();
  const child = spawn(process.execPath, ['dist/index.js'], {
    cwd: apiDir,
    env: {
      ...process.env,
      NODE_ENV: 'test',
      PORT: String(port),
      PYTHON_SERVICE_URL: pythonBaseUrl,
      JWT_SECRET: process.env.JWT_SECRET || 'unit-test-secret-not-the-legacy-one',
      AUDIT_SECRET: process.env.AUDIT_SECRET || 'unit-test-audit-secret',
      // Tests run over HTTP, so mint a dev bearer token to satisfy the global
      // auth middleware guarding every non-public route.
      DEV_AUTH_ENABLED: 'true',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  await waitForServer(port, child);
  return {
    baseUrl: `http://127.0.0.1:${port}`,
    stop: () =>
      new Promise((done) => {
        child.once('exit', () => done());
        child.kill();
      }),
  };
}

/** Poll the /health endpoint until the child process is listening. */
function waitForServer(port, child) {
  const deadline = Date.now() + 10000;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const req = http.get(`http://127.0.0.1:${port}/health`, (res) => {
        res.resume();
        if (res.statusCode === 200) return resolve();
        retry();
      });
      req.on('error', retry);
      function retry() {
        if (Date.now() > deadline) {
          child.kill();
          return reject(new Error('API server did not start within 10s'));
        }
        setTimeout(attempt, 100);
      }
    };
    attempt();
  });
}

function getJson(url, headers = {}) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { headers }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        const raw = Buffer.concat(chunks).toString('utf-8');
        let body;
        try {
          body = JSON.parse(raw);
        } catch {
          body = raw;
        }
        resolve({ status: res.statusCode, body });
      });
    });
    req.on('error', reject);
  });
}

function postJson(url, payload) {
  return new Promise((resolve, reject) => {
    const data = Buffer.from(JSON.stringify(payload));
    const req = http.request(
      url,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'content-length': data.length },
      },
      (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => {
          const raw = Buffer.concat(chunks).toString('utf-8');
          let body;
          try {
            body = JSON.parse(raw);
          } catch {
            body = raw;
          }
          resolve({ status: res.statusCode, body });
        });
      }
    );
    req.on('error', reject);
    req.end(data);
  });
}

/** Mint a dev bearer token via the API's own /auth/token endpoint. */
async function mintToken(apiBaseUrl) {
  const { status, body } = await postJson(`${apiBaseUrl}/auth/token`, {
    userId: 'unit-test',
    role: 'readonly',
  });
  assert.equal(status, 200, `expected to mint a dev token, got ${status}: ${JSON.stringify(body)}`);
  assert.equal(typeof body.token, 'string');
  return body.token;
}

test('GET /research/strategies proxies to the Python service (not 404)', async () => {
  const seen = [];
  const stub = await withPythonStub((req, res) => {
    seen.push(req.url);
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(
      JSON.stringify({
        ok: true,
        strategies: [{ id: 'ema_crossover', name: 'EMA Crossover' }],
      })
    );
  });

  const api = await startApi(stub.baseUrl);
  try {
    const token = await mintToken(api.baseUrl);
    const { status, body } = await getJson(`${api.baseUrl}/research/strategies`, {
      authorization: `Bearer ${token}`,
    });

    assert.notEqual(status, 404, 'route must be registered in the Node API');
    assert.equal(status, 200);
    assert.equal(body.source, 'live');
    assert.equal(body.ok, true);
    assert.equal(body.strategies[0].id, 'ema_crossover');
    assert.ok(
      seen.some((u) => u && u.startsWith('/research/strategies')),
      `expected an upstream request to /research/strategies, saw: ${JSON.stringify(seen)}`
    );
  } finally {
    await api.stop();
    await stub.close();
  }
});

test('GET /research/strategies passes the query string through', async () => {
  const seen = [];
  const stub = await withPythonStub((req, res) => {
    seen.push(req.url);
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ ok: true, strategies: [] }));
  });

  const api = await startApi(stub.baseUrl);
  try {
    const token = await mintToken(api.baseUrl);
    const { status } = await getJson(
      `${api.baseUrl}/research/strategies?symbol=EURUSD&timeframe=M15`,
      { authorization: `Bearer ${token}` }
    );
    assert.equal(status, 200);
    assert.ok(
      seen.some((u) => u && u.includes('symbol=EURUSD') && u.includes('timeframe=M15')),
      `expected the query string to reach Python, saw: ${JSON.stringify(seen)}`
    );
  } finally {
    await api.stop();
    await stub.close();
  }
});
