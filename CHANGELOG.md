# Changelog

Semua perubahan penting pada project ini dicatat di dokumen ini.

Format mengikuti [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) dan versi menggunakan prinsip [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **EPIC 07 — Deterministic Risk & Safety**:
  - `KillSwitch` — deterministic emergency stop (07.07)
  - `CircuitBreaker` — auto-trip on repeated failures (07.08)
  - `RiskLead` sebagai Department Lead untuk risk aggregation dan advisory decisions.
  - 4 spesialis analis: `AccountRiskAnalyst`, `PositionRiskAnalyst`, `PortfolioRiskAnalyst`, `DrawdownAnalyst`.
  - `RiskAssessmentReport` dan `RiskCommitteeDecision` schema dengan scoring, warnings, dan recommendations.
  - Separation test: membuktikan AI risk advice tidak memiliki izin memodifikasi batasan deterministik atau mengeksekusi order MT5.
  - 9 unit test komprehensif (`test_risk_intelligence.py`), 100% green.
- **EPIC 04 — Market Intelligence Department**:
  - `MarketLead` sebagai Department Lead untuk intelligence aggregation dan consensus synthesis.
  - 5 spesialis analis: `TechnicalAnalyst`, `StructureAnalyst`, `MomentumAnalyst`, `VolatilityAnalyst`, `NewsSentimentAnalyst`.
  - `AnalystReport` dan `CommitteeDecision` schema dengan directional consensus dan agreement/conflict tracking.
  - 10 unit test komprehensif (`test_market_intelligence.py`), 100% green.
- **EPIC 03 — Risk Gate**:
  - Validasi deterministic risk proposal dengan RiskThreshold.
  - Comprehensive unit test suite (`test_risk_gate.py`).
- **EPIC 02 — MT5 Write Guard**:
  - `MT5WriteGuard` class dengan validasi volume, monetary loss harian, dan max exposure.
  - `guarded_execute_order` integration wrapper untuk MT5 connector.
  - Permission enforcement `SEND_TO_MT5` sebelum order dikirim.
- **EPIC 01 — Architecture Normalization**:
  - `Department` dan `DepartmentLead` abstraction (PRD V2 §5.2).
  - Extended metadata pada `BaseAgent` (`role`, `permissions`, `dependencies`, `model_policy`, `timeout_seconds`).
  - Query helper di `AgentRegistry` (`get_by_role`, `get_by_permission`, `export_metadata`, `validate_permissions`).
  - `SupervisorAgent` auto-delegation ke `department_lead` sebelum fallback ke specialist langsung.
  - Guard helpers dan `AgentPermissionError` di `agents.permissions` (`require_permission`, `submit_to_risk_gate`, `propose_execution`, `send_to_mt5`).
  - `ARCHITECTURE_MAP.md` sebagai central index arsitektur dan dokumentasi.

### Planned
- End-to-end integration testing
- Staging / production deployment hardening
- Explicit live-trading enablement

---

## [1.0.0] - 2026-09-14

### Added

#### Phase 28–30 — Security & Live Readiness
- Security hardening untuk API, service Python, dan konfigurasi runtime.
- Validasi paper trading dan demo trading.
- Live readiness evaluator, gate, dan checklist sebelum mode `LIVE` dapat diaktifkan.

#### Phase 27 — Observability
- Metrics dan alerting untuk monitoring sistem.
- Observability dashboard pada aplikasi web.

#### Phase 21–26 — Frontend
- Dashboard Foundation berbasis Next.js.
- Trading Dashboard.
- AI Control Center.
- Strategy Center.
- Research Center.
- System Settings.

#### Phase 18–20 — Research & Simulation
- Research Engine.
- Paper Trading simulation dengan akun dan simulated execution.
- Demo Trading dan stability validation.

#### Phase 15–17 — Monitoring, Memory & Review
- Position Monitor.
- Trade Memory.
- Trade Review.

#### Phase 14 — Execution Engine
- Validasi order sebelum eksekusi.
- Pengiriman order, confirmation, retry, dan duplicate prevention.

#### Phase 10–13 — Risk & Supervisor Synthesis
- Risk Engine untuk risiko account, position, dan portfolio.
- Money Management / position sizing.
- Supervisor synthesis untuk menggabungkan hasil analyst agents.
- Deterministic Risk Gate dengan hard risk limits.

#### Phase 7–9 — AI Layer
- SupervisorAgent dengan routing policy, concurrency, dan token budget.
- 9Router LLM gateway dengan registry provider.
- Market agents: Structure, Momentum, Volatility, dan News.

#### Phase 4–6 — Trading Intelligence
- Market Regime Engine.
- Event Engine dengan EventDetector class-based.
- Priority processing, deduplication, queue, dan event history.

#### Phase 1–3 — MT5 & Trading Foundation
- MT5 connector layer: connection manager, data models, retrieval, dan endpoints.
- Paper trading API.
- Deterministic Trading Engine, indicators, trend, volatility, dan event processing.

#### Phase 0 — Architecture Foundation
- Monorepo npm workspaces: Next.js dashboard, Express API, FastAPI service, dan shared TypeScript package.
- Foundation Python: FastAPI, pydantic-settings, SQLAlchemy, pytest, dan pre-commit.
- Database layer: Prisma, SQLAlchemy, Docker Compose, migration, init, backup, dan restore tools.
- Structured logging dan environment validation.
- Development setup guide, CI/CD blueprint, constraints, PRD, dan environment template.

### Security
- Deterministic validation dan Risk Gate menjadi jalur wajib sebelum order dapat dieksekusi.
- Hard limits untuk drawdown, daily loss, dan exposure tetap berada di kode; tidak dapat diubah oleh LLM.
- Mode `LIVE` memerlukan explicit enablement dan live-readiness validation.

---

## [0.1.0-alpha] - 2026-09-12

### Added
- Initial monorepo repository structure.
- README, development setup documentation, constraints documentation, dan CI/CD blueprint.
- Environment template dan dependency manifests untuk Node.js serta Python.
