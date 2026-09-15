/**
 * Tests for the Python service proxy client (P0-3 / P0-6).
 *
 * Exercises the compiled `dist/pythonClient.js` against an in-process stub
 * HTTP server so no external network is required. Verifies:
 *   - successful proxying labels the result `source: "live"`,
 *   - an unreachable service resolves to `source: "unavailable"` (never throw),
 *   - a timeout resolves to `source: "unavailable"`,
 *   - malformed upstream JSON resolves to `source: "unavailable"`.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');

const { getJson, postJson, DEFAULT_PYTHON_SERVICE_URL } = require('../dist/pythonClient.js');

function withServer(handler) {
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

function setBaseUrl(url) {
  process.env.PYTHON_SERVICE_URL = url;
}

test('defaults to the documented base URL when env is unset', () => {
  assert.equal(DEFAULT_PYTHON_SERVICE_URL, 'http://127.0.0.1:8000');
});

test('successful proxy returns live data', async () => {
  const server = await withServer((req, res) => {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ models: [{ id: 'openai/gpt-4o-mini' }], source: 'gateway' }));
  });
  setBaseUrl(server.baseUrl);
  try {
    const result = await getJson('/ai/models');
    assert.equal(result.ok, true);
    assert.equal(result.source, 'live');
    assert.equal(result.data.models[0].id, 'openai/gpt-4o-mini');
  } finally {
    await server.close();
    delete process.env.PYTHON_SERVICE_URL;
  }
});

test('unreachable service resolves to unavailable without throwing', async () => {
  // Port 1 is reserved/closed on loopback -> connection refused.
  setBaseUrl('http://127.0.0.1:1');
  try {
    const result = await getJson('/system/overview', 1000);
    assert.equal(result.ok, false);
    assert.equal(result.source, 'unavailable');
    assert.equal(result.error, 'python_service_unavailable');
  } finally {
    delete process.env.PYTHON_SERVICE_URL;
  }
});

test('timeout resolves to unavailable', async () => {
  const server = await withServer((_req, res) => {
    // Never respond within the timeout window.
    setTimeout(() => res.end('{}'), 5000);
  });
  setBaseUrl(server.baseUrl);
  try {
    const result = await getJson('/slow', 100);
    assert.equal(result.ok, false);
    assert.equal(result.source, 'unavailable');
    assert.equal(result.error, 'python_service_timeout');
  } finally {
    await server.close();
    delete process.env.PYTHON_SERVICE_URL;
  }
});

test('non-2xx upstream resolves to unavailable', async () => {
  const server = await withServer((_req, res) => {
    res.writeHead(500, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ error: 'boom' }));
  });
  setBaseUrl(server.baseUrl);
  try {
    const result = await getJson('/broken');
    assert.equal(result.ok, false);
    assert.equal(result.source, 'unavailable');
    assert.equal(result.error, 'python_service_error');
  } finally {
    await server.close();
    delete process.env.PYTHON_SERVICE_URL;
  }
});

test('malformed upstream JSON resolves to unavailable', async () => {
  const server = await withServer((_req, res) => {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end('not-json{');
  });
  setBaseUrl(server.baseUrl);
  try {
    const result = await getJson('/garbage');
    assert.equal(result.ok, false);
    assert.equal(result.source, 'unavailable');
    assert.equal(result.error, 'python_service_invalid_json');
  } finally {
    await server.close();
    delete process.env.PYTHON_SERVICE_URL;
  }
});

test('forwards X-Trace-Id header to the upstream service', async () => {
  let seenTraceId;
  const server = await withServer((req, res) => {
    seenTraceId = req.headers['x-trace-id'];
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ ok: true }));
  });
  setBaseUrl(server.baseUrl);
  try {
    const result = await getJson('/observability/traces', 2000, {
      'X-Trace-Id': 'trace-abc-123',
    });
    assert.equal(result.ok, true);
    assert.equal(seenTraceId, 'trace-abc-123');
  } finally {
    await server.close();
    delete process.env.PYTHON_SERVICE_URL;
  }
});

test('postJson forwards the JSON body and X-Trace-Id header', async () => {
  let seenMethod;
  let seenTraceId;
  let seenBody;
  const server = await withServer((req, res) => {
    seenMethod = req.method;
    seenTraceId = req.headers['x-trace-id'];
    const chunks = [];
    req.on('data', (chunk) => chunks.push(chunk));
    req.on('end', () => {
      seenBody = Buffer.concat(chunks).toString('utf-8');
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ trace_id: 'trace-post-1' }));
    });
  });
  setBaseUrl(server.baseUrl);
  try {
    const payload = { event: { event_type: 'BREAKOUT' }, context: {} };
    const result = await postJson('/pipeline/run', payload, 2000, {
      'X-Trace-Id': 'trace-post-1',
    });
    assert.equal(result.ok, true);
    assert.equal(result.source, 'live');
    assert.equal(result.data.trace_id, 'trace-post-1');
    assert.equal(seenMethod, 'POST');
    assert.equal(seenTraceId, 'trace-post-1');
    assert.deepEqual(JSON.parse(seenBody), payload);
  } finally {
    await server.close();
    delete process.env.PYTHON_SERVICE_URL;
  }
});

test('postJson resolves to unavailable when the service is down', async () => {
  setBaseUrl('http://127.0.0.1:1');
  try {
    const result = await postJson('/pipeline/run', { event: {} }, 1000);
    assert.equal(result.ok, false);
    assert.equal(result.source, 'unavailable');
  } finally {
    delete process.env.PYTHON_SERVICE_URL;
  }
});
