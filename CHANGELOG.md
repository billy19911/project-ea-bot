# Changelog
Semua perubahan penting pada project ini dicatat di dokumen ini.
Format mengikuti [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) dan versi menggunakan prinsip [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
## [Unreleased]
### Added — Multi-Terminal MT5: Auto-Detect, Select, Arm/Disarm (Run 24)

Mendukung beberapa terminal MT5 berjalan bersamaan: sistem auto-detect terminal
yang aktif, operator memilih satu dari dashboard, dan saklar arm/disarm mengontrol
apakah terminal terpilih boleh mengeksekusi order nyata.

- **Registry terminal `services/python/mt5_terminals.json`** (atau `MT5_TERMINALS_FILE`): `{id, label, path, execution}` — path wajib ke `terminal64.exe`; `execution: true` hanya menandai kandidat, arm tetap wajib dan selalu mulai OFF.
- **`src/mt5/terminals.py`**: auto-detect terminal berjalan via `psutil` (`scan_running_terminals`), pilih terminal (`select_terminal`, re-attach `shutdown()`+`initialize(path=...)`), saklar `arm_execution`/`is_execution_armed`/`execution_permitted`. Config dibaca ulang tiap request — tanpa restart.
- **Fail-closed**: switch/reattach mematikan arm **sebelum** menyentuh binding — jika re-attach gagal, state tetap tidak ter-arm (bug ini ditemukan oleh test baru dan diperbaiki).
- **Endpoint baru**: `GET /mt5/terminals`, `POST /mt5/terminals/select`, `POST /mt5/terminals/arm` (Python + proxy Node); `/mt5/mode` kini menyertakan `execution_armed`.
- **Guard eksekusi**: jalur native `mt5.order_send()` di `execution/engine.py` hanya diizinkan bila mode live **dan** terminal terpilih sudah di-arm; `connector.execute_order()` tetap read-only.
- **Dashboard**: panel **MT5 Terminals** di tab Trading (daftar terminal, status running/attached/selected, tombol select + arm/disarm, pesan penolakan jujur dari server).
- **Proxy Node jujur**: `sendPostProxy` mempertahankan status & pesan upstream 4xx (mis. `400 "Terminal is not execution-enabled"`) alih-alih menutupinya sebagai `503 python_service_unavailable`; `pythonClient` merekam `upstreamStatus`/`upstreamBody`.
- **Dependency**: `psutil==7.2.2`; **test**: `tests/test_mt5_terminals.py` (23 test, mock tanpa MT5 nyata); suite Python **1178 passed**, Node **39/39**.

### Added — MT5 Live Read-Only Data Mode (Run 23)

Connector dapat attach ke terminal MT5 yang **sedang berjalan** untuk membaca data pasar & akun **nyata** — tanpa kredensial dan **tanpa kemampuan eksekusi order**.

- **`MT5_LIVE_DATA=true`** (env): memanggil `mt5.initialize()` untuk attach ke terminal yang sudah login; default `false` = paper mode seperti sebelumnya.
- **Endpoint baru `GET /mt5/mode`**: `{"live_data": true, "execution": "disabled (read-only)"}` + proxy Node `GET /mt5/mode`.
- **Safety berlapis**: `connector.execute_order()` menolak order di mode ini, dan jalur native `mt5.order_send()` di `execution/engine.py` diblokir (guard membaca kedua jalur import modul `mt5.connector` / `src.mt5.connector`).
- **Dashboard jujur**: badge sidebar & topbar berubah jadi **LIVE DATA · READ-ONLY** saat mode aktif; tab Trading menampilkan kartu **Akun MT5 (Live)** (login, balance, equity, free margin, server, leverage) dari `/trading/overview`.
- **`nullableValue`** kini membulatkan float (maks 2 desimal) — noise biner seperti `-120.70000000000002` tidak lagi bocor ke UI.
- **`requirements.txt`**: `MetaTrader5 ; sys_platform == "win32"` (aman untuk CI Linux — paket di-skip).
- **`.env.example` + README**: seksi baru "Mode data live MT5 (read-only)" dengan langkah install & run.

### Fixed — MT5 Live Path Bugs (Run 23)

6 bug di jalur live `services/python/src/mt5/connector.py` yang membuat data nyata tidak pernah terbaca (terverifikasi dengan terminal MT5 nyata):

- `get_tick()`: memanggil `mt5.symbols_get_tick()` (tidak ada) → `mt5.symbol_info_tick()`; objek Tick tidak punya `.symbol` → pakai argumen symbol.
- `get_symbol_info()`: cek `isinstance(raw, list)` padahal `symbols_get()` mengembalikan tuple → symbol info live selalu crash.
- `get_ohlc()`: hardcode `TIMEFRAME_H1` → kini menghormati parameter timeframe (map M1–MN1); atribut numpy array `r.symbol` (tidak ada) → pakai argumen symbol.
- `get_positions()`: `p.margin` (tidak ada di `TradePosition`) → `0.0`; `p.entry` (tidak ada) → `POSITION_REASON_CLIENT` → entry IN/OUT.
- `get_orders()`: `o.volume`/`o.stoplimit` (tidak ada di `TradeOrder`) → field nyata + turunan stop limit.
- **Test**: `tests/test_mt5_live_data_mode.py` (18 test, mock tanpa MT5 nyata — aman untuk CI Linux); suite Python **1154 passed**.

### Fixed — Honest UI Pass 2 (Run 22)

Menutup sisa celah kejujuran data di Control Plane: KPI kini dibaca dari endpoint yang benar, Safety Controls tidak lagi hardcode, dan tab Learning tidak lagi merender "%" kosong.

- **KPI "Hari Ini" (Control Plane overview)**: sebelumnya selalu `—` karena membaca `overview.kpis` (yang memang `null` by design) — kini membaca `/trading/overview` (data nyata: open positions, unrealized PnL, win rate `—` saat wins/losses null).
- **Safety Controls**: hapus hardcode `ARMED/NORMAL/NORMAL/ENFORCED`; kini menampilkan status nyata dari `/system/health` (`risk_gate.safe`, `flags.daily_loss_ok/drawdown_ok/margin_ok/equity_ok`) + `/reconciliation/status` (`last_report.critical`, `total_mismatches`, `history_count`), dengan badge `—` saat data tidak tersedia.
- **Tab Learning**: `{supervisor_kpis?.win_rate}%` tidak lagi merender "%" kosong saat null (kini `—` via helper `nullablePercent`); banner "Analytics belum tersedia" saat `available: false`; tabel by-hour/by-regime menampilkan "Tidak ada data." saat kosong.
- **Risk budget bar**: bar tidak lagi merender 0% palsu saat `risk_utilization` null.
- **Fetch efisien**: `/reconciliation/status` diambil sekali dalam `fetchAll` (sebelumnya fetch terpisah).
- **Docs**: `PRD_V2_CONFORMANCE_AUDIT.md` & `CURRENT_STATE.md` diberi banner HISTORICAL + angka test diperbarui (1136 Python · 38/38 Node).

### Fixed — Honest Data Pass (Run 21)

Menghapus "data fabrikasi" (angka `0`/`[]`/label `live` palsu) di endpoint overview & render UI, agar UI menampilkan `—` ketika data tidak tersedia (honesty over completeness).

- **`/trading/overview`**: sebelumnya menaruh PnL belum terealisasi (`total_unrealized_pnl`) ke field `today.net_pnl` dan mengarang `trades/wins/losses: 0` + `recent_trades: []` sambil mengklaim `source: 'live'`. Kini memetakan field nyata (`trades_executed`, `win_rate`, `profit_factor`, `recent_trades` dengan `side`/`quantity`/`unrealized_pnl`) dan `null` saat sumber tidak tersedia.
- **`/market/overview`**: `session`/`regime`/`volatility` tidak lagi dikarang; `null` bila tak ada data (harga tetap dari `bid`/`ask` nyata).
- **`/system/overview`**: `mode` dan KPI tidak lagi `{}`/hardcode; dihitung dari health nyata, `null` bila gagal.
- **`/ai-control/status`**: hapus daftar agent fabrikasi; `token_used`/`token_budget` `null` saat tidak ada.
- **Risk Center UI**: hapus hardcode **15%** max drawdown / **5%** daily loss; kini memakai limit nyata dari Python `/health` (`risk_gate.max_drawdown_pct`, `max_daily_loss`).
- **Positions UI**: perbaiki nama field yang salah (`volume`/`open_price`/`current_price`/`pnl`) → `quantity`/`price_open`/`price_current`/`unrealized_pnl`; kolom tanpa data menampilkan `—`.
- **Token/cost jujur**: `ai-control` & `observability` menampilkan `—` untuk Total Tokens/Cost saat 0 LLM call (sebelumnya `0`/`$0.000`).
- **Label roadmap dibersihkan dari UI**: `EPIC 15`, `Phase 23/24/27` di header/kartu/komentar CSS dihapus (konsisten dengan README yang bersih dari roadmap).
- **Test**: `apps/api/test/overview-mapping.test.cjs` (regresi baru) menutup mapping jujur; suite Node **38/38** hijau.

### Changed — Hardening & UI Real-Data Iterations (Runs 10–19)

- **CI always-green**: perbaiki workflow CI yang invalid, dependensi & audit, `node --test` portabel (Node 20 & 22), test DB default yang deterministik, config validator memuat `.env`; hasil CI 8/8 hijau.
- **Dashboard memakai data nyata** (bukan demo/hardcode): hapus seed data, strategy registry end-to-end, wiring `/observability` + model registry ke field API nyata (bebas NaN/crash).
- **Model Registry**:
  - base URL gateway 9Router dapat dikonfigurasi via env `NINE_ROUTER_BASE_URL` (default lama `https://api.9router.com/v1` mati → diarahkan ke gateway lokal).
  - sanitasi pesan error HTML dari upstream; sembunyikan field "Last" bila kosong.
  - pertahankan metadata model dari gateway (`context_length`, `capabilities`, `owned_by`) yang sebelumnya hilang karena SDK membuang field ekstra.
  - deteksi model gratis yang jujur (`:free` / `-free` / `/free`); label biaya benar (tidak lagi salah menandai "Gratis"/"Paid"); timestamp registry diformat manusiawi.
- **Uptime & biaya jujur**: uptime service diambil dari data nyata (bukan "live"/`null`), hapus angka `0` fabrikasi (`token_budget`, `max_concurrency`), label biaya "—" saat data tidak tersedia.
- **Rate limit**: dashboard polling reads dikecualikan dari rate limit global (hapus 429 palsu), batas dinaikkan.
- **Observability error-state**: halaman tidak lagi white-screen saat API membalas error (401/429/500) — guard `res.ok` + validasi shape payload + akses nested yang aman; tampilkan pesan jujur "Gagal memuat (HTTP `<kode>`)" + tombol "Coba lagi"; KPI tampil "—" saat data gagal.
- **Konsistensi**: semua halaman dashboard memakai helper `apps/web/lib/api.ts` (`apiFetch`) yang mengirim `Authorization: Bearer` + `X-Trace-Id`.

### Added
- **PRD_V2 Conformance Pass (Run 9)**:
  - Pipeline + scheduler, Telegram gateway, dan model discovery diselaraskan dengan PRD_V2.
  - API wiring: seluruh route non-publik kini memerlukan Bearer token; public allowlist `/health`, `/metrics`, `/auth/token` (§28).
  - Brain §7–§17 (reasoning, routing, memory) dan safety §19/§22–§24/§14/§28/§29 diterapkan.
  - Polish §15/§18/§26/§27, reconciliation, dan research realism.
  - Unifikasi metrics/trace; helper web `apps/web/lib/api.ts` mengirim `Authorization` + `X-Trace-Id` dari `localStorage('ea-bot-token')` di seluruh halaman dashboard (home, ai-control, observability, control-plane).
  - Suite test Node deterministik: `apps/api` menambah `npm test` (`build` + `node --test`) dan test guard produksi `JWT_SECRET`.

- **EPIC 07 ‑ Deterministic Risk & Safety**:
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