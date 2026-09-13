const test = require('node:test');
const assert = require('node:assert/strict');
const jwt = require('jsonwebtoken');

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

test('secret redaction removes nested sensitive values without mutating source', () => {
  const source = { apiKey: 'private', nested: { password: 'private', safe: 'ok' } };
  const result = secrets.redactSecrets(source);
  assert.deepEqual(result, { apiKey: '[REDACTED]', nested: { password: '[REDACTED]', safe: 'ok' } });
  assert.equal(source.apiKey, 'private');
  assert.equal(source.nested.password, 'private');
});
