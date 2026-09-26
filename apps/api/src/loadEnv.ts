/**
 * Runtime env self-loader — fix "login ribet / Buat token dev 404".
 *
 * The agent-dashboard supervisor restarts this API with a bare
 * `node dist/index.js` and no exported environment. `start-all.ps1` normally
 * exports `.env.runtime` (DEV_AUTH_ENABLED, JWT_SECRET, PYTHON_API_KEY, …), so
 * a supervised restart silently loses those vars — `/auth/token` then answers
 * 404 and the one-click login breaks.
 *
 * Behaviour:
 *   - production: no-op (env is injected externally, per Phase 28 policy).
 *   - EA_ENV_FILE set: that file is the only candidate (missing → no-op).
 *   - otherwise: walk up from this file's directory looking for `.env.runtime`.
 *   - values already present in process.env always win (Node loadEnvFile
 *     semantics), so an explicit shell/CI env is never overridden.
 *
 * Import this module FIRST in index.ts (before middleware/auth): auth.ts
 * captures JWT_SECRET at import time.
 */

import { existsSync } from 'fs';
import { dirname, join, resolve } from 'path';

function candidateFile(): string | null {
  const explicit = process.env.EA_ENV_FILE;
  if (explicit) {
    return resolve(explicit);
  }
  let dir = __dirname;
  for (let i = 0; i < 8; i += 1) {
    const candidate = join(dir, '.env.runtime');
    if (existsSync(candidate)) {
      return candidate;
    }
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

function loadRuntimeEnv(): void {
  if (process.env.NODE_ENV === 'production') return;
  if (typeof process.loadEnvFile !== 'function') return;
  const file = candidateFile();
  if (!file || !existsSync(file)) return;
  try {
    process.loadEnvFile(file);
  } catch (err) {
    // A malformed runtime file must never crash the API. Never log values.
    console.warn(`[loadEnv] could not load ${file}: ${(err as Error).message}`);
  }
}

loadRuntimeEnv();
