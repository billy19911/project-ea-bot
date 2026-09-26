<!-- SPDX-License-Identifier: CC0-1.0 -->

<div align="center">

# XynnBot

### Autonomous Multi-Agent Trading &amp; Research Platform

[![Status](https://img.shields.io/badge/status-in_development-orange.svg)](#status)
[![Platform](https://img.shields.io/badge/platform-MT5-6f42c1.svg)](#tech-stack)
[![Node](https://img.shields.io/badge/node-%3E%3D18.0.0-339933.svg)](#prasyarat)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB.svg)](#prasyarat)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](#lisensi)

</div>

---

## Tentang

**XynnBot** adalah platform *autonomous trading* yang menggabungkan **deterministic engines** (kode yang menegakkan safety) dengan **multi-agent AI** (Supervisor + specialist agents) untuk menganalisis pasar, mengelola risiko, dan mengeksekusi trade melalui MetaTrader 5.

> **Inti filosofi:** AI memutuskan dalam batas. Kode menegakkan batas.

```
AI  →  Trade Proposal  →  Deterministic Validation  →  Risk Gate  →  Execution  →  MT5
```

AI **tidak pernah** langsung mengirim order ke MT5. Setiap keputusan melewati validation layer yang deterministic dan Risk Gate berbasis hard limit.

---

## Arsitektur

### Alur Sistem

```
┌─────────────────────────────────────────────────────────────┐
│                      Kontrol Layer                          │
│  Dashboard (Next.js) │ API (Node.js / TypeScript)           │
└────────────────────────────┬────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        Event Manager   Agent Router   State Manager
              │              │              │
              └──────────────┼──────────────┘
                             ▼
                    ┌───────────────────┐
                    │   SUPERVISOR      │
                    │   AGENT           │
                    └─────────┬─────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────┐    ┌──────────────────┐    ┌──────────────┐
│ Market       │    │ Risk Department  │    │ Research      │
│ Intelligence │    │ (Deterministic)  │    │ Department   │
└──────┬───────┘    └────────┬─────────┘    └──────┬───────┘
       │                     │                     │
       └─────────────────────┼─────────────────────┘
                             ▼
                    ┌───────────────────┐
                    │   RISK GATE       │
                    │   (HARD LIMITS)   │
                    └─────────┬─────────┘
                              ▼
                    ┌───────────────────┐
                    │   EXECUTION       │
                    │   ENGINE          │
                    └─────────┬─────────┘
                              ▼
                          MT5
```

### Struktur Monorepo

```
project-ea-bot/
├── apps/
│   ├── web/                    # Next.js dashboard
│   │   └── app/                # ai-control, strategy, observability pages
│   └── api/                    # Node.js API (Express + Prisma)
│       ├── src/
│       ├── prisma/
│       └── test/
├── services/
│   └── python/                 # FastAPI service
│       └── src/
│           ├── agents/         # Supervisor, analysts, synthesis
│           ├── trading/        # Event engine, market regime, indicators
│           ├── risk/            # Risk engine, money management, risk gate
│           ├── execution/      # Execution engine
│           ├── mt5/             # MT5 connector & connection manager
│           ├── llm/             # 9Router LLM gateway
│           ├── monitoring/      # Position monitor
│           ├── research/        # Research engine
│           ├── paper/           # Paper trading simulation
│           ├── demo/            # Demo trading & stability
│           ├── memory/          # Trade memory
│           ├── review/          # Trade review
│           └── live_readiness/  # Live readiness evaluator & gate
├── packages/
│   ├── eslint-config/          # Shared lint config
│   └── shared/                 # TypeScript types & utilities
│       └── src/
├── infrastructure/
│   ├── docker/                 # docker-compose, Dockerfiles
│   └── db/                     # PostgreSQL init, backup, restore
├── .github/
│   └── workflows/              # CI/CD
├── docs/
│   ├── logging.md              # Panduan structured logging
│   └── development-setup.md    # Panduan install manual (Windows)
├── scripts/
│   └── setup.js
├── telegram/                   # Telegram bot integration
├── config-validate.js
├── .env.example
├── CHANGELOG.md
├── CONSTRAINTS.md
├── PRD_V1_Autonomous_Multi_Agent_Trading_Research_Platform.md
└── README.md                   # ← Anda di sini
```

---

## Tech Stack

| Layer              | Technology                          |
|--------------------|-------------------------------------|
| Frontend           | React + Next.js                     |
| Backend API        | Node.js / TypeScript / Express      |
| AI Service         | Python / FastAPI                    |
| LLM Gateway        | 9Router (dengan fallback)           |
| Database           | PostgreSQL + Prisma (Node) / SQLAlchemy (Python) |
| Cache / Queue      | Redis                               |
| Execution          | MetaTrader 5                         |
| Container          | Docker (opsional)                   |

---

## Status

Platform sedang dalam tahap *pre-release*: core trading, AI, risk, dan observability sudah terimplementasi dan teruji. Lihat [`CHANGELOG.md`](./CHANGELOG.md) untuk riwayat perubahan dan [`ARCHITECTURE_MAP.md`](./ARCHITECTURE_MAP.md) untuk status per-EPIC.

---

## Safety First

Sistem ini punya safety mechanism yang tegas. AI **tidak pernah** diberi akses langsung ke eksekusi MT5.

| Mode              | Deskripsi                                |
|-------------------|------------------------------------------|
| `OFFLINE`         | Tidak ada interaksi AI                   |
| `BACKTEST`        | Simulasi historis                        |
| `PAPER`           | Akun demo tanpa uang nyata               |
| `DEMO`            | Akun broker demo                         |
| `LIVE`            | Trading real — butuh explicit enable     |
| `EMERGENCY_STOP`  | Lockdown sistem                          |

Hard risk limits (drawdown, daily loss, exposure, dll) **tidak boleh** diubah oleh LLM. Risk Gate selalu dipanggil sebelum eksekusi.

---

## Getting Started

### Prasyarat

- **Node.js** ≥ 18.0.0 (binary, bukan cuma npm)
- **Python** 3.11+
- **PostgreSQL** (local/remote)
- **Redis** (local/remote)
- **MetaTrader 5** terminal (untuk eksekusi)

### Setup Singkat

```bash
# 1. Clone repository
git clone <repo-url> project-ea-bot
cd project-ea-bot

# 2. Install Node.js dependencies (monorepo)
npm install

# 3. Install Python dependencies
cd services/python
python -m venv .venv
.venv/Scripts/activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt
cd ../..

# 4. Konfigurasi environment
cp .env.example .env
# Edit .env sesuai environment lokal

# 5. Validasi environment
node config-validate.js

# 6. Jalankan API (Node.js)
cd apps/api
npm run dev
```

Terminal kedua — jalankan Python service:

```bash
cd services/python
.venv/Scripts/activate          # Windows
# source .venv/bin/activate     # Linux/macOS
uvicorn src.main:app --reload
```

Terminal ketiga — jalankan dashboard:

```bash
cd apps/web
npm run dev
```

## Cara Menjalankan

### Cara cepat — satu klik (Windows)

```
start.bat
```

Satu perintah itu menyalakan **ketiga** service (Python API :8787, Node API :3789,
Web :4321), menunggu sampai sehat, lalu membuka dashboard di browser. Skrip juga
otomatis:

- memuat konfigurasi lokal dari `.env.runtime` (dibuat otomatis bila belum ada),
- membuat `JWT_SECRET` acak sekali dan menyimpannya ke `.env.runtime` (gitignored),
- melewati service yang **sudah berjalan** (aman dipanggil berulang),
- menulis log ke `logs/*.log`.

| Perintah | Fungsi |
|---|---|
| `start.bat` / `npm run up` | nyalakan semua service + buka dashboard |
| `start.bat -NoBrowser` | sama, tanpa membuka browser |
| `stop.bat` / `npm run down` | hentikan semua service (hanya port dari `.env.runtime`) |
| `status.bat` / `npm run status` | cek kesehatan ketiga service |
| `token.bat` / `npm run token` | buat dev token & copy ke clipboard (isi `localStorage`) |

> Script hanya menyentuh port dari `.env.runtime` (default 8787/3789/4321) — **tidak
> pernah** menyentuh terminal MT5 yang sedang berjalan.

### Cara manual (3 terminal)

```bash
# Terminal 1 — Python service (FastAPI) :8787
cd services/python
.venv/Scripts/activate            # Windows
# source .venv/bin/activate       # Linux/macOS
NINE_ROUTER_BASE_URL=http://127.0.0.1:20128/v1 uvicorn src.main:app --host 127.0.0.1 --port 8787

# Terminal 2 — Node API :3789
cd apps/api
npm run build                     # sekali saja / setelah ubah kode
DEV_AUTH_ENABLED=true PORT=3789 PYTHON_SERVICE_URL=http://127.0.0.1:8787 node dist/index.js

# Terminal 3 — Web dashboard :4321
cd apps/web
npm run build                     # sekali saja
npx next start -p 4321
# buka http://127.0.0.1:4321
```

### Dev auth token

Dengan `DEV_AUTH_ENABLED=true`, panggil `POST /auth/token` dengan body `{"userId":"admin","role":"admin"}`, lalu simpan token di browser:

```js
localStorage.setItem('ea-bot-token', '<token>')
```

| Service | Port | Health check |
|---|---:|---|
| Python FastAPI | 8787 | `GET /health` |
| Node API | 3789 | `GET /health` |
| Web (Next.js) | 4321 | buka `/` |

### Mode data live MT5 (read-only)

Secara default bot berjalan dalam **paper mode** (data simulasi). Untuk membaca
data pasar & posisi **nyata** dari terminal MT5 yang sedang berjalan:

```bash
# 1. Install paket resmi (Windows only)
cd services/python && .venv/Scripts/pip install MetaTrader5

# 2. Jalankan Python service dengan mode live read-only
MT5_LIVE_DATA=true uvicorn src.main:app --host 127.0.0.1 --port 8787
```

Yang terjadi saat `MT5_LIVE_DATA=true`:

- Connector attach ke terminal MT5 yang sudah login (`mt5.initialize()`, tanpa kredensial).
- Endpoint `/mt5/mode` melaporkan `{"live_data": true, "execution": "disabled (read-only)"}`.
- Dashboard menampilkan badge **LIVE DATA · READ-ONLY** dan data akun/posisi nyata.
- **Order eksekusi DIBLOKIR** di connector dan execution engine — mode ini hanya untuk membaca.
- Tanpa variabel ini (default), semua tetap paper mode dan aman di CI Linux (paket MT5 di-skip).

### Multi-terminal MT5 (auto-detect + arm/disarm)

Satu proses Python hanya bisa attach ke **satu** terminal MT5 (batasan paket
`MetaTrader5`). Untuk mengontrol beberapa terminal (mis. A/B/C) sekaligus memilih
**satu** yang boleh mengeksekusi order:

1. Daftarkan terminal di `services/python/mt5_terminals.json` (atau file yang
   ditunjuk `MT5_TERMINALS_FILE`). Path wajib menunjuk ke **`terminal64.exe`**,
   bukan folder:

   ```json
   {
     "terminals": [
       { "id": "vito2", "label": "VITO 2", "path": "E:\\MT5 XYNN EA\\MetaTrader 5 VITO 2\\terminal64.exe", "execution": false }
     ]
   }
   ```

   `"execution": true` hanya menandai terminal sebagai **kandidat** penerima order
   nyata — eksekusi tetap harus di-arm eksplisit dan selalu mulai OFF.

2. Endpoint multi-terminal:

   | Endpoint | Fungsi |
   |---|---|
   | `GET /mt5/terminals` | Daftar terminal + status `running`/`attached`/`selected` (auto-detect lewat `psutil`) |
   | `POST /mt5/terminals/select` | Pilih terminal aktif (`{"terminal_id": "vito2"}`) — re-attach fail-closed: arm dimatikan lebih dulu |
   | `POST /mt5/terminals/arm` | Arm/disarm eksekusi (`{"armed": true}`) — hanya untuk terminal dengan `execution: true` |

   Dashboard (tab **Trading** → panel **MT5 Terminals**) menyediakan pemilihan
   terminal, tombol arm/disarm, dan menampilkan mana yang sedang ter-attach.

3. **Saklar arm default OFF** dan bisa dimatikan kapan saja. Arm hanya membuka
   jalur eksekusi engine; selama tidak ada sinyal yang lolos validation + Risk
   Gate, tidak ada order yang dikirim. Konfigurasi dibaca ulang setiap request —
   tidak perlu restart server.

---

## Dokumentasi

| Dokumen | Deskripsi |
|---------|-----------|
| [`PRD_V1_...md`](./PRD_V1_Autonomous_Multi_Agent_Trading_Research_Platform.md) | Spesifikasi arsitektur lengkap (PRD V1) |
| [`docs/logging.md`](./docs/logging.md) | Panduan structured logging (pino / structlog) |
| [`docs/development-setup.md`](./docs/development-setup.md) | Panduan install dependensi manual (Windows) |
| [`CHANGELOG.md`](./CHANGELOG.md) | Riwayat versi & perubahan |
| [`CONSTRAINTS.md`](./CONSTRAINTS.md) | Kendala environment & rekomendasi solusi |

---

## Arsip: EPIC 00–30

Lengkap EPIC 00–30 tercakup. Lihat [`ARCHITECTURE_MAP.md`](./ARCHITECTURE_MAP.md) untuk checklist dan diagram.

---

## Lisensi

Distribusi under **MIT License**. Lihat detail di header setiap file (`SPDX-License-Identifier`).

---

## Developer

- **Billy19911** — [GitHub](https://github.com/billy19911)

---

<div align="center">

_Dokumen ini adalah acuan utama project. Untuk desain sistem lengkap, lihat **PRD V1**._

</div>
