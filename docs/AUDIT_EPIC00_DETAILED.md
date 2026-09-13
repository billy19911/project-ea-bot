# EPIC 00 — Detailed Technical Audit

**Tanggal:** 2026-09-14
**Fokus:** Root cause analysis untuk setiap blocking issue

---

## 1. Build Failure — TypeScript Error

### Lokasi
`apps/api/src/middleware/websocket.ts:99`

### Error
```
error TS2344: Type 'SecureWebSocket' does not satisfy the constraint 'typeof WebSocket'.
  Type 'SecureWebSocket' is missing the following properties from type 'typeof WebSocket':
  prototype, createWebSocketStream, Server, WebSocketServer, and 9 more.
```

### Root Cause
```typescript
export function setupWSHeartbeat(wss: WSServer<SecureWebSocket>): NodeJS.Timer {
```

`SecureWebSocket` adalah **interface** yang extends `WebSocket` (instance type), bukan **class constructor**.

Generic parameter `WSServer<T>` di library `ws` mengharapkan `T extends WebSocket` (instance), tapi TypeScript di mode tertentu membutuhkan `typeof WebSocket` (constructor type) untuk inferensi.

### Fix
Ubah signature menjadi:

```typescript
export function setupWSHeartbeat(wss: WSServer): NodeJS.Timer {
```

Atau jika ingin type-safe:

```typescript
export function setupWSHeartbeat(wss: WSServer<WebSocket>): NodeJS.Timer {
```

Kemudian cast `ws` ke `SecureWebSocket` di dalam callback:

```typescript
wss.clients.forEach((ws: WebSocket) => {
  const sws = ws as SecureWebSocket;
  if (sws.isAlive === false) {
    sws.terminate();
    return;
  }
  sws.isAlive = false;
  sws.ping();
});
```

---

## 2. Test Failure — MT5 Timeframe Map

### Lokasi
`services/python/tests/test_mt5.py:65-67`

### Error
```
FAILED tests/test_mt5.py::test_timeframe_map_populated - assert False
```

### Root Cause
Di `src/mt5/retrieval.py:24-32`:

```python
_TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1 if mt5 else 0,
    "M5": mt5.TIMEFRAME_M5 if mt5 else 0,
    ...
}
```

Ketika `MetaTrader5` **tidak terinstall**, `mt5 = None`, sehingga semua nilai menjadi `0`.

Test mengharuskan:
```python
assert all(v != 0 for v in _TIMEFRAME_MAP.values())
```

Ini akan selalu gagal di environment tanpa MT5.

### Fix Options

**Option A — Skip test jika MT5 tidak tersedia:**
```python
import pytest

@pytest.mark.skipif(mt5 is None, reason="MetaTrader5 not installed")
def test_timeframe_map_populated():
    assert len(_TIMEFRAME_MAP) == 7
    assert all(v != 0 for v in _TIMEFRAME_MAP.values())
```

**Option B — Gunakan fallback constants:**
```python
# Di retrieval.py, definisikan fallback values
MT5_TIMEFRAME_FALLBACK = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 16385,
    "H4": 16388,
    "D1": 16408,
}

_TIMEFRAME_MAP = {
    k: getattr(mt5, f'TIMEFRAME_{k}', v) if mt5 else v
    for k, v in MT5_TIMEFRAME_FALLBACK.items()
}
```

---

## 3. ESLint Flat Config Migration

### Lokasi
Semua workspace Node.js (`apps/api`, `apps/web`, `packages/shared`)

### Error
```
ESLint couldn't find an eslint.config.(js|mjs|cjs) file.
From ESLint v9.0.0, the default configuration file is now eslint.config.js.
```

### Root Cause
ESLint v9 menghapus dukungan `.eslintrc.*` dan memerlukan **flat config**.

### Fix
Buat `eslint.config.js` di setiap workspace. Contoh untuk `apps/api`:

```javascript
import js from '@eslint/js';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    languageOptions: {
      parserOptions: {
        project: './tsconfig.json',
      },
    },
  },
  {
    ignores: ['dist/', 'node_modules/'],
  }
);
```

Untuk `apps/web`, update `eslint.config.js` dengan Next.js plugin:

```javascript
import { dirname } from 'path';
import { fileURLToPath } from 'url';
import { FlatCompat } from '@eslint/eslintrc';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({
  baseDirectory: __dirname,
});

const eslintConfig = [
  ...compat.extends('next/core-web-vitals', 'next/typescript'),
];

export default eslintConfig;
```

---

## 4. Missing Dependencies — Python

### Lokasi
`services/python/src/llm/nine_router.py:11`

### Error
```
ModuleNotFoundError: No module named 'openai'
```

### Root Cause
`requirements.txt` hanya berisi 6 package, tapi `pyproject.toml` dependencies berbeda. Ada ketidaksesuaian.

`nine_router.py` meng-import:
```python
from openai import OpenAI
```

Tapi `openai` tidak ada di `requirements.txt` maupun `pyproject.toml`.

### Fix
Tambahkan ke `pyproject.toml`:

```toml
[project]
dependencies = [
    # ... existing deps ...
    "openai>=1.0.0",
]
```

Lalu jalankan:
```bash
pip install -e .
```

---

## 5. CI/CD Blueprint — Path Mismatch

### Lokasi
`.github/workflows/ci.yml`

### Problem
Workflow merujuk ke:
- `frontend/package-lock.json` → seharusnya `apps/web/package-lock.json`
- `backend/` → seharusnya `services/python/` atau `apps/api/`
- `requirements.txt` di root → seharusnya `services/python/requirements.txt`

### Fix
Update semua path di workflow:

```yaml
- name: Install frontend dependencies
  run: |
    cd apps/web
    npm ci

- name: Install Python dependencies
  run: |
    cd services/python
    pip install -e .
```

---

## 6. FastAPI Deprecated Lifecycle

### Lokasi
`services/python/src/main.py:45`

### Warning
```
DeprecationWarning: on_event is deprecated, use lifespan event handlers instead.
```

### Fix
Ganti dari:
```python
@app.on_event("startup")
async def startup():
    ...
```

Ke:
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_resources()
    yield
    # Shutdown
    await cleanup_resources()

app = FastAPI(lifespan=lifespan)
```

---

## 7. Additional Findings

| No | File | Issue | Severity |
|---|---|---|---|
| 1 | `apps/api/package.json` | `postinstall: "prisma skills sync"` — typo | Medium |
| 2 | `requirements.txt` | Hanya 6 baris, tidak sinkron dengan `pyproject.toml` | Low |
| 3 | `.env.example` | Default JWT_SECRET harus `REPLACE_ME` bukan nilai hardcoded | Medium |
| 4 | `apps/web` ESLint | Next.js lint masih pakai legacy config | High |

---

## Action Items — Prioritized

| Prio | Task | Workspace | Est. Time |
|---|---|---|---|
| P0 | Fix `SecureWebSocket` type error | `apps/api` | 15 min |
| P0 | Skip/fallback MT5 test | `services/python` | 10 min |
| P0 | Add `openai` to dependencies | `services/python` | 5 min |
| P1 | Migrate ESLint to flat config | All Node.js | 30 min |
| P1 | Fix CI/CD paths | `.github` | 15 min |
| P2 | Replace `on_event` with lifespan | `services/python` | 20 min |
| P2 | Fix `postinstall` script | `apps/api` | 2 min |

---

*Audit selesai. Siap untuk eksekusi perbaikan.*
