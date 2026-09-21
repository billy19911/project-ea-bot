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
