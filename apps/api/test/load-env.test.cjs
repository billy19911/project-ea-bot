/**
 * Tests for the runtime env self-loader (fix: "Buat token dev" answered 404
 * after the agent-dashboard restarted the API with a bare `node dist/index.js`
 * and no exported env).
 *
 * Spawns fresh Node processes against the compiled `dist/loadEnv.js` so the
 * ambient test-runner environment can never leak into the assertions.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const apiDir = path.join(__dirname, '..');

/**
 * Run a snippet in a fresh Node process with a scrubbed environment:
 * DEV_AUTH_ENABLED / JWT_SECRET / EA_ENV_FILE / NODE_ENV are removed so the
 * only way a value can appear is via the loader under test.
 */
function runNode(snippet, extraEnv = {}) {
  const env = { ...process.env, ...extraEnv };
  for (const key of ['DEV_AUTH_ENABLED', 'JWT_SECRET', 'EA_ENV_FILE', 'NODE_ENV']) {
    if (!(key in extraEnv)) delete env[key];
  }
  return spawnSync(process.execPath, ['-e', snippet], {
    cwd: apiDir,
    env,
    encoding: 'utf8',
  });
}

const READ_KEYS =
  "require('./dist/loadEnv.js');" +
  'console.log(JSON.stringify({d: process.env.DEV_AUTH_ENABLED ?? null, j: process.env.JWT_SECRET ?? null}));';

function tmpEnvFile(contents) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ea-loadenv-'));
  const file = path.join(dir, 'runtime.env');
  fs.writeFileSync(file, contents);
  return file;
}

test('loads values from EA_ENV_FILE when the ambient env lacks them', () => {
  const file = tmpEnvFile('DEV_AUTH_ENABLED=true\nJWT_SECRET=from-file-secret\n');
  const result = runNode(READ_KEYS, { EA_ENV_FILE: file });
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout.trim()), {
    d: 'true',
    j: 'from-file-secret',
  });
});

test('variables already present in process.env win over the file', () => {
  const file = tmpEnvFile('DEV_AUTH_ENABLED=true\nJWT_SECRET=from-file-secret\n');
  const result = runNode(READ_KEYS, { EA_ENV_FILE: file, DEV_AUTH_ENABLED: 'false' });
  assert.equal(result.status, 0, result.stderr);
  const out = JSON.parse(result.stdout.trim());
  assert.equal(out.d, 'false');
  assert.equal(out.j, 'from-file-secret');
});

test('EA_ENV_FILE pointing at a missing file is a silent no-op', () => {
  const missing = path.join(os.tmpdir(), 'ea-loadenv-missing', 'nope.env');
  const result = runNode(
    "require('./dist/loadEnv.js');" + "console.log(process.env.DEV_AUTH_ENABLED ?? 'unset');",
    { EA_ENV_FILE: missing },
  );
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), 'unset');
});

test('discovery walks up from apps/api/dist and finds the repo .env.runtime', { skip: false }, (t) => {
  const runtimeFile = path.join(apiDir, '..', '..', '.env.runtime');
  if (!fs.existsSync(runtimeFile)) {
    t.skip('no .env.runtime in this checkout');
    return;
  }
  const raw = fs.readFileSync(runtimeFile, 'utf8');
  const match = raw.match(/^DEV_AUTH_ENABLED=(.*)$/m);
  if (!match) {
    t.skip('.env.runtime has no DEV_AUTH_ENABLED entry');
    return;
  }
  const result = runNode(
    "require('./dist/loadEnv.js');" + "console.log(process.env.DEV_AUTH_ENABLED ?? 'unset');",
  );
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), match[1].trim());
});

test('NODE_ENV=production makes the loader a no-op (env is injected externally)', () => {
  const file = tmpEnvFile('DEV_AUTH_ENABLED=true\n');
  const result = runNode(
    "require('./dist/loadEnv.js');" + "console.log(process.env.DEV_AUTH_ENABLED ?? 'unset');",
    { EA_ENV_FILE: file, NODE_ENV: 'production' },
  );
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), 'unset');
});
