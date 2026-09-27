const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const jwt = require('jsonwebtoken');

// Deterministic: ensure the module under test never falls back to the legacy
// dev secret, regardless of the ambient environment this test runs in.
process.env.JWT_SECRET = process.env.JWT_SECRET || 'unit-test-secret-not-the-legacy-one';

const auth = require('../dist/middleware/auth.js');
const secrets = require('../dist/middleware/secrets.js');

function invoke(middleware, { authorization } = {}) {
  return new Promise((resolve) => {
    const req = { headers: { authorization }, socket: { remoteAddress: '127.0.0.1' } };
    const res = {
      statusCode: 200,
      status(code) { this.statusCode = code; return this; },
      json(body) { resolve({ status: this.statusCode, body, calledNext: false }); },
    };
    middleware(req, res, () => resolve({ status: res.statusCode, calledNext: true, user: req.user }));
  });
}

test('production rejects tokens signed with the legacy development secret', async () => {
  const oldEnv = process.env.NODE_ENV;
  const oldSecret = process.env.JWT_SECRET;
  process.env.NODE_ENV = 'production';
  delete process.env.JWT_SECRET;

  try {
    const legacyToken = jwt.sign({ userId: 'attacker', role: 'admin' }, 'dev-secret-change-in-production');
    const result = await invoke(auth.authenticate, { authorization: `Bearer ${legacyToken}` });
    assert.equal(result.status, 401);
    assert.equal(result.calledNext, false);
  } finally {
    process.env.NODE_ENV = oldEnv;
    if (oldSecret === undefined) delete process.env.JWT_SECRET;
    else process.env.JWT_SECRET = oldSecret;
  }
});

test('production requires JWT_SECRET and refuses to boot without it', () => {
  const apiDir = path.join(__dirname, '..');
  const result = spawnSync(process.execPath, ['-e', "require('./dist/middleware/auth.js')"], {
    cwd: apiDir,
    env: { ...process.env, NODE_ENV: 'production', JWT_SECRET: '' },
    encoding: 'utf8',
  });

  assert.notEqual(result.status, 0);
  assert.match(result.stderr || '', /JWT_SECRET is required in production/);
});

test('secret redaction removes nested sensitive values without mutating source', () => {
  const source = { apiKey: 'private', nested: { password: 'private', safe: 'ok' } };
  const result = secrets.redactSecrets(source);
  assert.deepEqual(result, { apiKey: '[REDACTED]', nested: { password: '[REDACTED]', safe: 'ok' } });
  assert.equal(source.apiKey, 'private');
  assert.equal(source.nested.password, 'private');
});

test('redactToken removes token query values for safe logging (P2-12)', () => {
  const ws = require('../dist/middleware/websocket.js');
  assert.equal(
    ws.redactToken('/ws?token=secret123&x=1'),
    '/ws?token=[redacted]&x=1'
  );
  assert.equal(ws.redactToken('/ws?x=1'), '/ws?x=1');
});

test('websocket refuses tokens signed with the legacy dev secret in production', () => {
  // The WS layer must reject the legacy public dev secret in production, not
  // silently accept it via a private fallback (audit finding).
  const apiDir = path.join(__dirname, '..');
  const script = `
    process.env.NODE_ENV = 'production';
    process.env.JWT_SECRET = 'real-production-secret';
    const jwt = require('jsonwebtoken');
    const ws = require('./dist/middleware/websocket.js');
    const legacy = jwt.sign({ userId: 'attacker', role: 'admin' }, 'dev-secret-change-in-production');
    const req = { headers: { authorization: 'Bearer ' + legacy }, url: '/ws' };
    const ok = ws.wsAuthHandler(req);
    process.stdout.write(String(ok));
  `;
  const result = spawnSync(process.execPath, ['-e', script], {
    cwd: apiDir,
    env: { ...process.env, NODE_ENV: 'production', JWT_SECRET: 'real-production-secret' },
    encoding: 'utf8',
  });
  assert.equal((result.stdout || '').trim(), 'false');
});

function invokeSanitize(body, query = {}) {
  const security = require('../dist/middleware/security.js');
  return new Promise((resolve) => {
    const req = { body, query, method: 'POST', path: '/strategies', headers: {} };
    const res = {
      statusCode: 200,
      status(code) { this.statusCode = code; return this; },
      json(payload) { resolve({ status: this.statusCode, body: payload, next: false }); },
    };
    security.sanitizeInput(req, res, () => resolve({ status: 200, next: true }));
  });
}

test('sanitizer allows legitimate symbols and free-text (no false positives)', async () => {
  // Regression: the old pattern rejected broker symbols and text containing
  // apostrophes/quotes/brackets. These are all legitimate.
  const legit = [
    { symbol: 'BTCUSD#' },
    { symbol: 'EUR_USD+' },
    { note: "broker's rejection" },
    { description: 'Buy the dip (support + rebound)' },
    { comment: 'trend-following' },
  ];
  for (const body of legit) {
    const result = await invokeSanitize(body);
    assert.equal(result.next, true, `should allow: ${JSON.stringify(body)}`);
  }
});

test('sanitizer still blocks real injection signatures', async () => {
  const attacks = [
    { q: '1; DROP TABLE users' },
    { q: "1' OR '1'='1' UNION SELECT password FROM users" },
    { q: '<script>alert(1)</script>' },
    { q: 'javascript:alert(1)' },
    { q: '<img onerror=alert(1)>' },
    { q: '../../etc/passwd' },
  ];
  for (const body of attacks) {
    const result = await invokeSanitize(body);
    assert.equal(result.status, 400, `should block: ${JSON.stringify(body)}`);
    assert.equal(result.next, false);
  }
});
