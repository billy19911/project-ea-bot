# Changelog
Semua perubahan penting pada project ini dicatat di dokumen ini.
Format mengikuti [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) dan versi menggunakan prinsip [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
## [Unreleased]
### Added
- **EPIC 07 ‑ Deterministic Risk & Safety**:
  - `KillSwitch` — deterministic emergency stop (07.07)
  - `CircuitBreaker` — auto‑trip on repeated failures (07.08)
  - `RiskLead` sebagai Department Lead untuk risk aggregation dan advisory decisions.
  - 4 specialist analis: `AccountRiskAnalyst`, `PositionRiskAnalyst`, `PortfolioRiskAnalyst`, `DrawdownAnalyst`.
  - `RiskAssessmentReport` dan `RiskCommitteeDecision` schema dengan scoring, warnings, dan recommendations.
  - Separation test: membuktikan AI risk advice tidak memiliki izin memodifikasi batasan deterministik atau mengeksekusi order MT5.
  - 9 unit test komprehensif (`test_risk_intelligence.py`), 100% green.

- **EPIC 08 ‑ Execution Engine**:
  - `OrderBuilder` — deterministically build OrderRequest from trade proposal (08.03)
    - Normalize symbol, prefixes/suffixes, map side/order_type, lot/volume, SL/TP, auto‑quote fill.
  - `ExecutionRecoveryEngine` — mismatch detection and execution blocking (08.07)
    - Audit orphan positions, missing ledger items, volume mismatches.
    - State machine: NORMAL → WARN_MISMATCH → BLOCKED_CRITICAL.
  - 38 unit tests (`test_order_builder.py`).
  - Full test suite: 648 passed.

- **EPIC 09 ‑ Position Monitoring**:
  - `PositionMonitor` real‑time position oversight (09.01).
  - SL/TP management, dynamic updates (09.02).
  - ATR‑based dynamic trailing stop (09.03).
  - Abnormal price movement detection (>3×ATR threshold) (09.04).
  - Risk change monitoring dan exit events generation (09.05, 09.06).
  - 35 unit tests (`test_position_monitor.py`), 100% green.

- **EPIC 12 ‑ Research Engine**:
  - `Hypothesis`, `StrategyVersion`, `Experiment`, `BacktestResult`.
  - Validation, experiment creation, metric aggregation, comparative analysis.
  - 17 unit tests (`test_research_engine.py`), 100% green.

- **EPIC 13 ‑ Strategy Versioning & Promotion**:
  - `StrategyRegistry` — register, get, list, activate, retire strategies (13.01).
  - `VersionedStrategy` — version schema dengan name, version, parameters, status (13.02).
  - `PromotionGate` — enforce DRAFT → TESTING → ACTIVE → RETIRED transitions (13.03).
  - `ReadOnlyDict` — live‑parameter protection saat status ACTIVE (13.06).
  - Hanya satu versi ACTIVE per strategy name (13.04); retirement bersih (13.05).
  - 27 unit tests (`test_strategy_registry.py`), 100% green.

- **EPIC 14 ‑ Learning Loop**:
  - `LearningLoop` — review → pattern → hypothesis → experiment → candidate → validation → approval (14.01–14.07).
  - `PerformanceTracker` — performance‑by‑time, session, regime, setup dengan minimum sample‑size safeguards (14.08–14.10).
  - Supervisor KPI learning: win rate, profit factor, expectancy, max drawdown, false signals (14.11).
  - `compare_candidates` — current vs candidate comparison dengan konsisten metrics (14.12).
  - `LearningMemory` — validated lessons disimpan terpisah dari raw trade history (14.13).
  - Tidak ada automatic live mutation (14.14).
  - 21 unit tests (`test_learning_loop.py`), 100% green.
  - Full test suite: 752 passed.

### Planned
- End‑to‑end integration testing.
- Staging / production deployment hardening.
- Explicit live‑trading enablement.

## [1.0.0] - 2026-09-14
### Added
- Phase 28‑30 ‑ Security & Live Readiness.
  - Security hardening untuk API, service Python, dan konfigurasi runtime.
  - Validasi paper trading dan demo trading.
  - Live readiness evaluator, gate, dan checklist sebelum mode `LIVE` dapat diaktifkan.
- Phase 27 ‑ Observability.
  - Metrics dan alerting untuk monitoring sistem.
  - Observability dashboard pada aplikasi web.
- Phase 21‑26 ‑ Frontend.
  - Dashboard Foundation berbasis Next.js.
  - Trading Dashboard.
  - AI Control Center.
  - Strategy Center.
  - Research Center.

## [0.1.0-alpha] - 2026-09-12
### Added
- Initial monorepo repository structure.
- README, development setup documentation, constraints documentation, dan CI/CD blueprint.
- Environment template dan dependency manifests untuk Node.js serta Python.