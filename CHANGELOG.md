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

- **EPIC 15 ‑ Dashboard & Control Plane**:
  - 16 halaman dashboard: System Overview, Trading, Positions, Market, AI Organization, Task Explorer, Decision Explorer, Risk Center, Execution Center, Audit Viewer, System Health, Committee Trace, Telegram, AI Providers, Model Registry, Learning Analytics (15.01–15.22).
  - API endpoints baru: `/system/overview`, `/trading/overview`, `/positions`, `/market/overview`, `/tasks`, `/decisions`, `/system/health`, `/audit/events`, `/committee/trace`, `/telegram/status`, `/ai/providers`, `/ai/models`, `/learning/analytics`.
  - Fix pre‑existing bug audit middleware: Express 5 null‑prototype query crash + `log.audit` bukan pino method.
  - Navigasi Control Plane ditambahkan ke semua halaman existing.
  - Next.js build 8/8 routes sukses; ESLint 0 errors.

- **EPIC 16 ‑ Observability**:
  - `TraceCollector` — event traces & task traces dengan span parent/child, status, durasi (16.03–16.04).
  - `MetricsRegistry` — counter/gauge/histogram berlabel + domain recorders: risk decisions (16.08), execution (16.09), supervisor KPI (16.11), committee consensus (16.12), decision quality (16.13), no-trade outcomes (16.14), learning patterns (16.15), Telegram delivery (16.16), provider health (16.17), token usage (16.05).
  - `AlertManager` — threshold rules (above/below), dedup saat firing, auto‑resolve, severity validation (16.10).
  - Structured logs, HTTP latency & error rates sudah tersedia dari Phase 27 (16.01–16.02, 16.06–16.07).
  - 31 unit tests (`test_observability.py`), 100% green.
  - Full test suite: 783 passed.

- **EPIC 17 ‑ Security**:
  - `ToolPermissionRegistry` — fail‑closed tool→permission mapping dengan wildcard `*` grant, `require()` raise `ToolPermissionError` (17.06).
  - `ProtectedAuditLog` — append‑only audit trail dengan SHA‑256 hash chain; deteksi modifikasi, penghapusan, dan reorder entry (17.07).
  - Authentication, RBAC, secret isolation, API authorization, agent permissions, rate limiting sudah tersedia dari Phase 28‑30 + EPIC 01 (17.01–17.05, 17.08).
  - LIVE mode protection tersedia dari `live_readiness` (17.09).
  - 17 unit tests (`test_security.py`), 100% green.
  - Full test suite: 800 passed.

- **EPIC 18 ‑ Testing & Failure Simulation**:
  - `test_failure_simulation.py` — 13 skenario kegagalan: isolasi agent gagal/timeout, pemulihan transient, duplikat order, circuit breaker→kill switch, reconciliation mismatch→block, chaos storm (18.03–18.04, 18.07, 18.09–18.10, 18.14).

- **EPIC 19 ‑ Live Readiness**:
  - `LiveReadinessGate` — 14 gate bernama: backtest, walk_forward, paper, demo, risk, stability, recovery, observability, security, autonomous_workflow, committee_consensus, learning_safety, telegram_control_plane, provider_discovery (19.01–19.09, 19.11–19.15).
  - Gate hanya bisa PASSED dengan evidence eksplisit; submission FAIL wajib menyertakan evidence atau alasan.
  - **Explicit LIVE activation (19.10)**: `activate_live()` hanya berhasil jika SEMUA gate PASSED dan frasa konfirmasi persis `"ACTIVATE LIVE TRADING"`; tidak ada bypass programatik.
  - Fail‑closed: gate revoke atau fail saat LIVE otomatis menurunkan mode kembali ke PAPER.
  - Custom gate pluggable via protocol `ReadinessGate`; riwayat aktivasi/deaktivasi immutable (`ActivationRecord`).
  - 23 unit tests (`test_readiness_activation.py`), 100% green.

### Planned
- End‑to‑end integration testing.
- Staging / production deployment hardening.

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