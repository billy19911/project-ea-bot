<!-- SPDX-License-Identifier: CC0-1.0 -->

<div align="center">

# XynnBot

### Autonomous Multi-Agent Trading &amp; Research Platform

[![Status](https://img.shields.io/badge/status-in_development-orange.svg)](#status--roadmap)
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

## Status &amp; Roadmap

### Phase 0 — Architecture Foundation ✅
- [x] Monorepo setup (npm workspaces, TypeScript, ESLint, Prettier)
- [x] Python service foundation (FastAPI, pydantic-settings, SQLAlchemy)
- [x] Database layer (Prisma + SQLAlchemy, docker-compose blueprint)
- [x] Logging & config system (structured logging, env validation)
- [x] Development environment docs & CI/CD blueprint

### Phase 1–6 — Trading Core ✅
- [x] MT5 connector (connection manager, data models, paper trading API)
- [x] Deterministic Trading Engine
- [x] Event Engine (class-based EventDetector, priority, dedup, queue, history)
- [x] Market Regime Engine

### Phase 7–13 — AI & Risk ✅
- [x] Supervisor Agent (routing policy, concurrency, token budget)
- [x] 9Router LLM Layer
- [x] Market Agents (Structure, Momentum, Volatility, News)
- [x] Risk Engine (account / position / portfolio risk)
- [x] Money Management
- [x] Supervisor Synthesis
- [x] Deterministic Risk Gate (hard limits)

### Phase 14–17 — Execution & Monitoring ✅
- [x] Execution Engine (validation, sending, confirmation, retry, dedup)
- [x] Position Monitor
- [x] Trade Memory
- [x] Trade Review

### Phase 18–20 — Research & Simulation ✅
- [x] Research Engine
- [x] Paper Trading
- [x] Demo Trading & stability validation

### Phase 21–26 — Frontend ✅
- [x] Dashboard Foundation
- [x] Trading Dashboard
- [x] AI Control Center
- [x] Strategy Center
- [x] Research Center
- [x] System Settings

### Phase 27 — Observability ✅
- [x] Metrics, alerts, dan observability dashboard

### Phase 28–30 — Security & Live Readiness ✅
- [x] Security hardening
- [x] Paper & demo validation
- [x] Live readiness checklist

### Berikutnya
- Live trading enablement (explicit `LIVE` mode activation)
- Hardening & end-to-end integration testing
- Deployment ke staging / production

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

Lihat [`ARCHITECTURE_MAP.md`](./ARCHITECTURE_MAP.md) untuk checklist, diagram, dan roadmap lengkap.

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
