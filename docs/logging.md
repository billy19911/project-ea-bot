# Logging Guide — project-ea-bot

Semua service di monorepo ini menggunakan **structured logging dalam format JSON**.
Ini memungkinkan log aggregator (ELK, Datadog, Grafana Loki, dll.) mem-parsing log secara otomatis.

---

## 1. Prinsip Umum

| Aturan | Keterangan |
|--------|------------|
| **JSON output** | Setiap log baris adalah satu JSON object |
| **Level-based** | Gunakan level yang tepat: `trace` < `debug` < `info` < `warn` < `error` < `fatal` |
| **Trace ID** | Semua log di dalam satu request harus membawa `traceId` yang sama |
| **SERVICE_NAME** | Setiap service mengidentifikasi diri lewat env `SERVICE_NAME` |
| **No console.log** | Jangan pakai `console.log` / `print()` di production code |

---

## 2. Node.js (apps/api) — pino

### Instalasi

```bash
npm install pino pino-pretty
```

### Setup (contoh: `apps/api/src/logger.ts`)

```ts
import pino from "pino";

export const logger = pino({
  // Use pretty-print di development only
  ...(process.env.NODE_ENV === "development"
    ? { transport: { target: "pino-pretty", options: { colorize: true } } }
    : {}),
  level: process.env.LOG_LEVEL || "info",
  base: {
    service: process.env.SERVICE_NAME || "api",
  },
  // Semua log otomatis punya timestamp ISO, level, service name
});

/**
 * Buat child logger untuk sebuah request — membawa traceId.
 */
export function createRequestLogger(traceId: string, extra?: Record<string, unknown>) {
  return logger.child({ traceId, ...extra });
}
```

### Cara pakai di handler

```ts
import { logger, createRequestLogger } from "../logger";

export async function handleRequest(req: Request, res: Response) {
  const traceId = req.headers["x-trace-id"] as string || crypto.randomUUID();
  const log = createRequestLogger(traceId, { path: req.url, method: req.method });

  log.info({ userId: req.user?.id }, "request.received");

  try {
    const result = await doSomething();
    log.info({ result }, "request.completed");
    return result;
  } catch (err) {
    log.error({ err, traceId }, "request.failed");
    throw err;
  }
}
```

### Output sample (production / JSON)

```json
{"level":30,"time":1726147200000,"pid":1234,"hostname":"server-1","service":"api","traceId":"abc-123","msg":"request.completed","userId":42}
{"level":50,"time":1726147201000,"pid":1234,"hostname":"server-1","service":"api","traceId":"abc-123","err":{"type":"Error","message":"timeout"},"msg":"request.failed"}
```

---

## 3. Python (services/python) — structlog

### Instalasi

```bash
pip install structlog orjson
```

### Setup (contoh: `services/python/src/logging_setup.py`)

```python
import sys
import logging
import structlog
from pythonjsonlogger import json as json_logger

def setup_logging() -> None:
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer() if os.getenv("NODE_ENV") == "production" else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Integrate with stdlib logging so third-party libs also log JSON
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(json_logger.JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(level)
```

### Cara pakai di service code

```python
import structlog
from logging_setup import setup_logging

logger = structlog.get_logger()

def handle_request(request):
    trace_id = request.headers.get("x-trace-id", str(uuid.uuid4()))
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(trace_id=trace_id, path=request.path)

    logger.info("request.received", user_id=request.user.id)

    try:
        result = do_something()
        logger.info("request.completed", result=result)
        return result
    except Exception as e:
        logger.error("request.failed", exc_info=True)
        raise
```

### Output sample (production / JSON)

```json
{"levelname": "INFO", "service": "python-service", "trace_id": "abc-123", "event": "request.completed", "result": "ok", "timestamp": "2024-09-12T10:00:00Z"}
{"levelname": "ERROR", "service": "python-service", "trace_id": "abc-123", "event": "request.failed", "exc_info": "...", "timestamp": "2024-09-12T10:00:01Z"}
```

---

## 4. Environment Variables untuk Logging

| Variable | Default | Keterangan |
|----------|---------|------------|
| `LOG_LEVEL` | `info` | Level minimum: `trace`, `debug`, `info`, `warn`, `error`, `fatal` |
| `SERVICE_NAME` | `api` | Nama service — muncul di setiap log line |
| `NODE_ENV` | `development` | Jika `development`, Node.js logger pakai pretty-print |

---

## 5. Trace ID

- **Masuk**: Baca header `x-trace-id` dari incoming request.
- **Belum ada**: Generate UUID v4 baru.
- **Keluar**: Sertakan di response header `x-trace-id` dan di semua log lines.
- **Propagasi**: Jika service A memanggil service B, sertakan `x-trace-id` di HTTP headers.

---

## 6. Best Practices

1. **Jangan log secrets** — password, token, PII tidak boleh masuk log.
2. **Gunakan level với purpose**:
   - `info` — event bisnis penting (request selesai, pembayaran berhasil)
   - `debug` — informasi debugging yang berguna di staging
   - `trace` — sangat detail, hanya di local development
3. **Wajib ada `msg`** — deskripsi singkat event dalam bahasa Inggris, gunakan dot notation: `user.login.failed`.
4. **Sertakan context** — user ID, trace ID, endpoint, duration (ms).
5. **Error log wajib pakai `err`** — di pino: `logger.error({ err, msg: "..." })`; di structlog: `logger.error("...", exc_info=True)`.
