#!/usr/bin/env python3
"""validate_env.py — Validasi environment variable untuk Python service.

Dipanggil di awal startup. Mengecek semua variable wajib ada dan bernilai
valid. Keluarkan pesan error yang jelas jika ada yang hilang/salah.
Exit kode 1 jika validation gagal.

Cara pakai:
    python services/python/src/validate_env.py

atau dari root monorepo:
    python services/python/src/validate_env.py
"""

import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Schema: semua environment variable yang wajib/divalidasi
# ---------------------------------------------------------------------------
REQUIRED: dict[str, dict[str, Any]] = {
    # Application
    "SERVICE_NAME": {
        "required": True,
        "type": str,
        "description": "Nama service — muncul di semua log lines",
    },
    # Database
    "DB_HOST": {
        "required": True,
        "type": str,
        "description": "Hostname PostgreSQL server",
    },
    "DB_NAME": {
        "required": True,
        "type": str,
        "description": "Nama database",
    },
    "DB_USER": {
        "required": True,
        "type": str,
        "description": "Username database",
    },
    "DB_PASSWORD": {
        "required": True,
        "type": str,
        "description": "Password database",
    },
    "DB_PORT": {
        "required": False,
        "type": int,
        "default": 5432,
        "validate": lambda v: 0 < v < 65536,
        "description": "PostgreSQL port",
    },
    "DB_POOL_MIN": {
        "required": False,
        "type": int,
        "default": 2,
        "validate": lambda v: v >= 0,
        "description": "Minimum koneksi pool",
    },
    "DB_POOL_MAX": {
        "required": False,
        "type": int,
        "default": 10,
        "validate": lambda v: v > 0,
        "description": "Maksimum koneksi pool",
    },
    # Redis
    "REDIS_URL": {
        "required": False,
        "type": str,
        "default": "redis://localhost:6379",
        "validate": lambda v: v.startswith("redis://") or v.startswith("rediss://"),
        "description": "URL koneksi Redis",
    },
    # Auth
    "JWT_SECRET": {
        "required": True,
        "type": str,
        "description": "Secret key untuk JWT signing",
    },
    "JWT_EXPIRY": {
        "required": False,
        "type": str,
        "default": "24h",
    },
    # Logging
    "LOG_LEVEL": {
        "required": False,
        "type": str,
        "default": "INFO",
        "validate": lambda v: v.upper() in ("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL"),
        "description": "Level logging minimum",
    },
    "NODE_ENV": {
        "required": False,
        "type": str,
        "default": "development",
        "validate": lambda v: v in ("development", "production", "test", "staging"),
        "description": "Environment mode",
    },
    # Python service
    "PYTHON_SERVICE_HOST": {
        "required": False,
        "type": str,
        "default": "0.0.0.0",
    },
    "PYTHON_SERVICE_PORT": {
        "required": False,
        "type": int,
        "default": 8000,
        "validate": lambda v: 0 < v < 65536,
        "description": "Port Python service",
    },
    # Feature flags
    "ENABLE_TRACING": {
        "required": False,
        "type": str,
        "default": "false",
        "validate": lambda v: v.lower() in ("true", "false", "1", "0"),
        "description": "Aktifkan distributed tracing",
    },
}


def _parse_int(raw: str, default: int) -> int:
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def validate_env() -> list[str]:
    """Validasi semua environment variable.
    Return daftar error message (kosong = success)."""
    errors: list[str] = []
    env = os.environ

    for name, spec in REQUIRED.items():
        raw = env.get(name)

        # --- Variable wajib yang tidak ada ---
        if spec.get("required") and (raw is None or raw.strip() == ""):
            errors.append(f"❌ {name} wajib diisi (tidak ada di environment)")
            continue

        # --- Variable dengan default, kosong → pakai default ---
        if raw is None or raw.strip() == "":
            if "default" in spec:
                continue
            errors.append(f"❌ {name} tidak boleh kosong")
            continue

        # --- Type checking ---
        expected_type = spec.get("type", str)
        if expected_type is int:
            value = _parse_int(raw, spec.get("default", 0))
            if "validate" in spec and not spec["validate"](value):
                errors.append(f"❌ {name}={raw} tidak valid — {spec.get('description', name)}")
            continue

        # --- String validation ---
        if "validate" in spec and not spec["validate"](raw):
            errors.append(f"❌ {name}={raw} tidak valid — {spec.get('description', name)}")

    return errors


def main() -> None:
    print("🔍 Validasi environment variable Python service...\n")
    errors = validate_env()

    if errors:
        for err in errors:
            print(err)
        print("\n🛑 Startup dibatalkan. Perbaiki .env dan coba lagi.")
        sys.exit(1)

    # Ringkasan
    print("✅ Environment variable valid.\n")
    print(f"   SERVICE_NAME    = {os.environ.get('SERVICE_NAME', 'api')}")
    print(f"   LOG_LEVEL       = {os.environ.get('LOG_LEVEL', 'INFO')}")
    print(f"   NODE_ENV        = {os.environ.get('NODE_ENV', 'development')}")
    print(f"   DB_HOST         = {os.environ.get('DB_HOST')}")
    print(f"   DB_NAME         = {os.environ.get('DB_NAME')}")
    print(f"   JWT_SECRET      = {'✓ set' if os.environ.get('JWT_SECRET') else '✗ MISSING'}")
    print(f"   REDIS_URL       = {os.environ.get('REDIS_URL', 'redis://localhost:6379')}")
    print(f"   PYTHON_SERVICE_PORT = {os.environ.get('PYTHON_SERVICE_PORT', '8000')}")


if __name__ == "__main__":
    main()
