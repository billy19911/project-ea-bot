<!-- SPDX-License-Identifier: CC0-1.0 -->

# XynnBot — Autonomous Multi-Agent Trading & Research Platform

<div align="center">

[![Status](https://img.shields.io/badge/status-architecture_foundation-blue.svg)](#status)
[![Platform](https://img.shields.io/badge/platform-MT5-purple.svg)](#platform)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](#license)

</div>

---

**XynnBot** adalah platform *autonomous trading* yang menggabungkan **deterministic engines** (kode yang enforce safety) dengan **multi-agent AI** (Supervisor + specialist agents) untuk menganalisis pasar, mengelola risiko, dan mengeksekusi trade melalui MetaTrader 5.

Inti sistem: **AI memutuskan dalam batas. Kode menegakkan batas.**

```
AI  →  Trade Proposal  →  Deterministic Validation  →  Risk Gate  →  Execution
```

AI tidak pernah langsung kirim order ke MT5. Setiap keputusan melewati validation layer yang deterministic.

---

## Arsitektur

### Cara Kerja Sistem

```
┌─────────────────────────────────────────────────────────────┐
│                      Kontrol Layer                          │
│  Dashboard (Next.js) │ API (Node.js/TypeScript)            │
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
│ Market       │    │ Risk Department  │    │ Research     │
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
│   ├── web/          # Next.js dashboard
│   └── api/          # Node.js API (Express)
├── services/
│   └── python/       # FastAPI service (agents, MT5 connector, risk)
├── packages/
│   ├── eslint-config/# Shared lint config
│   └── shared/       # TypeScript types & utilities
├── infrastructure/
│   ├── docker/       # Docker compose & Dockerfiles
│   └── db/          # PostgreSQL init, backup, restore
├── .github/
│   └── workflows/   # CI/CD
├── docs/
│   ├── logging.md    # Panduan structured logging
│   └── development-setup.md
├── scripts/
├── config-validate.js
├── .env.example
├── README.md         # Ini
├── CHANGELOG.md
├── CONSTRAINTS.md
└── PRD_V1_Autonomous_Multi_Agent_Trading_Research_Platform.md
```

---

## Tech Stack

| Layer              | Technology                        |
|--------------------|-----------------------------------|
| Frontend           | React + Next.js                   |
| Backend API        | Node.js / TypeScript / Express    |
| AI Service         | Python / FastAPI                  |
| LLM Gateway        | 9Router (dengan fallback)         |
| Database           | PostgreSQL                        |
| Cache / Queue      | Redis                             |
| Execution          | MetaTrader 5                      |
| Container          | Docker (pilihan)                  |

---

## Status & Roadmap

### Phase 0 — Architecture Foundation ✅ *(Selesai)*
- [x] Monorepo setup (npm workspaces, TypeScript, ESLint, Prettier)
- [x] Python service foundation (FastAPI, pydantic-settings, SQLAlchemy)
- [x] Database layer (Prisma + SQLAlchemy, docker-compose blueprint)
- [x] Logging & config system (structured logging, env validation)
- [x] Development environment docs & CI/CD blueprint
- [x] CHANGELOG, CONSTRAINTS.md, PRD V1

### Phase 1 — MT5 Connector *(Berikutnya)*
- MT5 connection & recovery
- Account info, symbol, tick, OHLC
- Positions & orders (paper/demo)

### Phase 2–6 *(Perencanaan)*
- Deterministic Trading Engine
- Multi-Agent System (Supervisor + specialist agents)
- Risk Engine & Risk Gate
- Execution Engine
- Dashboard & Observability

---

## Safety First

Sistem ini punya safety mechanism yang tegas:

| Mode          | Deskripsi                                      |
|---------------|------------------------------------------------|
| `OFFLINE`     | Tidak ada interaksi AI                         |
| `BACKTEST`    | Simulasi historis                              |
| `PAPER`       | Akun demo tanpa uang nyata                     |
| `DEMO`        | Akun broker demo                               |
| `LIVE`        | Trading real — butuh explicit enable           |
| `EMERGENCY_STOP` | Lockdown sistem                              |

Hard risk limits (drawdown, daily loss, exposure, dll) **tidak boleh** diubah oleh LLM. Risk Gate selalu dipanggil sebelum eksekusi.

---

## Getting Started

### Prasyarat

- Node.js (binary, bukan cuma npm)
- Python 3.11+
- PostgreSQL (local/remote)
- Redis (local/remote)

### Setup Singkat

```bash
# Install dependencies
cd apps/api && npm install && cd ../web && npm install && cd ../../packages/shared && npm install && cd ../..

# Install Python dependencies
cd services/python
.venv/Scripts/activate
pip install -r requirements.txt

# Konfigurasi environment
cp .env.example .env
# Edit .env sesuai environment lokal

# Validasi environment
node config-validate.js

# Jalankan API (Node.js)
cd apps/api
node src/index.ts

# Jalankan Python service (terminal lain)
cd ../../services/python
.venv/Scripts/activate
uvicorn src.main:app --reload
```

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

## Developer

- **Billy19911** — [GitHub](https://github.com/billy19911)

---

<div align="center">

_Dokumen ini adalah acuan utama fase 0. Untuk desain sistem lengkap, lihat PRD V1._

</div>
