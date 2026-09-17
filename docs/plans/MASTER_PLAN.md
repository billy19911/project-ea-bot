# MASTER PLAN — Agent Intelligence Upgrade

> Dibuat: 2026-09-18 | Repo: `project-ea-bot` | Branch: `main`

## Ringkasan Eksekusi

4 fase berurutan, masing-masing menghasilkan kode + test + commit terpisah:

| Fase | Fokus | File Utama | Estimasi |
|------|-------|------------|----------|
| 1 | `FundamentalAnalystAgent` — bangun logika fundamental dari data kalender ekonomi | `src/agents/analysts/fundamental_analyst.py` (BARU) | Medium |
| 2 | `MarketLead` upgrade — tambah ilmu: market regime detection + specialist weighting + fix wiring | `src/market/intelligence.py` (MODIFIKASI) | Large |
| 3 | `RiskLead` wiring — fix interface + register ke `main.py` | `src/risk/intelligence.py` (MODIFIKASI) | Medium |
| 4 | Departemen baru — `PostTradeReviewAgent` + Review Department | `src/agents/analysts/review_agent.py` (BARU) | Medium |

## Root Causes (dari audit kode)

### Bug #1: `agent_type` salah
`MarketLead` dan `RiskLead` pakai `agent_type="lead"`, bukan `"department_lead"`.
Supervisor (`supervisor.py:328`) cari `registry.get_by_type("department_lead")` → tidak pernah menemukan keduanya.

### Bug #2: `can_handle` signature tidak kompatibel
`MarketLead.can_handle(self, task_type: str) -> bool` dan
`RiskLead.can_handle(self, task_type: str) -> bool` —
`BaseAgent.can_handle(self, event_type: str, context: dict) -> bool`.
Supervisor panggil `agent.can_handle(event_type, context)` → `TypeError` atau bypass.

### Bug #3: `analyze` return type tidak kompatibel
`MarketLead.analyze()` return `AnalystReport` (dataclass).
`RiskLead.analyze()` return `RiskAssessmentReport` (dataclass).
Supervisor expect dict: `{"agent": str, "signal": str, "confidence": float, "reasons": list[str], ...}`.

### Bug #4: Tidak di-register
`main.py:register_default_agents()` hanya daftarkan 5 agent (Technical, Momentum, Structure, Volatility, NewsSentiment).
`FundamentalAnalystAgent`, `MarketLead`, `RiskLead`, `DepartmentLead` — semua belum di-register.

### Bug #5: Specialist duplikat
`market/intelligence.py` punya mini specialist stubs (`TechnicalAnalyst`, `StructureAnalyst`, dll)
yang tidak sama dengan agent produksi (`TechnicalAnalystAgent`, `StructureAnalystAgent`, dll).
Harusnya komite pakai output dari agent produksi yang sudah terdaftar.

## Constraints

- **SAFETY:** MT5 akun LIVE — semua operasi read-only, no order execution.
- **No new dependencies** — hanya `httpx` + modul bawaan Python.
- **Fail-closed:** internet down / feed offline → NEUTRAL confidence 0.55, tidak crash.
- **Code style:** `black`, `isort`, `flake8 --max-line-length=100`.
- **Test coverage:** setiap fase punya unit test, full suite harus pass.
- **Deterministic:** semua logika berbasis rules/keywords, no random, no LLM API calls.

## Pre-requisites (sudah tersedia)

- `NewsFeedProvider` (`src/market/news_feed.py`) — fetch ForexFactory calendar + RSS news, caching, sentiment scoring.
- `NewsFeedProvider.get_news_context(symbol, currency)` → dict dengan `news_items` + `economic_events`.
- `EconomicEventItem` dataclass: `title, country, date, impact, forecast, previous`.
- `DepartmentLead` generic (`src/agents/departments.py`) — pattern reference untuk department lead.
- `trade_memory.py` (`src/memory/trade_memory.py`) — storage untuk post-trade review.

## Urutan Eksekusi

```
Fase 1 (Fundamental) → Fase 2 (MarketLead) → Fase 3 (RiskLead) → Fase 4 (Review Dept)
     ↑ dependency: Fase 2 butuh FundamentalAnalystAgent dari Fase 1
```

Setiap fase: implement → test → lint → commit.
