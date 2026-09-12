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

### Setup

Logger sudah tersedia di `apps/api/src/logger.ts`. Import di file mana saja:

```ts
import { logger, createChild } from "./logger";
```

### Cara pakai di route handler

Logger di-inject otomatis oleh middleware ke `req.log` (child logger dengan traceId):

```ts
app.get('/health', (req, res) => {
  req.log.info({ statusCode: 200 }, 'health.check');
  res.json({ status: 'healthy' });
});
```

### Child logger untuk non-HTTP context

```ts
import { logger, createChild } from "./logger";

const jobLog = createChild({ jobId: "abc-123", type: "cron" });
jobLog.info("job.started");
jobLog.error({ err }, "job.failed");
```

### Output sample (production / JSON)

```json
{"level":"info","time":1726147200000,"service":"api","traceId":"abc-123","msg":"request.received","method":"GET","path":"/health"}
{"level":"error","time":1726147201000,"service":"api","traceId":"abc-123","err":{"type":"Error","message":"timeout"},"msg":"request.failed"}
```

Di development, outputnya lebih readable berkat `pino-pretty`.

---

## 3. Python (services/python) — structlog

### Instalasi

```bash
pip install structlog python-json-logger orjson
```

### Setup

Logger sudah tersedia di `services/python/src/logging_setup.py`. Panggil sekali di awal application:

```python
from logging_setup import setup_logging, get_logger

setup_logging()  # harus dipanggil pertama kali
log = get_logger("my_module")
```

### Cara pakai

```python
import structlog
from logging_setup import setup_logging, bind_trace, clear_trace

setup_logging()
logger = structlog.get_logger()

def handle_request(request):
    trace_id = request.headers.get("x-trace-id", str(uuid.uuid4()))
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(trace_id=trace_id, path=request.url.path)

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
{"event": "request.received", "level": "info", "service": "python-service", "trace_id": "abc-123", "timestamp": "2024-09-12T10:00:00Z", "user_id": 42}
{"event": "request.failed", "level": "error", "service": "python-service", "trace_id": "abc-123", "timestamp": "2024-09-12T10:00:01Z"}
```

Di development, outputnya lebih readable (ConsoleRenderer).

---

## 4. Environment Variables untuk Logging

| Variable | Default | Keterangan |
|----------|---------|------------|
| `LOG_LEVEL` | `info` | Level minimum: `trace`, `debug`, `info`, `warn`, `error`, `fatal` |
| `SERVICE_NAME` | `api` | Nama service — muncul di setiap log line |
| `NODE_ENV` | `development` | Jika `development`, Node.js logger pakai pretty-print |

---

## 5. Trace ID

- **Masuk**: Baca header `x-trace-id` dari incoming request (Node.js middleware di `apps/api/src/index.ts` sudah handle ini).
- **Belum ada**: Generate UUID v4 baru.
- **Keluar**: Sertakan di response header `x-trace-id` dan di semua log lines.
- **Propagasi**: Jika service A memanggil service B, sertakan `x-trace-id` di HTTP headers.

---

## 6. Best Practices

1. **Jangan log secrets** — password, token, PII tidak boleh masuk log.
2. **Gunakan level dengan purpose**:
   - `info` — event bisnis penting (request selesai, pembayaran berhasil)
   - `debug` — informasi debugging yang berguna di staging
   - `trace` — sangat detail, hanya di local development
3. **Wajib ada `msg`** — deskripsi singkat event, gunakan dot notation: `user.login.failed`.
4. **Sertakan context** — user ID, trace ID, endpoint, duration (ms).
5. **Error log wajib pakai `err`** — di pino: `logger.error({ err, msg: "..." })`; di structlog: `logger.error("...", exc_info=True)`.
6. **Gunakan child logger per request** — jadi semua log dalam satu request punya traceId yang sama.
