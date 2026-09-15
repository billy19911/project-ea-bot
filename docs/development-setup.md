# Development Setup Guide

Panduan lengkap untuk men-setup lingkungan development Project EA Bot secara manual.

> **Catatan:** Environment saat ini TIDAK memiliki Docker. Semua dependency harus diinstal dan dikonfigurasi secara manual. Lihat [CONSTRAINTS.md](../CONSTRAINTS.md) untuk daftar kendala lengkap.

---

## Daftar Isi

1. [Node.js](#nodejs)
2. [Python](#python)
3. [PostgreSQL](#postgresql)
4. [Redis](#redis)
5. [Verifikasi Installasi](#verifikasi-installasi)
6. [Troubleshooting](#troubleshooting)

---

## Node.js

### Mengapa bukan cukup npm saja?

Environment ini memiliki `npm` (v10.9.8) tetapi **tidak memiliki Node.js binary** (`node.exe`) di PATH. Ini adalah kondisi rusak — `npm` adalah package manager yang bergantung pada `node` untuk menjalankan script. Tanpa `node` binary:

- `npm install` mungkin bisa berjalan (karena npm bundled), tetapi
- `npm run build`, `npm test`, `node server.js`, dan semua script yang memanggil `node` **akan gagal**.

### Install Node.js di Windows

#### Opsi A: Binary (.zip) — Direkomendasikan untuk environment terkendala

1. Unduh Node.js binary dari [nodejs.org/dist](https://nodejs.org/dist/):
   - Pilih versi LTS terbaru (mis. `v20.17.0`)
   - Download file: `node-v20.17.0-win-x64.zip`

2. Ekstrak ke folder permanen, contoh:
   ```
   C:\Program Files\nodejs\
   ```
   atau
   ```
   %LOCALAPPDATA%\nodejs\
   ```

3. Tambahkan ke `PATH`:
   - Buka **System Properties** → **Environment Variables**
   - Edit `Path` (User atau System)
   - Tambahkan path ke folder `bin`: `C:\Program Files\nodejs\`
   - Klik OK dan **restart terminal/VS Code** agar perubahan PATH aktif

4. Verifikasi:
   ```powershell
   node --version
   npm --version
   ```

#### Opsi B: Scoop (Jika Scoop tersedia)

```powershell
scoop install nodejs-lts
```

#### Opsi C: winget

```powershell
winget install OpenJS.NodeJS.LTS
```

### Verifikasi Node.js

```bash
node --version    # Harusnya mengeluarkan v20.x.x
npm --version     # Harusnya mengeluarkan 10.x.x
node -e "console.log('Node berjalan')"
```

---

## Python

### Status

Python 3.11.16 sudah tersedia di environment ini.

### Verifikasi

```bash
python --version
# atau
py --version
```

### Setup Virtual Environment (Disesuaikan)

```bash
# Buat virtual environment
python -m venv .venv

# Aktifkan (Windows)
.venv\Scripts\activate

# Aktifkan (Linux/macOS/WSL)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Install Python (Jika belum ada)

1. Unduh dari [python.org/downloads](https://www.python.org/downloads/)
2. Pastikan centang **"Add Python to PATH"** saat instalasi
3. Verifikasi: `python --version`

---

## PostgreSQL

### Install di Windows

#### Opsi A: Installer Resmi

1. Unduh dari [postgresql.org/download/windows](https://www.postgresql.org/download/windows/)
2. Jalankan installer — pilih komponen: PostgreSQL Server, pgAdmin 4, Command Line Tools
3. Catat password yang dibuat untuk user `postgres`
4. Biarkan port default (5432) dan locale default

#### Opsi B: Scoop

```powershell
scoop install postgresql
```

#### Opsi C: Chocolatey

```powershell
choco install postgresql
```

### Setup Awal

Setelah instalasi, buat database dan user untuk project:

```bash
# Buka psql sebagai postgres user
psql -U postgres

# Di dalam psql:
CREATE DATABASE ea_bot;
CREATE USER ea_bot_user WITH PASSWORD 'your_password_here';
GRANT ALL PRIVILEGES ON DATABASE ea_bot TO ea_bot_user;
\q
```

### Verifikasi

```bash
psql --version
# Tes koneksi
psql -U ea_bot_user -d ea_bot -h localhost
```

---

## Redis

### Install di Windows

#### Opsi A: Redis untuk Windows (Microsoft Archive)

1. Unduh dari [MicrosoftArchive/redis releases](https://github.com/MicrosoftArchive/redis/releases)
2. Pilih file: `Redis-x64-3.0.504.zip` (versi stabil untuk Windows)
3. Ekstrak ke folder, contoh: `C:\Redis`
4. Tambahkan ke PATH atau jalankan dari folder tersebut

#### Opsi B: WSL2 (Direkomendasikan jika menggunakan WSL)

```bash
wsl sudo apt update
wsl sudo apt install redis-server
wsl sudo service redis-server start
```

#### Opsi C: Docker (Jika suatu hari Docker tersedia)

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

### Jalankan Redis Server

```powershell
# Dari folder instalasi
C:\Redis\redis-server.exe

# Atau sebagai Windows Service (jika diinstal sebagai service)
redis-server --service-start
```

### Verifikasi

```bash
redis-cli ping
# Harusnya mengembalikan: PONG
```

---

## Verifikasi Installasi

Setelah semua dependency terinstal, jalankan verifikasi:

```powershell
# Cek semua dependency
node --version
npm --version
python --version
psql --version
redis-cli ping
git --version
```

Semua perintah di atas harus berhasil sebelum development bisa dimulai.

---

## Troubleshooting

### Node.js: "node is not recognized"

- Pastikan Node.js terinstal (bukan hanya npm)
- Cek PATH: `echo %PATH%` di PowerShell atau `echo $PATH` di Git Bash
- Pastikan folder yang berisi `node.exe` ada di PATH
- Restart terminal/VS Code setelah mengubah PATH

### PostgreSQL: "psql: fatal: database does not exist"

- Pastikan PostgreSQL server berjalan
- Cek service: `sc query postgresql-x64-15` (nama service mungkin berbeda)
- Mulai ulang service PostgreSQL

### Redis: "Could not connect to Redis"

- Pastikan redis-server berjalan di tab terminal terpisah
- Cek apakah port 6379 sudah dipakai aplikasi lain
- Jalankan `redis-cli ping` untuk verifikasi

### Python: Permission Denied saat install package

- Jalankan terminal sebagai Administrator
- Atau gunakan virtual environment (direkomendasikan)

---

## Konfigurasi Environment Variables

Setelah semua dependency terinstal, buat file `.env` berdasarkan `.env.example`:

```bash
cp .env.example .env
```

Edit `.env` dengan nilai yang sesuai:
- `DATABASE_URL` — Koneksi string PostgreSQL
- `REDIS_URL` — URL Redis (biasanya `redis://localhost:6379`)
- `SECRET_KEY` — Kunci rahasia untuk session/auth

---

## Dev auth token

API menerapkan autentikasi pada semua route kecuali allowlist publik: `/health`, `/metrics`, `/auth/token` (PRD_V2 §28). Untuk memakai dashboard web saat development:

1. Jalankan API dengan token minting aktif:
   ```bash
   DEV_AUTH_ENABLED=true npm run dev
   ```

2. Mint sebuah token (development-only):
   ```bash
   curl -s -X POST http://localhost:3001/auth/token \
     -H 'Content-Type: application/json' \
     -d '{"userId":"admin","role":"admin"}'
   ```

3. Simpan token di browser agar halaman dashboard mengirim header `Authorization: Bearer <token>`:
   ```js
   localStorage.setItem('ea-bot-token', '<token>')
   ```

Helper `apps/web/lib/api.ts` (`apiFetch`) membaca key `ea-bot-token` dan menambahkan header `Authorization` serta `X-Trace-Id` ke setiap request.

---
