# logging_setup.py — Structured JSON logging untuk Python service
#
# Cara pakai:
#   from logging_setup import get_logger, setup_logging
#
#   setup_logging()              # panggil sekali di awal application
#   log = get_logger("my_module")
#   log.info("request.received", user_id=42, trace_id="abc-123")
#
# Environment variables (otomatis dibaca):
#   LOG_LEVEL    — trace|debug|info|warn|error|fatal (default: info)
#   SERVICE_NAME — ditambahkan ke setiap log line
#   NODE_ENV     — jika "development" gunakan pretty-print

import contextvars
import logging
import os
import sys
from typing import Any

try:
    import structlog
except ImportError:  # pragma: no cover
    structlog = None  # type: ignore[assignment]

# Context vars yang akan di-merge ke setiap log line
trace_ctx = contextvars.ContextVar("trace_ctx", default={})

# ---------------------------------------------------------------------------
# Setup sekali di awal application
# ---------------------------------------------------------------------------
def setup_logging() -> None:
    """Konfigurasi structlog + stdlib logging untuk output JSON terstruktur."""
    _configure_structlog()
    _configure_stdlib_integration()


def _configure_structlog() -> None:
    level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_str, logging.INFO)

    # Pilih renderer: pretty di development, JSON di production
    if os.getenv("NODE_ENV") == "development":
        renderer = structlog.dev.ConsoleRenderer() if structlog else None
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.UnicodeDecoder(),
            _add_service_name,
            renderer or structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _add_service_name(logger: Any, method_name: str, event_dict: dict) -> dict:
    """Tambah SERVICE_NAME ke setiap log line."""
    event_dict.setdefault("service", os.getenv("SERVICE_NAME", "python-service"))
    return event_dict


def _configure_stdlib_integration() -> None:
    """Integrasi dengan stdlib logging supaya library pihak ketiga juga
    keluarkan JSON (bukan plain text)."""
    handler = _JsonHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    root.setLevel(getattr(logging, level_str, logging.INFO))


# ---------------------------------------------------------------------------
# JSON Formatter & Handler (fallback bila structlog tidak terinstall)
# ---------------------------------------------------------------------------
class _JsonFormatter(logging.Formatter):
    """Formatter sederhana yang outputnya JSON satu baris."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "service": os.getenv("SERVICE_NAME", "python-service"),
            "event": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.name:
            payload["logger"] = record.name
        return _to_json(payload)


class _JsonHandler(logging.StreamHandler):
    def emit(self, record: logging.LogRecord) -> None:
        self.stream.write(self.format(record) + "\n")
        self.flush()


def _to_json(obj: Any) -> str:
    """Serialize ke JSON. Fallback ke str() bila orjson tidak ada."""
    try:
        import orjson
        return orjson.dumps(obj, option=orjson.OPT_APPEND_NEWLINE | orjson.OPT_SERIALIZE_NUMBERS).decode()
    except ImportError:
        import json
        return json.dumps(obj, default=str)


# ---------------------------------------------------------------------------
# Helper API
# ---------------------------------------------------------------------------
def get_logger(name: str | None = None):
    """Ambil logger terstruktur. panggil setelah setup_logging()."""
    if structlog:
        return structlog.get_logger(name)
    # Fallback: stdlib logger biasa
    return logging.getLogger(name)


def bind_trace(trace_id: str, **extra: Any) -> None:
    """Simpan context (trace_id + metadata lain) ke context vars.
    Dipanggil sekali per request; semua log setelahnya akan inherit context."""
    token = trace_ctx.set({"trace_id": trace_id, **extra})
    # Simpan token biar bisa di-reset nanti jika perlu
    # (di concrete app, simpan di request context / async-local storage)
    globals()["_trace_token"] = token


def clear_trace() -> None:
    """Clear context di akhir request."""
    token = globals().get("_trace_token")
    if token:
        trace_ctx.reset(token)


# ---------------------------------------------------------------------------
# Demo — jalankan file ini untuk melihat output
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    setup_logging()
    log = get_logger("demo")

    log.trace("ini trace — biasanya tidak muncul kecuali LOG_LEVEL=trace")
    log.debug("ini debug — muncul kalau LOG_LEVEL=debug")
    log.info("hello from python service", user_id=42, trace_id="abc-123")
    log.warn("ini warning")
    log.error("ini error", code=500)

    # Contoh simulasi context per-request
    bind_trace("req-001", path="/api/users", method="GET")
    log.info("request.received")
    clear_trace()
