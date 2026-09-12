#!/usr/bin/env python3
"""main.py — Entry point Python service.

Jalankan dengan:
    python services/python/src/main.py

Service ini memakai structured JSON logging (structlog) dan memvalidasi
environment variable sebelum mulai.
"""

import os
import sys

# Validasi env sebelum sembarang logic jalan
sys.path.insert(0, os.path.dirname(__file__))
from validate_env import validate_env

errors = validate_env()
if errors:
    for e in errors:
        print(e, file=sys.stderr)
    sys.exit(1)

# Setup structured logging
from logging_setup import setup_logging, get_logger, bind_trace

setup_logging()
log = get_logger("main")

service_name = os.environ.get("SERVICE_NAME", "python-service")
port = int(os.environ.get("PYTHON_SERVICE_PORT", "8000"))

log.info(
    "python.service.starting",
    service=service_name,
    port=port,
    node_env=os.environ.get("NODE_ENV", "development"),
)

# NOTE: Ganti dengan FastAPI/Flask/Gunicorn integration saat development lanjutan.
# Contoh dengan FastAPI:
#
#   from fastapi import FastAPI, Request
#   import uuid
#
#   app = FastAPI()
#
#   @app.middleware("http")
#   async def tracing_middleware(request: Request, call_next):
#       trace_id = request.headers.get("x-trace-id", str(uuid.uuid4()))
#       bind_trace(trace_id, path=request.url.path, method=request.method)
#       response = await call_next(request)
#       response.headers["x-trace-id"] = trace_id
#       log.info("request.completed", status=response.status_code)
#       clear_trace()
#       return response
#
#   if __name__ == "__main__":
#       import uvicorn
#       uvicorn.run(app, host=os.environ.get("PYTHON_SERVICE_HOST", "0.0.0.0"), port=port)

log.info("python.service.ready", port=port)
print(f"✅ Python service siap di port {port} (LOG_LEVEL={os.environ.get('LOG_LEVEL', 'INFO')})")
