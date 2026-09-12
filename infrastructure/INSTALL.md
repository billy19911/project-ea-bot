# =============================================================================
# Project EA Bot — Database Installation Guide (No Docker)
# =============================================================================
# Environment ini tidak memiliki Docker. Instal PostgreSQL dan Redis secara
# manual menggunakan langkah di bawah ini.
#
# Target: Windows 11 (development machine)
# =============================================================================

# ---------------------------------------------------------------------------
# 1. PostgreSQL
# ---------------------------------------------------------------------------
# Opsi A: PostgreSQL Installer (recommended untuk Windows)
#   Download: https://www.postgresql.org/download/windows/
#   Pilih PostgreSQL 16.
#   Saat instalasi, atur:
#     - Port: 5432
#     - Password user 'postgres' dan user tambahan 'ea_bot'
#     - Buat database: ea_bot
#
# Opsi B: WinGet (Windows Package Manager)
#   > winget install --id PostgreSQL.PostgreSQL
#
# Setelah terinstall, buat user dan database:
#   > psql -U postgres
#   CREATE USER ea_bot WITH PASSWORD 'changeme_dev';
#   CREATE DATABASE ea_bot OWNER ea_bot;
#   GRANT ALL PRIVILEGES ON DATABASE ea_bot TO ea_bot;
#
# ---------------------------------------------------------------------------
# 2. Redis
# ---------------------------------------------------------------------------
# Opsi A: Redis for Windows (MSOpenTech / Microsoft archive — untuk dev)
#   Download: https://github.com/microsoft/Windows-Redis/releases
#   Install dan jalankan sebagai Windows Service.
#
# Opsi B: Chocolatey
#   > choco install redis-64
#
# Opsi C: Build dari source (Linux WSL2 disarankan untuk production-like)
#   > wget https://download.redis.io/redis-stable.tar.gz
#   > tar xzf redis-stable.tar.gz
#   > cd redis-stable
#   > make
#   > src/redis-server
#
# Setelah Redis berjalan, sesuaikan redis.conf jika perlu password:
#   requirepass your_redis_password
#
# ---------------------------------------------------------------------------
# 3. Verifikasi koneksi
# ---------------------------------------------------------------------------
# PostgreSQL:
#   > psql -U ea_bot -d ea_bot -h localhost -p 5432
#
# Redis:
#   > redis-cli ping
#   (harus return PONG)
#
# ---------------------------------------------------------------------------
# 4. Set environment variables
# ---------------------------------------------------------------------------
# Salin .env.example menjadi .env dan sesuaikan nilai HOST/PORT jika berbeda.
# =============================================================================
