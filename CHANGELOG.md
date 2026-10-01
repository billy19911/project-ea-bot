# Changelog
Semua perubahan penting pada project ini dicatat di dokumen ini.
Format mengikuti [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) dan versi menggunakan prinsip [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
## [Unreleased]

### Added — Zona OB/FVG berkualitas: overlay chart + gate entry closed-bar + bias gate
- `services/python/src/trading/entry_zone.py`: `detect_entry_zones()` baru — deteksi OB/FVG dari closed OHLC (forming bar dikecualikan), quality gate via `ZoneConfig` (retest limit, FVG fill, invalidasi), metadata `mitigation`/`touch_count`; `build_entry_plan`/`ZoneEntryGate` menerima `zone_closes`/`zone_timeframe`/`zone_config` (fallback deteksi lama bila `zone_closes` tidak diberikan — backward compat).
- `services/python/src/orchestration/pipeline.py`: gate entry memakai detektor berkualitas + **bias M30/H1 wajib searah sinyal** (netral → blok dengan alasan jelas); `_zone_wait_reason` memakai detektor yang sama.
- `services/python/src/charting/endpoints.py`: `/chart/analysis` menambah blok `zones` (scan via env `ZONE_TF`, default M5; chart = timeframe chart).
- Web: `PriceChart.tsx` merender band zona (scan solid, chart dashed) + `zonesSignature` (memo stabil, tanpa flicker) + chip zona di `market/page.tsx` + CSS token `globals.css` + `chartSignature.ts`.
- Test: `test_entry_zone.py` (+5), `test_charting.py` (assert blok zones), `test_phase4_5_cutover.py`; full suite **3149 passed**; `tsc --noEmit` web clean. Semua terminal tetap DISARMED.

### Added — Queue pressure stats (EventQueue) + isolasi test ops-drill
- `services/python/src/trading/event_engine.py`: `EventQueue.stats()` — `queue_size` / `queue_capacity` / `queue_high_water` / `queue_rejected` (thread-safe; enqueue saat penuh menambah `queue_rejected`).
- `services/python/src/trading/scheduler.py`: `stats()` menyertakan blok queue dari `queue.stats()`.
- Test: kontrak stats di `test_event_engine.py`/`test_scheduler.py`; `test_ops_drills.py` preflight/verify di-mock agar runner test tidak bergantung stack live. Full suite **3149 passed**. Semua terminal tetap DISARMED.

### Fixed — Timezone MT5: epoch broker → UTC sejati (hapus anomaly +10 jam / "Ruang Komite kosong")
- Akar bug: `connector`/`retrieval` memakai `datetime.fromtimestamp()` (naive local UTC+7) sementara gate freshness (`feed_loop`/`market_freshness`) menganggap naive = UTC; offset server broker **+3h** → bar tampak +~10 jam "di masa depan" → gate `clock_anomaly_received_before_bar` menolak semua snapshot → Ruang Komite kosong.
- `services/python/src/mt5/broker_time.py` (baru): `from_broker_epoch()` / `to_broker_epoch()`, `BROKER_UTC_OFFSET = +3h` (diukur dari server broker). Keluar = `ts − 3h` (aware UTC); masuk = `dt + 3h` (int broker epoch).
- `services/python/src/mt5/connector.py` + `services/python/src/mt5/retrieval.py`: semua output/input dikonversi; **0 `fromtimestamp` tersisa**. `services/python/src/market/health.py`: `_now_naive_local` → `_as_aware_utc`; `services/python/src/trading/feed_loop.py`: komentar diselaraskan (aware-UTC).
- Konsumen aktif ikut dipatch: `review/close_detector.py` (`closed_at` true-UTC) + `reports/daily.py` (window pakai int broker epoch, bucketing/`generated_at`/`cutoff` aware-UTC, note UTC). `review_store`/`trade_ledger` (tanpa caller produksi) tidak diubah.
- Semantik `history_deals_get` diprobes live: INT = raw broker epoch (dipakai langsung), naive-datetime = machine-local (bug), aware OK.
- Verifikasi: `tests/test_mt5_broker_time.py` (22 test) + 2 test konsumen (RED→GREEN); full suite **3149 passed**; E2E live: `/market/health` `bar_timestamp` true-UTC + `clock_anomaly:false`, `/reports/daily` bucket UTC (154 deals, 77 closed, net +19.2M IDR). Semua terminal tetap DISARMED.

### Added — B-10: Auto-Detect Terminal Aktif (Tanpa Gate Live/Demo, Arm Manual per Akun)
- `services/python/src/mt5/terminals.py`: **arm eligibility = terminal running saja**. Field `"execution"` di `mt5_terminals.json` **tidak lagi dibaca** untuk gate apa pun (file milik user tetap tidak disentuh); `list_terminals` mengemit `armable` (= proses running) sebagai ganti `execution_allowed`. Terminal **auto-detect** (running, tidak ada di config) kini armable (`armable: true`) dan ikut fan-out (`fanout_target: true`) — sebelumnya hardcoded "never armable". `arm_terminal` hanya butuh exists + running; `get_armed_terminals` = armed + running; `get_fanout_targets` = running + armed + fanout_target. `execution_permitted()` **tidak diubah** (tetap fail-closed: butuh ≥1 armed + binding attached).
- `services/python/src/mt5/endpoints.py`: docstring `execution_allowed` → `armable`.
- `services/python/src/execution/engine.py`: `_size_for_terminal` fallback sizing baru — `fixed_lot` → `risk_per_trade_pct` → **volume sinyal** (`request.volume`) saat target tanpa config (sebelumnya 0.0 → order fan-out gagal "Volume lot tidak valid (0)"); tetap di-clamp `[min_volume, max_lot_per_trade]` + normalisasi `volume_step`.
- `apps/web/app/control-plane/page.tsx`: badge `eligible`/`data-only` dihapus (sisakan `ARMED` + status running); tombol Arm nonaktif **hanya bila terminal tidak running** (`disabled={busy || !hasToken || !t.running}`); danger zone memakai `selected?.running`.
- Default tetap **DISARMED**; tidak ada order nyata dikirim (semua fake); `EA_ALLOW_LIVE` tidak di-set; `mt5_terminals.json` tidak disentuh oleh agent.
- Test baru `services/python/tests/test_b10_auto_detect_terminals.py` (8 skenario): arm `execution:false`+running → OK; arm auto-detect → OK; arm stopped → fail-closed; fan-out tanpa gate execution; `execution_permitted()` tetap butuh attached; terminal armed mati → drop dari armed & fanout; sizing fallback volume sinyal; default semua OFF.
- Verifikasi: full Python **3120 passed, 0 failed** (3112 baseline + 8 new B-10), lint bersih. E2E smoke LULUS di server utama `:8787` (pasca-restart, PID 39696, kode B-10 aktif) **dan** instance terisolasi `:8791`: `GET /mt5/terminals` mengemit `armable` (tanpa `execution_allowed`); arm `vito2` (LIVE, `execution:false`, running) → `ok:true`, `armed_terminals:["vito2"]`; disarm → `[]`; arm terminal stopped → `ok:false "is not running"` (fail-closed); Node proxy `:3789` meneruskan field baru; state akhir semua DISARMED.

### Added — B-9 Lanjutan: Multi-arm hardening (multi-akun per operator)
- `services/python/src/mt5/terminals.py`: `select_terminal` no longer disarms — selection only moves the process-wide DATA binding; the per-terminal arm state is never touched (success OR failed re-attach). `arm_terminal` no longer requires an attached binding — arming requires only: registered + running + `"execution": true`. Disarm is still always allowed.
- `services/python/src/execution/fanout.py`: canonical fan-out now re-attaches the process-wide MT5 binding **PER ACCOUNT** (`_reattach_for_target`) right before that account's order is built/sent (symbol cache cleared per broker), and restores the original binding in a `finally` (`_restore_binding`, best-effort, never raises). A failed re-attach fails ONLY that account (`FAILED`, "gagal attach ke terminal '<id>'"); the other accounts still proceed. Path-less targets (test doubles) skip re-attach (backward compat).
- `services/python/src/orchestration/pipeline.py`: the single-terminal path now **fails closed when >1 terminal is armed** — `_dispatch_execution` counts armed+eligible terminals (dual-import helper, fail-closed to 0) and, with fan-out OFF and count > 1, returns a `_BlockedExecutionAdapter` failure (`MULTIPLE TERMINALS ARMED — single-terminal execution disabled. Enable canonical fan-out (canonical_fanout_enabled) or disarm all but one.`) instead of silently sending a partial order. Count ≤ 1 keeps the historic behaviour; the fan-out branch is unaffected.
- `services/python/src/system/settings_store.py` + `system/endpoints.py`: new knob `canonical_fanout_enabled` (default NONAKTIF) reported by `_apply_to_runtime` (takes effect on next process start — the coordinator is built once).
- `services/python/tests/test_b9_multi_arm_hardening.py` (new): 12 end-to-end tests — multi-arm without attach; select does not disarm; fan-out per-account re-attach + restore (recording connector); partial attach failure keeps the other account; `execution_permitted()` gate (attached-to-armed → True, attached-to-non-armed → False, armed terminal stops running → False); pipeline >1 armed fail-closed (engine NOT called) vs 1/0 armed normal path; fan-out ON not blocked.
- Updated tests to the new semantics: `test_mt5_terminals.py` (select keeps arm state; arm ignores attachment), `test_task06_canonical_fanout.py` + `test_task12_adversarial_e2e.py` (autouse connector stub for headless re-attach). UI copy updated (`control-plane/page.tsx`): select "status arm tidak berubah"; per-row Arm/Disarm explains multi-arm. Design doc `docs/tasks/B-9-multi-terminal-execution.md` extended with the implemented section + LIMITATIONS.
- Verifikasi: full Python **3110 passed, 0 failed** (3098 baseline + 12 new), lint clean (black/isort/flake8). All terminals remain **DISARMED** by default; no `mt5_terminals.json` execution flag changed; no real order sent (all fakes).

### Added — TASK 12: Adversarial E2E certification
- `services/python/tests/test_task12_adversarial_e2e.py` (new): 33 adversarial end-to-end tests proving the cross-stack invariants for **all 13 scenarios A–M** using the REAL components (event queue + event gate → scheduler → pipeline → supervisor → canonical fan-out → deterministic risk gate → reconciliation/restart recovery → review/R pipeline → error taxonomy → terminal arm state). Only the MT5 client boundary (`ExecutionEngine` send / broker reads) is faked. Each scenario has an explicit assertion: (A) no event → supervisor idle/no proposal; (B) qualifying event → ONE signal; (C) duplicate event → no duplicate signal; (D) one signal → 3 accounts → same `signal_id`; (E) A ok/B fail/C ok → NO second AI analysis; (F) exposure 25% + 10% > 30% → BLOCK; (G) open position → restart → reconcile → state restored; (H) entry 2500/SL 2495/exit 2510 → R=+2, RR = planned reward/risk; (I) trailing SL 2506 → R still from 2495; (J) LLM 503 → `LLM_PROVIDER_503` (never generic agent error) → no order; (K) Python down → Node 503 → UI "Python service tidak tersedia"; (L) LIVE configured → DISARMED at startup → analysis ok → no native order; (M) DEMO explicit ARM → gates pass → execution allowed, then disarmed.
- `src/agents/supervisor.py`: **hardening fix** — `_classify_agent_exception` now loads the `llm.errors` taxonomy via a new `_load_llm_errors()` helper that tries the relative identity then the two absolute spellings, so a provider 503 is ALWAYS attributed as `LLM_PROVIDER_503` regardless of whether the supervisor is loaded as `src.agents.supervisor` or top-level `agents.supervisor`. Previously the top-level identity silently degraded every provider 503 to `AGENT_EXCEPTION` (invariants 18/19). No trading behaviour or default arm state changed.
- Verifikasi: full Python **3098 passed** (33 test TASK 12 baru); Node `node --test test/error-taxonomy.test.cjs test/pythonClient.test.cjs` **34 pass**. Semua terminal tetap **DISARMED** by default (autouse fixture disarms before/after and asserts the invariant).

### Added — TASK 11: Operational UI data integrity
- `docs/audit/UI_DATA_INTEGRITY.md` (new): full trace of all 18 operational pages — `UI field → API endpoint → Node handler → Python source → actual data source`, each classified REAL/DERIVED/SIMULATED/MOCK/UNAVAILABLE. No operational page silently shows MOCK data after the fixes below.
- **F1 — AI Control activity log:** `agents/activity.py` now records the REAL per-run `error` flag; `system/endpoints.py /tasks` reports `status: "failed"` for errored runs and a real `counts.failed` (was hard-coded `"success"` / `0`). The AI Control activity log can no longer render an always-green success badge over a failed run.
- **F2 — Reconciliation false-negative:** `execution/reconciliation.py ReconciliationReport.to_dict()` now emits the UI-facing real keys `has_critical`, `internal_count`, `broker_count`, `mismatches[]` (`kind`/`symbol`/`ticket`/`detail`) and `checked_at` (stamped by `reconciliation_runner.py` with the real UTC run time). The Reconciliation page previously bound to keys that were never emitted and therefore **silently always showed "CLEAN / 0 mismatches"** — it now reflects the true fail-closed state.
- **F3 — Risk Center honesty:** `system/v2_endpoints.py` `/v2/circuit-breaker` now also returns the REAL, pipeline-fed `execution_guard` (kill switch + per-dependency breakers) and flags `value_wired=false`; `/v2/capital` is bound (read-only) to the live MT5 equity and exposes honest derived keys (`total_capital`/`allocated`/`available`/`utilization`/`allocations_configured`/`equity_bound`) without a fabricated equity. `apps/web/app/risk-center/page.tsx` labels the multi-level breaker **manual / not auto-fed**, shows the real Execution guard, and correctly binds `risk_limits.limits` (was rendering `[object Object]`).
- **F4 — Performance dimensions:** `system/v2_endpoints.py _closed_trade_rows()` now carries the REAL `closed_at` timestamp and a session derived from it, so the `hour`/`weekday`/`session` dimensions bucket real closed trades instead of always returning empty.
- **F5 — Market sizing honesty:** `charting/endpoints.py` no longer substitutes a fabricated `equity = 10000.0`; when the real account equity is unavailable `position_size` is `null` and `provenance.sizing_equity_bound=false`.
- Verifikasi: full Python **3065 passed** (6 test TASK 11 baru); `tsc --noEmit` + `eslint` clean (web + api). Semua terminal tetap **DISARMED** by default; tidak ada default arm yang diubah.

### Added — TASK 09: Market freshness
- `src/trading/market_freshness.py` (new): the single deterministic freshness authority. `TIMEFRAME_MAX_AGE_SECONDS` is a **timeframe-aware** threshold map (bar period + documented 60s grace): M1=120s (strict), M5=360s, H1=3660s, H4=14460s, D1=86520s — unknown/empty timeframe falls back to a documented `DEFAULT_MAX_AGE_SECONDS` (M5). `evaluate_freshness(snapshot, ...)` returns a fail-closed `FreshnessVerdict`: rejects `age_seconds > max_allowed_age`; rejects clock anomalies (`received_at < bar_timestamp`, future timestamps beyond `CLOCK_SKEW_TOLERANCE_SECONDS`, negative age); and rejects a snapshot whose `bar_timestamp`/`received_at` is missing/unparseable (`timestamp_unknown`) — an unverifiable age is never treated as fresh.
- `src/trading/feed_loop.py`: every snapshot now carries the required freshness triple `bar_timestamp` / `received_at` / `age_seconds` plus `timeframe` and `symbol` (receive time captured once per poll; `_bar_timestamp()` normalises MT5 bar times to aware UTC, `None` when unparseable — never a silent "fresh").
- `src/orchestration/pipeline.py`: new **market-freshness gate** (Step 0.5) runs BEFORE `_build_analysis_context` merges the snapshot and BEFORE the Supervisor/committee is convened. A stale or clock-anomalous snapshot short-circuits to `STALE_MARKET_DATA` (WAIT) with no report emitted, so **stale data can never reach the committee as trade-ready context**. The gate is `freshness_gate_enabled=True` by default; verified-bad data fails closed, while a genuinely snapshot-less manual cycle is unchanged.
- `src/ops/readmodels.py` + `src/market/endpoints.py`: staleness is now visible — `market_snapshot()` exposes a `snapshot` freshness block, `GET /market/health` embeds `snapshot_freshness`, and a new `GET /market/snapshot-status` returns the cached snapshot's FRESH/STALE/NO_DATA verdict (age, bar_timestamp, received_at, timeframe, max_allowed_age). Absent snapshot → `NO_DATA` (never a fake "fresh").
- `apps/api/src/index.ts`: `/market/snapshot-status` proxy. `apps/web/app/market/page.tsx`: a freshness chip in the Market page meta row (Data segar / Data basi / belum ada snapshot).
- Verifikasi: 20 test TASK 09 baru (`tests/test_market_freshness.py`) — semua 5 kriteria STOP GATE 09. Full Python 3059 passed. Semua terminal tetap **DISARMED** by default.

### Added — TASK 08: Reconciliation + restart recovery
- `src/execution/restart_recovery.py` (new): `RestartRecoveryCoordinator` runs the ORDERED restart sequence — *load durable intents → connect MT5 → read open positions → read recent orders/deals → reconcile → rebuild internal state → ONLY THEN permit execution*. `RestartRecoveryReport` state is `pending` / `reconciled` / `blocked`. `ReconciliationReadinessGate` exposes `check_can_execute() -> (bool, reason)`; it is **fail-closed** (blocks while pending/blocked). A failed broker read is reported as **unverified**, never as "empty" — so `internal == empty` is never mis-read as `broker == empty`.
- `src/execution/engine.py`: `OrderRequest` now carries durable order identity — `signal_id`, `account_id`, `terminal_id`, `broker_order_ticket`, `broker_deal_ticket`, `broker_position_ticket` (plus `intent_id` = idempotency key). These are persisted on `SUBMITTED`/`ACKNOWLEDGED`/`POSITION_CONFIRMED` (and the adopted-lost-response path), so a restart can trace every order back to its canonical signal + account + terminal.
- `src/execution/fanout.py`: stamps `signal_id` / `account_id` onto the built request (and the minimal request fallback) so the persisted ledger is reconcilable across a restart.
- `src/orchestration/pipeline.py`: new **readiness gate** stage (Step B3.5, after the reconciliation guard). Fail-closed: a `readiness_guard` blocks new orders until recovery has converged; a broken guard blocks.
- `src/orchestration/runtime.py`: optional `recovery_coordinator` (default `None` → historic behaviour preserved) wires a `ReconciliationReadinessGate` into the pipeline; `run_recovery()` / `recovery_state()` accessors.
- `src/system/startup_checks.py`: `run_restart_recovery()` builds the production coordinator (durable ledger + read-only MT5 connector + `Reconciler`), wires it onto the runtime and runs it once at boot. Non-live mode is a verified no-op (the connector's synthetic positions are placeholders, not a real broker book) so it cannot cause a permanent false-positive block.
- `src/main.py`: lifespan now runs `run_restart_recovery()` after the existing execution-recovery scan; a failure leaves the system fail-closed.
- `src/orchestration/endpoints.py`: `GET /reconciliation/recovery` (restart-recovery state + `permits_execution`); `GET /reconciliation/status` now includes `recovery`.
- Prinsip: broker ↔ internal state HARUS konvergen; state tidak pasti → BLOCK NEW ORDERS; orphan broker position → blokir entry baru; duplicate recovery TIDAK membuat order duplikat (idempotency by `intent_id`).
- Verifikasi: 25 test TASK 08 baru (`tests/test_task08_reconciliation_restart.py`) — semua 5 kriteria STOP GATE 08. Full Python 3039 passed. Semua terminal tetap **DISARMED** by default.

### Added — TASK 07: Risk / final order invariant
- `src/risk/gate.py`: new deterministic check `monetary_risk` — `risk_money = abs(entry − initial_SL) × contract_size × volume`, using the **actual broker symbol specification** (`market.symbol_spec`, `source == "broker"`) or an explicit broker-supplied value. A labelled fallback/asset-class spec is never accepted as a contract size. When a monetary budget (`max_risk_pct`) is configured the check **fails closed** (reject) if no real contract size can be resolved; no invented fallback.
- `src/orchestration/pipeline.py`: **final-order re-validation** — after the order builder normalises the volume/prices to the broker lot step + digits, the deterministic Risk Gate is re-run on the EXACT final order values (symbol/volume/price/SL/TP). Only an order that passes the gate on its own values may execute, so *final order sent == final order approved*. The final order + its risk verdict are recorded on the result (`final_order`).
- `src/execution/fanout.py`: per-account broker-spec augmentation (`_augment_market_info`) so the account gate always sees real `contract_size`/`point`/`spread`; `_proposal_from_request` + `_differs_from_approved` re-validate the built request when it differs from the approved proposal (byte-parity guard).
- `src/orchestration/runtime.py`: `MAX_RISK_PCT` env configures the monetary risk budget on the production `RiskGate` (safety logic stays out of UI-editable settings). Default unset → check is informational only.
- Projected exposure already validates `current + proposed <= limit` via `RiskEngine.check_projected_exposure`, now exercised with the final volume/price.
- Verifikasi: 16 test TASK 07 baru (`tests/test_task07_final_order_risk.py`) — monetary risk (market_info + broker spec), fail-closed on missing spec, invented-fallback rejection, projected exposure (25%+10%>30% → BLOCK), lot rounding up AND down, final sent == approved (pipeline + fanout), real-gate end-to-end. Full Python 3011 passed. Execution tetap DISARMED.

### Added — TASK 02: Event-driven supervisor / wake model
- `src/trading/event_classes.py`: event-class taxonomy (TRADE_TRIGGER / CONTEXT_UPDATE / HOUSEKEEPING / TRADE_CLOSE) + `EventGate` (classification gate + TTL fingerprint dedup) + `EventFingerprintGuillotine`.
- `src/trading/scheduler.py`: `AutonomousScheduler(event_gate=...)` — only qualifying (TRADE_TRIGGER) events reach the committee; identical events are suppressed deterministically; new `events_gated` stat + bounded event-trace (`recent_event_traces`) recording the exact wake cause per analysis.
- `src/orchestration/runtime.py`: production scheduler now carries an `EventGate` so housekeeping (RISK_*, RECONCILIATION, HEALTH_CHECK, METRICS) can never convene the committee or create a trade proposal.
- `src/trading/feed_loop.py`: stamps `event_id` / `event_created_at` / `feed_poll_time` / `bar_time` on emitted events for the wake-cause trace.
- `GET /scheduler/event-trace` endpoint exposes the recent wake-cause trace.
- Prinsip: NO EVENT → supervisor idle; QUALIFYING EVENT → wake → committee; DUPLICATE → suppressed; HOUSEKEEPING → never a trade signal.
- Verifikasi: 28 test TASK 02 baru (`tests/test_task02_event_driven_supervisor.py`). Execution tetap DISARMED.

### Added — Phase 3: Committee & Debate Engine (COMPLETE)
- `src/agents/roles.py`: 8 canonical roles (regime/structure/liquidity/momentum/volatility/news/entry/challenger) dengan `RoleOutput` ternormalisasi.
- `src/agents/debate.py`: `DebateEngine` bounded (max 2 rounds, max 3 challenges/cycle) + `DebateRecord` traceable.
- `src/agents/event_dispatch.py`: trigger taxonomy (BOS/CHOCH/LIQUIDITY_SWEEP/NEWS_HIGH_IMPACT/VOLATILITY_SPIKE/ZONE_TOUCH/SETUP_FORMED) + level analisis.
- `src/agents/orchestrator.py`: `CommitteeOrchestrator` additive — path supervisor/synthesis lama tetap jalan.
- Prinsip: specialists beri evidence → lead bentuk hipotesis → challenger serang → committee resolve → Risk Gate menegakkan. Unresolved HIGH/CRITICAL → WAIT/NO_TRADE (fail-closed).
- Verifikasi: 46 test Phase 3; full Python 2690 passed; Node 61 passed. Lihat `PHASE3_COMPLETE.md`.

### Added — Phase 4: Entry Engine (COMPLETE)
- `src/trading/entry_config.py`, `entry_zones.py`, `entry_detectors.py`, `trigger_engine.py`, `entry_lifecycle.py`: OB strict (displacement ≥0.5 ATR), FVG 3-candle (gap ≥0.1 ATR), 5 trigger (rejection/displacement/micro_bos/momentum_shift/candle_close), lifecycle CANDIDATE→ARMED→WAITING_TRIGGER→ENTRY_READY/INVALID/EXPIRED, klaim idempoten thread-safe.
- Multi-timeframe: konteks M15 / trigger M5 / mikro M1; timeframe kontradiktif tidak di-average — `structure_invalidated` memblokir.
- Safety: zone touch ≠ entry; trigger engine otoritatif (AI tak bisa force ENTRY_READY); RiskGate tetap otoritatif; no MT5 import di modul Phase 4.
- Verifikasi: 52 test Phase 4; full Python 2742 passed; Node 61 passed. Lihat `PHASE4_COMPLETE.md`. Live trading tetap DISABLED.

### Added — Phases 1-9 canonical trading architecture + ops UI integration
- Arsitektur canonical Phases 1-9 ter-wire ke dashboard ops (Ruang Komite, Entry, Risk, Research, Learning).
- Lihat `ARCHITECTURE_MAP.md` untuk checklist per-EPIC.

### Added — Agent callsigns + REVIEW-LEAD everywhere
- Setiap agent kini punya `display_name` human-friendly (callsign) tampil di seluruh UI (komite, trace, analytics).
- `ReviewLead` tampil di semua surface review/learning (dulu hanya backend).

### Added — Multi-terminal fan-out + Entry OB/FVG live + Settings toggles
- `fan-out`: 1 analisa → N terminal MT5 (`vito1`/`bil1`/`dapit`) via `mt5_terminals.json`.
- Entry OB/FVG multi-timeframe yang sebelumnya terlalu ketat kini dilonggarkan agar sinyal benar-benar tereksekusi.
- Halaman Settings: toggle live `fan_out_enabled` + `entry_obfvg_enabled` tanpa restart.
- Uncommitted saat ini: `vito1` tambah `fixed_lot: 0.01` + `risk_per_trade_pct: 1.0`; `bil1` (`execution: true`) tambah `risk_per_trade_pct: 1.0` + `fixed_lot: 0.05`.

### Added — Global ops alert banner + sidebar search + daily-flow shortcuts
- Banner alert global untuk status ops kritis (arm-live, disconnect, risk block).
- Sidebar: search + shortcut alur harian (Market → Committee → Entry → Risk → Execution).

### Changed — Sidebar & tabel: accordion, zebra, token-ifikasi
- Sidebar: grup collapsible, auto-scroll, collapse rail, animasi smooth collapse/expand; hanya grup aktif terbuka.
- Semua tabel data-heavy: zebra + hover + sticky header; warna/font/mono/radius di-token-ifikasi (`globals.css`).
- Halaman Ruang Komite: emoji diganti ikon SVG + polish premium.

### Fixed — Research Monte Carlo kosong + siklus manual salah simbol
- `metrics.monte_carlo` kini diisi agar halaman Monte Carlo menampilkan hasil.
- Siklus manual pakai XAUUSD (bukan EURUSD); cegah sinyal stuck di cooldown.
- Instrumen utama = gold (XAUUSD); crypto hanya fallback akhir pekan.

### Fixed — R-multiple, lot input, System pages, pagination, SIMULATED flag
- `close price` dari deal MT5 + persist entry-context → deteksi win/R akurat.
- Web: fix input lot, rename Control Panel, tabel AI rapi, chart Price Now + crosshair horizontal.
- System pages diperbaiki + UI tokens/eyebrow dinormalisasi; pagination default 10 + newest-first di halaman high-volume.
- Data pasar simulasi kini di-flag `SIMULATED` eksplisit (tidak lagi disamarkan sebagai live); `lessons` cleaner buang placeholder id-only.

### Fixed — startup: seeding SLTP gagal karena field settings di-rename
- **Gejala:** log menampilkan `Gagal menerapkan runtime settings saat startup` (AttributeError) setiap boot → **seluruh** blok seed + `_apply_to_runtime` **dibatalkan**, sehingga cap lot/risiko & knob SLTP tidak pernah diterapkan saat startup.
- **Sebab:** `main.py` masih membaca `settings.sltp_progressive_enabled` yang sudah di-rename menjadi `sltp_tp1_lock_enabled` saat SLTP diubah ke model ladder.
- **Fix (`main.py`):** gunakan `getattr(...)` dengan default aman + key store yang benar (`sltp_progressive_enabled` ← `sltp_tp1_lock_enabled`), sehingga satu field hilang tak membatalkan seluruh seeding.

### Fixed — Batas risiko: `max_position_size` ditampilkan padahal tidak dipakai gate
- **`system/endpoints.py::_risk_limits_snapshot`**: `max_position_size` didefinisikan di `RiskEngine` tetapi **tidak pernah dipanggil** di `RiskGate` (`check_position_size` tak punya pemanggil di jalur order). Panel "Batas risiko" menampilkannya read-only → terkesan aktif padahal tidak. Kini **di-omit** dari snapshot agar UI jujur (hanya batas yang benar-benar ditegakkan yang tampil). Label web di `settings/page.tsx` juga dibersihkan.

### Verifikasi (startup + limits)
- Python **2539 passed** (+2 regresi: seed SLTP memakai atribut settings yang benar, dan snapshot meng-omit `max_position_size`). Log startup bersih (tak ada lagi `Gagal menerapkan`). Runtime live: `max_lot_per_trade=0.05`, SLTP semua ON. `black`/`isort`/`flake8` bersih; web `tsc`+lint bersih & di-rebuild.

### Fixed — CRITICAL: cap lot `max_lot_per_trade` tidak bekerja (order 1.0 lot lolos cap 0.05)
Gejala: order XAUUSD nyata bervolume **1.0** padahal `max_lot_per_trade` diset **0,05** di dashboard (akun IDR, equity besar).
- **Akar masalah** — `TradingPipeline.max_lot_per_trade` selalu memakai **default kode `1.0`**: `orchestration/runtime.py::_build_pipeline` **tidak meneruskan** knob dari store ke constructor, dan satu-satunya koreksi (`_apply_to_runtime`) rapuh: ia berjalan **setelah** blok `trend_sample_interval` yang bisa melempar lebih dulu, lalu exception-nya ditelan senyap oleh `main.py`. Akibatnya cap tetap 1.0.
- **`orchestration/runtime.py::_build_pipeline`** kini membaca `max_lot_per_trade` & `risk_per_trade_pct` dari settings store **saat construct** (+ clamp fail-safe ke (0,100]) dan meneruskannya ke `TradingPipeline`, plus `force_risk_sizing=True` (lot selalu dihitung ulang dari knob risiko lalu di-cap).
- **`orchestration/pipeline.py`** — default `max_lot_per_trade` diubah dari `1.0` → **`0.05`** (fail-safe floor); cap diekstrak ke `_cap_lot()` dan **selalu** dijalankan, termasuk jalur `entry <= 0` (dulu `return` lebih awal melewati cap). Jika perhitungan cap gagal → **fail-closed** (paksa size = cap), bukan membiarkan order tak ter-cap.
- **`system/endpoints.py::_apply_to_runtime`** — tiap knob kini di-apply dalam `try/except` **independen** (satu gagal tidak membatalkan yang lain); knob ukuran/risiko diproses **lebih awal**; kegagalan dilaporkan di `applied["_errors"]`.

### Verifikasi (cap lot)
- Python **2537 passed** (+3 regresi: satu knob gagal tidak membatalkan cap, `_build_pipeline` membaca cap dari store, dan size 25.0/1.0 di-cap ke 0.05 end-to-end). Runtime live terbukti `max_lot_per_trade = 0.05` (dulu 1.0). `black`/`isort`/`flake8` bersih.

### Changed — SL Management jadi LADDER berbasis level TP (perbaikan "SL pindah terlalu awal")
Keluhan: SL bergerak padahal harga belum mencapai level, sehingga "pindah sebelum waktunya".
- **`execution/sltp_manager.py` — ditulis ulang**: model lama men-trailing dari profit pertama (`progress_r > 0`) → SL bergerak terlalu dini. Model baru = **ladder diskret**:
  1. **Entry** → SL + TP tetap; **tidak ada trailing sebelum TP1**.
  2. **Harga capai TP1 (1R)** → SL pindah ke **BEP + buffer** (`bep_buffer_r`, default 0.1R) — trade anti-rugi.
  3. **Harga capai TP2 (2R)** → SL naik ke **level TP1 (1R)**, profit terkunci.
  4. **Lewat TP2 → TPmax** → **trailing runner** (ATR) tetapi **tidak pernah di bawah TP1**.
  Monotonik & anti-churn tetap terjaga. Konfigurasi baru: `bep_buffer_r`, `tp1_lock_enabled`, `tp1_lock_r`, `tp2_trigger_r`.
- **TP order saat entry = TPmax (3R)** — `agents/synthesis.py` (`TP_ATR_MULT = SL_ATR_MULT × 3 = 4.5×ATR`) dan `orchestration/pipeline.py` (TP dihitung dari `entry ± 3×|entry−SL|`). Sebelumnya TP = 2R, kini 3R agar trade punya ruang menjalankan ladder penuh.
- **R ladder di-anchor ke SL AWAL** — `monitoring/trade_manager.py` kini membaca stop-loss AWAL dari `review/entry_context.py` (hook `initial_sl_reader`), bukan SL yang sudah bergeser, sehingga level TP1/TP2 tidak melenceng saat SL bergerak.
- **Config/env**: `SLTP_BEP_BUFFER_R`, `SLTP_TP1_LOCK_ENABLED` menggantikan `SLTP_BEP_TRIGGER_R`/`SLTP_BEP_LOCK_R`/`SLTP_TP1_LOCK_R`; knob dashboard `sltp_progressive_enabled` kini berarti "kunci profit di TP2". `settings_store.py` + `.env.runtime` diperbarui.

### Verifikasi (SL ladder)
- Python **2534 passed** (`test_sltp_manager.py` dirombak ke model ladder; +regresi TPmax di `test_synthesis.py`, `test_risk_gate_spread_fix.py`); `black`/`isort`/`flake8` bersih. Simulasi ladder (BUY 2000/R10) terbukti: SL diam sebelum TP1, BEP di TP1, TP1-lock di TP2, trail setelah TP2.

### Added — SL/TP Konsisten + R-Multiple Learning (per hari/minggu/bulan)
Menjawab dua keluhan nyata: TP antar-entry "beda", dan learning belum bisa membaca R.
- **Fix inkonsistensi SL/TP** — `agents/synthesis.py` memakai `2.0×ATR`/`4.0×ATR` sementara `risk/money_management.py` dan `trading/level_plan.py` memakai `1.5×ATR`/`3.0×ATR`. Karena pipeline hanya mengisi yang kosong, satu order bisa memakai SL dari satu sumber dan TP dari sumber lain (RR tidak sesuai). Kini `synthesis.py` memakai konstanta tunggal `SL_ATR_MULT=1.5` / `TP_ATR_MULT=3.0` — satusumber kebenaran, RR 2:1 eksak.
- **`review/r_multiple.py` (BARU)** — helper murni `compute_r_multiple()` (R dari *harga*: `(exit-entry)/|entry-SL|`, tidak butuh contract-size), `r_bucket_from_trades()`, dan `aggregate_r_by_period()` (harian/mingguan/bulanan). Degenerate input → `None` (tidak pernah angka palsu).
- **Jembatan SL ke jalur close** — `orchestration/pipeline.py._remember_entry_context()` kini menyimpan **stop-loss AWAL** order ke `review/entry_context.py`; `review/close_detector.py` membawanya ke close record. `review/auto_trigger.py` menghitung `r_multiple` (field + `closed_at`) di setiap `ReviewRecord` dan meneruskannya lewat `trade_result`.
- **Learning baca R** — `system/v2_endpoints.py._closed_trade_rows()` kini mengisi `TradeRow.r_multiple` (sebelumnya selalu `0.0`), sehingga `avg_r`/`total_r` di Performance Intelligence benar-benar terisi.
- **Endpoint baru** `GET /v2/r-performance?period=day|week|month` (Python + proxy Node) — avg/total R, win rate, dan profit factor per periode + ringkasan keseluruhan.
- **Web — Performance page**: kartu "Avg R"/"Total R" + tabel "R-multiple by period" dengan pemilih day/week/month.

### Verifikasi (SL/TP + R)
- Python **2526 passed** (+17 `test_r_multiple.py`, +integrasi di `test_review_auto_trigger.py`/`test_position_close_detector.py`/`test_v2_endpoints.py`); `black`/`isort`/`flake8` bersih. Node API **61 passed**; Web `tsc`+lint bersih.

### Added — Dynamic Stop-Loss Management (BEP / Progressive TP1 / Trailing)
Fitur yang sebelumnya hanya "kode mati" kini berfungsi penuh dan tersambung ke broker.
- **`execution/sltp_manager.py` (BARU)** — logika keputusan murni `decide_stop_loss()`: **break-even** (geser SL ke entry setelah profit N R), **progressive/TP1 lock** (kunci profit saat TP1), dan **trailing** (jarak `ATR × faktor`). Monotonik (hanya mengetatkan risiko, tidak pernah melebarkan), anti-churn via `min_move_r`. Konfigurasi `SLTPConfig`.
- **`execution/engine.py` — `modify_position_sltp()`**: kemampuan BARU memodifikasi SL/TP posisi via MT5 `TRADE_ACTION_SLTP`. **Arm-gated/fail-closed** (pola sama dengan B-7): tanpa terminal ter-arm → 403; simulasi saat MT5 tak tersedia. Sebelumnya sistem **tidak punya** jalur modifikasi SL sama sekali.
- **`monitoring/trade_manager.py` (BARU)** — orkestrator per-siklus: baca posisi → hitung SL → kirim. Fail-safe per-posisi, monotonik, ada `snapshot()` untuk observability (counter + riwayat perubahan).
- **Wiring**: `orchestration/runtime.py` membangun `TradeManager` (opt-in `SLTP_MANAGEMENT_ENABLED`, default OFF) dan memanggilnya di `_monitor_positions()` tiap siklus. Endpoint baru `GET /sltp/status` (Python + proxy Node).
- **Config** (`SLTP_*`): `SLTP_MANAGEMENT_ENABLED`, `SLTP_BEP_TRIGGER_R`, `SLTP_BEP_LOCK_R`, `SLTP_TP1_LOCK_R`, `SLTP_TRAIL_ATR_FACTOR`, `SLTP_MIN_MOVE_R`, dll.

### Added — Multi-Timeframe Analysis (HTF Bias + LTF Entry Filter)
- **`market/multi_timeframe.py` (BARU)** — `compute_htf_bias()` (bias tren TF tinggi via EMA slope, kekuatan ternormalisasi) + `build_timeframe_prices()` (ambil closes per-TF, konsensus multi-TF). Read-only, fail-safe.
- **`trading/feed_loop.py`** — saat `MULTI_TIMEFRAME_ENABLED`, melampirkan `timeframe_prices` (konsensus multi-TF untuk momentum analyst) dan `htf_bias` ke setiap snapshot (opt-in, fail-safe).
- **`orchestration/pipeline.py` — HTF-bias veto**: entry LTF yang **melawan** bias HTF kuat akan diveto menjadi NO_TRADE **sebelum** Risk Gate. Aktif hanya via `MULTI_TIMEFRAME_FILTER_ENABLED`; bias NEUTRAL/lemah tidak pernah memblokir (fail-safe).
- **Config** (`MULTI_TIMEFRAME_*`): daftar TF (`M15,H1,H4`), kekuatan minimum, toggle filter.

### Verifikasi
- Python **2458 passed** (dari 2424, +34 test: `test_sltp_manager.py` 11, `test_trade_manager.py` 6, `test_multi_timeframe.py` 10, pipeline HTF-veto 5, engine SLTP 2); `black`/`isort`/`flake8` bersih. Node API **61 passed**; Web `tsc`+lint bersih.

### Added — Reconciliation Ledger Identity + Learning Engine 2.0 Wiring + Realistic Backtest
- **`execution/engine.py` — ledger identity fields**: saat order dikonfirmasi sebagai posisi (`POSITION_CONFIRMED`), engine kini menyimpan `symbol`/`volume`/`magic` (sebelumnya hanya state+ticket). Reconciliation provider (`internal_positions_from_store`) jadi bisa mencocokkan posisi internal vs book broker (menutup gap B-4 follow-up). Jalur `adopted` (retry/lost-response) juga diperbaiki. +1 test end-to-end.
- **Learning Engine 2.0 (PRD §43) — `learning/engine_v2_store.py` (BARU)**: store JSONL persist untuk `LearningEngineV2` (fail-safe: baris korup di-skip, file tak-bisa-ditulis → cache-only). `learning/feedback.py::record_review_lesson_v2()` menjembatani review → `Lesson` (selalu OBSERVATION; promosi hanya lewat agregasi pola). Di-wire di `main.py` lifespan dan di-rehydrate saat restart. Endpoint `/learning/analytics` kini mengembalikan section `learning_engine_v2` (pattern ter-agregasi + evidence level). **Advisory only** — tidak pernah mengubah parameter strategi live. +6 test.
- **Research — realistic-cost backtester (PRD §39)**: endpoint `POST /research/experiments/{id}/backtest` menerima flag opsional `realistic: true` yang menjalankan `RealisticBacktester` (spread/slippage/komisi/swap/sizing) dengan sinyal EMA(3/8) yang sama seperti baseline. **Additive**: default (tanpa flag) tetap memakai simulasi price-difference lama. Node proxy meneruskan body apa adanya. +1 test.
- **`mt5/connection_manager.py`**: `health_check()` async kini meng-offload panggilan blocking ke `asyncio.to_thread` (sebelumnya memblokir event loop sehingga timeout `wait_for` tak berfungsi).

### Verifikasi (batch 2)
- Python **2424 passed** (dari 2416, +8 test); `black`/`isort`/`flake8` bersih pada file yang diubah. Node API 61 passed; Web `tsc` + lint bersih.

### Fixed — Audit Komprehensif: Bug, Fail-Closed Hardening, Dead Code & UX
- **`risk/monitor.py` — leak state MT5**: `_get_account_info()` tidak lagi memanggil `mt5.initialize()` tiap poll (yang tanpa `shutdown()` bisa meng-clobber binding terminal milik konektor utama). Kini membaca via konektor bersama `mt5.connector.get_account_info()` — satu sesi MT5 yang konsisten (fail-safe bila MT5 absen).
- **`execution/engine.py` — tabrakan ticket simulasi**: generator ticket `int(time.time()*1000) % 1_000_000` diganti `_next_simulated_ticket()` (monotonic counter + ms) sehingga dua fill simulasi dalam milidetik sama tidak pernah bertabrakan. +1 test regresi.
- **`apps/api/src/middleware/security.ts` — sanitizer terlalu agresif**: pola menolak semua string berisi `' " < > -- exec script` (memblokir simbol broker seperti `BTCUSD#`, deskripsi bebas, catatan ber-apostrof). Diganti daftar signature serangan high-signal (SQLi keyword, `<script`, `javascript:`, event handler, path traversal, null byte). +4 test (false-positive + masih memblokir serangan).
- **`apps/api/src/middleware/websocket.ts` — JWT fallback tanpai guard produksi**: kini memakai `resolveJwtSecret()` bersama `auth.ts` (throw di produksi), tidak lagi fallback ke secret dev publik. +1 test.
- **`apps/api/src/index.ts` — hapus endpoint `/signals` stub**: array in-memory non-persisten yang tidak dipakai UI dan diiklankan di `GET /` — dihapus (dead write surface).
- **`apps/api/src/metrics.ts` — agent stats selalu nol**: agregasi histogram `_count`/`_sum` diperbaiki (sebelumnya tidak akumulasi); `latencies` kini benar-benar di-return.
- **`services/python/src/agents/permissions.py` — fail-closed**: `submit_to_risk_gate` tanpa `RiskGate` kini menolak (bukan `accepted: True`); `propose_execution` tidak lagi melaporkan acceptance palsu. Test disesuaikan.
- **`services/python/src/mt5/connection_manager.py`**: `health_check()` async tidak lagi memanggil panggilan blocking sinkron di event loop — di-offload via `asyncio.to_thread` agar `wait_for` timeout benar-benar bekerja.

### Removed — Dead Code
- `services/python/src/live_readiness/gate.py` — duplikat `LiveReadinessEvaluator` + `DynamicMockHandler` yang ter-shadow, tidak pernah di-import.
- `services/python/src/mt5/_constants.py` — duplikat `SIMULATED_SYMBOLS/PRICES`, tidak pernah di-import.
- `infrastructure/docker/Dockerfile` — file rusak (berisi config Vite).

### Fixed — Web UX
- **Command palette (⌘K/Ctrl+K) fungsional**: input filter + navigasi keyboard (`↑`/`↓`/Enter/Esc) + routing nyata; sebelumnya hanya teks statis.
- **Auth guard client-side**: halaman terproteksi kini redirect ke `/login?next=…` bila tidak ada token; `/login` menghormati `?next=` (validasi same-site).
- **Nav**: `/orders`, `/positions`, `/trade-history` ditambahkan; `risk/page.tsx` `activeKey` diperbaiki.
- **Empty states jujur**: `certification` tidak lagi selamanya "Loading…"; panel `execution-quality` menyatakan breakdown belum dikoleksi.

### Verifikasi
- Python **2416 passed**, Node API **61 passed**, Web `tsc` + `lint` bersih.

### Added — Level Entry/SL/TP1/TP2/TPmax di Laporan Sinyal (sesuai model analisa project)
- **`trading/level_plan.py` (BARU)**: matematika murni mengubah model risiko project (`MoneyManager`: SL = 1.5 × ATR, TP = 3.0 × ATR = 2R) menjadi ladder pelaporan **TP1 = 1R, TP2 = 2R (= TP produksi), TPmax = 3R**. Fungsi `build_level_plan` (dari order nyata — SL persis order, tetap konsisten apa pun SL/TP yang dibawa), `indicative_levels` (ATR, saat belum ada order), `direction_from_text`, `extract_price_atr` (membaca snapshot feed loop: `volatility.price/atr`, `market_state`, `prices`, `market_info`). **Tidak pernah mengarang level**: tanpa arah/harga/ATR → `None`.
- **`orchestration/pipeline.py`**: field baru `levels` di `PipelineResult` (+ `to_dict()`) — diisi ladder **order** di jalur proposal/gate dan ladder **indikatif** di jalur no-trade, sehingga laporan tetap membawa Entry/SL/TP1/TP2/TPmax meski siklus berakhir `NO_TRADE`/`WAIT`/`BLOCKED`. Di jalur proposal, bila proposal tak membawa stop yang bisa dipakai (mis. ATR belum tersedia untuk melengkapinya — kondisi live yang membuat gate menolak `stop_loss`), laporan jatuh ke ladder indikatif, bukan kosong. Best-effort: error pelaporan tak pernah menggagalkan siklus.
- **`telegram/notifier.py`**: `_format_levels()` merender satu baris ringkas `📐 Level BUY: Entry 2000.0 · SL 1997.0 · TP1 2003.0 · TP2 2006.0 · TPmax 2009.0` (+ label `(indikatif)` untuk ladder analisis) di **report per-siklus** dan **digest** (satu baris per digest; ladder order nyata diprioritaskan); `summarize_pipeline_result` meloloskan `levels`.
- **Anti-spam tetap**: digest tetap SATU pesan per jendela — ladder ditambahkan sebagai satu baris, bukan pesan baru.
- **Verifikasi**: 22 test baru (`test_level_plan.py` 12 + `test_level_reporting.py` 10); full suite **2005 passed**; pre-commit (black/isort/flake8) hijau.

### Added — Bot Sinyal Telegram Terpisah (bot ke-3, mis. XynnSignal)
- **`build_signal_gateway_from_env()` / `get_signal_gateway()` / `get_report_gateway()` (`src/telegram/notifier.py`)**: Gateway **kedua** opsional lewat `TELEGRAM_SIGNAL_BOT_TOKEN` — semua laporan sinyal (digest `📊 Ringkasan Siklus` + `🧠 Market Analysis`, termasuk keputusan BUY/SELL yang bypass digest) dikirim ke bot ini sehingga **chat bot utama tetap bersih** (hanya perintah `/status` dll). `TELEGRAM_SIGNAL_CHAT_IDS` kosong = memakai allowlist bot utama.
- **Fallback aman**: tanpa token bot sinyal — atau bot sinyal setengah terkonfigurasi (tanpa penerima) — laporan otomatis kembali lewat bot utama. Bot sinyal tidak pernah "menelan" laporan.
- **`/telegram/status` jujur (`src/system/endpoints.py`)**: tambah `signal_bot_configured` / `signal_bot_connected` (true hanya bila token sinyal + transport nyata + penerima terisi).
- **Operator wiring (`scripts/start-all.ps1` + `scripts/restart-py.ps1` + `.env.example` + `.env.runtime`)**: env `TELEGRAM_SIGNAL_BOT_TOKEN` / `TELEGRAM_SIGNAL_CHAT_IDS` diteruskan ke proses Python; placeholder tanpa secret di `.env.example`.
- **Verifikasi**: 14 test baru (`test_telegram_signal_bot.py`); full suite lulus; Flake8/black/isort bersih.

### Added — Fase 7: Learning Feedback Loop (Lessons → Analisis)
- **`JsonlLessonStore` (`services/python/src/learning/lesson_store.py`)**: Store lesson persist **append-only JSONL + cache in-memory**, API-identik `InMemoryLessonStore` (`add_lesson`/`all_lessons`/`get_lessons`/`clear`/`__len__`). Lessons **bertahan lintas restart** (dibuktikan test reload). Fail-safe: baris korup di-skip saat load, file tak bisa ditulis → degradasi cache-only; **nol dependency baru**; tidak menyentuh `memory/trade_memory.py`.
- **`LessonFeedbackProvider` + `format_lessons_reason()` (`src/learning/feedback.py`)**: Merangkas lessons per simbol (`count`/`wins`/`losses`/`recent` newest-first; `"*"` = semua) untuk siklus analisis berikutnya. `record_review_lesson()` adalah **jembatan** `ReviewAutoTrigger.on_review` → store yang sama — sehingga **kedua jalur review** (ReviewLead events + paper-close hook) menulis ke satu sink.
- **Injeksi ke analisis (`src/orchestration/pipeline.py`)**: Param baru `TradingPipeline(lesson_provider=None)` — **default None = perilaku lama utuh**. Bila provider ada → `context["lessons"]` diisi (symbol di-resolve dari event **sebelum** ringkasan dibuat). Provider rusak di-swallow — cycle tidak pernah putus.
- **Surface advisory (`src/market/intelligence.py` + `src/risk/intelligence.py`)**: `MarketLead.analyze()` & `RiskLead.analyze()` menambah reason `"Historical lessons: {count} (W {x}/L {y}) — last: …"` bila ada lessons. **Signal & confidence TIDAK diubah** (deterministik utuh — ditegakkan test).
- **`/learning/analytics` nyata (`src/system/endpoints.py`)**: Kini membaca store proses nyata — `available:true` + `by_outcome` + `total` + daftar lessons (`id`/`category`/`outcome`/`symbol`/`text`). Store kosong → `available:false` jujur; store rusak → `source:"unavailable"` tanpa raise. `by_hour`/`by_regime`/`supervisor_kpis` tetap kosong (tidak difabrikasi).
- **Wiring lifespan (`src/main.py`)**: Startup menukar default store ke `JsonlLessonStore` (env `LESSON_STORE_PATH`, default `logs/lessons.jsonl`) dan memasang `ReviewAutoTrigger(on_review=record_review_lesson)` — jembatan jalur paper-close. Fail-safe: error wiring tidak memblok startup.
- **Wiring runtime (`src/orchestration/runtime.py`)**: Pipeline produksi dibangun dengan `LessonFeedbackProvider(get_lesson_store())` — setiap cycle scheduler/manual membawa lessons ke analisis.
- **Operator wiring (`scripts/start-all.ps1` + `.env.example`)**: `start-all.ps1` kini meneruskan `MARKET_FEED_ENABLED`/`MARKET_FEED_SYMBOLS`/`MARKET_FEED_TIMEFRAME`/`MARKET_FEED_INTERVAL_S` (Fase 6) + `LESSON_STORE_PATH` (Fase 7) ke proses Python; `.env.example` memuat placeholder ketiga grup (Telegram, feed, lesson store) tanpa secret.
- **Verifikasi**: 26 test baru (`test_jsonl_lesson_store.py`, `test_learning_feedback.py`, update `test_system_endpoints.py`); full suite **1501 passed, 0 failed** (1475 → 1501); Flake8/black/isort + pre-commit hooks bersih. **E2E nyata** (TestClient): `TRADE_CLOSE` → lesson tersimpan ke JSONL → `/learning/analytics` melaporkan `available:true, total:1, by_outcome:{win:1}` → instance store baru me-reload lesson → siklus `TREND_BULLISH` berikutnya membawa `"Historical lessons: 1 (W 1/L 0) — last: …"` di reasons `market_lead`; pipeline produksi terverifikasi memakai `JsonlLessonStore` + provider.

### Added — Fase 6: Market Feed Loop (MT5 → Event → Queue → Pipeline)
- **`MarketFeedLoop` (`services/python/src/trading/feed_loop.py`)**: Loop latar belakang otonom yang membaca OHLC MT5 (**read-only**) → deteksi event (`EventDetector` + dedupe + history) → enqueue ke queue produksi → scheduler memproses. **Default OFF** (`MARKET_FEED_ENABLED=false`) — operator menyalakan eksplisit.
  - Fail-safe: MT5/detector error → log warning + skip siklus; loop tidak pernah mati. Satu simbol gagal tidak memblokir simbol lain.
  - Dedupe fingerprint: bar identik (length + waktu + close terakhir) tidak di-emit ulang — pasar tenang tidak membanjiri queue.
  - Guard invariant: modul tidak boleh mengimport execution/order; tidak punya method pemesan order (ditegakkan test).
- **Config baru (`src/config.py`)**: `MARKET_FEED_ENABLED` (default `false`), `MARKET_FEED_SYMBOLS` (`XAUUSD`), `MARKET_FEED_TIMEFRAME` (`M5`), `MARKET_FEED_INTERVAL_S` (`60`).
- **Wiring lifespan (`src/main.py`)**: saat enabled → `MarketFeedLoop` di-start sebagai task; saat shutdown → `stop()` + await (pola sama dengan scheduler). Disabled → tidak ada task tambahan, perilaku lama utuh.
- **`_RecordingPipelineProxy` (`src/orchestration/runtime.py`)**: Siklus yang dijalankan scheduler (event feed) kini dicatat ke history `/decisions` + trace store — sebelumnya scheduler memanggil `pipeline.run()` langsung sehingga keputusan feed tidak pernah terlihat.
- **Verifikasi**: 15 test baru; full suite **1475 passed**; Flake8/black/isort bersih. **E2E nyata** (server :8001, feed ON, simulasi read-only): `events_processed` naik ke 20, `/decisions` terisi otomatis (`EMA_CROSSOVER`, `STOCH_OVERBOUGHT`, `MOMENTUM_BULLISH`) **tanpa POST manual** — sistem menganalisis market sendiri.

### Added — Fase 5: Telegram Transport Nyata + Report Otomatis ke User
- **`HttpTelegramTransport` (`services/python/src/telegram/transport.py`)**: Transport HTTP nyata satu-satunya yang bicara ke `api.telegram.org` — POST `/bot<token>/sendMessage` via `httpx` (timeout 10s), injectable client (test pakai `httpx.MockTransport`, nol network). Error di-raise sebagai `TelegramTransportError` **tanpa membocorkan token** (URL/token tidak pernah muncul di pesan error/log). Guard invariant: modul ini tidak boleh mengimport execution/MT5 (ditegakkan guard test, pola sama dengan gateway).
- **`src/telegram/notifier.py`**: `summarize_pipeline_result()` (ringkasan jujur: event_type, decision, status, confidence, summary ≤240 char, risk_reason, executed, trace_id), `notify_pipeline_result()` (fail-safe — tidak pernah raise; diam saat fitur mati), `build_gateway_from_env()` + singleton `get_gateway()`/`set_gateway()` (token kosong → transport `None`, perilaku lama).
- **`TradingPipeline.result_hook` (`src/orchestration/pipeline.py`)**: Seam report per-cycle — dipanggil tepat sekali di `_finalise()` (semua jalur keluar `run()` melewatinya); hook rusak di-swallow agar report tidak pernah memutus loop otonom. `PipelineResult` kini membawa `event_type`, `confidence`, `summary` (dari sintesis supervisor) — terserialisasi di `to_dict()`.
- **Wiring runtime (`src/orchestration/runtime.py`)**: `_notify_cycle_result` dipasang sebagai `result_hook` pipeline produksi → **setiap cycle** (via `/pipeline/run` maupun scheduler otonom) mengirim report "🧠 Market Analysis" ke allowlist Telegram; gagal kirim tidak memengaruhi cycle.
- **`/telegram/status` jujur (`src/system/endpoints.py`)**: kini melaporkan gateway singleton bersama — `connected:true` hanya bila transport HTTP nyata + allowlist terisi (sebelumnya selalu `false`). Label `pipeline_result` ditambahkan di `format_notification` (backward-compat).
- **Konfigurasi**: `.env.example` + `.env.runtime` placeholders `TELEGRAM_BOT_TOKEN` / `TELEGRAM_ALLOWED_CHAT_IDS` (commented, tanpa secret); `scripts/start-all.ps1` meneruskan kedua env var ke proses Python.
- **Verifikasi**: 24 test baru (`test_telegram_transport.py`, `test_telegram_notifier.py`, update `test_system_endpoints.py`), full suite **1460 passed, 0 failed**, Flake8/black/isort + pre-commit hooks bersih. Fitur mati secara default (tanpa token) — sistem tetap jalan penuh tanpa report.

### Added — Upgrade Kecerdasan Agent: 4 Fase (Fundamental, MarketLead, RiskLead, Review Department)
- **Fase 1 — `FundamentalAnalystAgent` (`services/python/src/agents/analysts/fundamental_analyst.py`)**: Logika fundamental deterministik penuh — konsumsi `NewsFeedProvider.get_economic_calendar()`, scoring berbasis Interest Rate Differential, deviasi High-Impact (NFP/CPI/FOMC/suku bunga), dan risk sentiment. Sinyal `BULLISH`/`BEARISH`/`NEUTRAL` dengan confidence terukur; fail-closed `NEUTRAL` confidence `0.55` saat feed offline. Terdaftar di `main.register_default_agents()` + routing `ECONOMIC_` (35 test baru; commit `369f36d`).
- **Fase 2 — `MarketLead` upgrade (`services/python/src/market/intelligence.py`)**: Kini `agent_type="department_lead"` — deteksi regime pasar (High Volatility / News Spike / Trending / Ranging) dengan adaptive specialist weighting (bobot menjumlah 1.0), delegasi ke spesialis produksi (`momentum_analyst`, `structure_analyst`, `volatility_analyst`, `news_sentiment`) lewat committee, return `CommitteeDecision` kompatibel Supervisor. 26 test baru + update kontrak routing (`test_agent_wiring.py`); commit `16e17b0`.
- **Fase 3 — `RiskLead` wiring (`services/python/src/risk/intelligence.py`)**: Kini `agent_type="department_lead"` dengan identitas `risk_lead`; `can_handle(event_type, context)` menerima event risk (`RISK_`, `DRAWDOWN_`, `EXPOSURE_`, `MARGIN_`, `PORTFOLIO_`, `CORRELATION`) + legacy `risk_analysis`; `analyze()` return dict kompatibel Supervisor. **Advisory-only** — tidak bisa veto, bypass, atau menyentuh MT5; `gate.py`/`engine.py` tidak disentuh (deterministic gate tetap pemegang keputusan akhir). Fail-closed `NEUTRAL` conf 0.0 tanpa data. Legacy `synthesize()`/`create_department()` tetap utuh. 18 test baru + update `test_risk_intelligence.py`; commit `e5cdd77`.
- **Fase 4 — Review Department (`services/python/src/review/intelligence.py` + `src/agents/analysts/review_agent.py`)**: Departemen ketiga setelah Market & Risk.
  - **`PostTradeReviewAgent`** (`post_trade_review`): review trade CLOSED — normalisasi outcome (win/loss/breakeven) + plan adherence (signal vs actual direction), ekstraksi satu lesson deterministik per trade (bukan narasi), persist lewat `lesson_store` injectable (kontrak `add_lesson`, kompatibel `learning.LearningMemory`). Enrichment best-effort via toolkit review existing (`TradeReviewer` MAE/MFE + `classify_root_cause`), fail-safe: store rusak tidak pernah menggagalkan review.
  - **`ReviewLead`** (`review_lead`, `department_lead`): routing `TRADE_CLOSE*` / `POST_TRADE_REVIEW`, jalankan spesialis, return dict Supervisor dengan metadata departemen (`department: review`).
  - **Fail-closed**: data trade hilang → `UNSUPPORTED`/`NEUTRAL` conf 0.0 tanpa lesson tersimpan. **Tidak menyentuh** `memory/trade_memory.py` (tidak punya API lesson), MT5, Risk Gate, atau Execution Engine.
  - Wiring: ekspor `analysts/__init__.py` + `review/__init__.py`, registrasi `ReviewLead()` di `main.register_default_agents()`. 26 test baru; commit `627edb4`.
- **Verifikasi total**: full suite Python **1436 passed, 0 failed** (baseline 1331 → 1366 → 1392 → 1410 → 1436), Flake8/black/isort bersih, pre-commit hooks lulus. Verifikasi end-to-end produksi: `TRADE_CLOSE` → `review_lead` (win + followed_plan → lesson benar), `TRADE_CLOSED` loss+deviated → rule berbeda, `POST_TRADE_REVIEW` tanpa data → fail-closed, `TREND_BULLISH` → `market_lead`, `RISK_CHECK` → `risk_lead` (isolasi 3 departemen terbukti).

### Added — Real-time News & Economic Calendar Feed Provider (News Agent Realtime)
- **`NewsFeedProvider` (`services/python/src/market/news_feed.py`)**: Adapter berita live tanpa API key berbayar.
  - Kalender ekonomi live dari ForexFactory JSON (`https://nfs.faireconomy.media/ff_calendar_thisweek.json`) dengan deteksi event High-impact (NFP, CPI, FOMC, Suku Bunga).
  - Headline finansial live dari Yahoo Finance RSS (`GC=F,DX-Y.NYB`) dan CNBC RSS (Forex & Economy).
  - Sentimen deterministik berbasis leksikon keuangan: scoring float -1.0 s/d +1.0 dan impact level LOW/MEDIUM/HIGH.
  - In-memory TTL caching (15 menit untuk kalender, 5 menit untuk headline) dengan fail-closed fallback agar operasi trading tetap aman saat jaringan eksternal offline.
- **REST API Endpoints (`services/python/src/market/endpoints.py`)**:
  - `GET /market/news`: daftar berita live terbaru beserta score sentimen dan impact.
  - `GET /market/calendar`: event kalender ekonomi minggu berjalan dengan filter mata uang dan impact.
  - `GET /market/sentiment`: ringkasan sentimen gabungan pasar untuk instrumen tertentu (default: XAUUSD).
  - `POST /market/refresh`: paksa pembaruan cache berita dan kalender seketika.
- **Integrasi Otonom**:
  - Disambungkan ke `AutonomousScheduler` via `OrchestrationRuntime` (`runtime.py`) sebagai default `context_provider`, sehingga `NewsSentimentAgent` kini otomatis menganalisa berita pasar realtime di setiap cycle.
- **Verifikasi**: 22 unit test baru di `tests/test_news_feed.py` (total 1331 passed di test suite Python), Flake8 0 warning, Black & isort lulus, CI GitHub Actions 8/8 hijau (commit `198b3ea`). Live server Python :8000 mengembalikan 80 headline berita dan 105 event kalender ekonomi nyata.

### Changed — Pembersihan Dead CSS & Migrasi Design Token (Fase 1-3 Hardening)
- **Dead CSS dihapus via PostCSS AST parser**: 872 baris sisa migrasi AppShell (Tahap A) yang menduplikasi sidebar di 5 modul (`page.module.css`, `ai-control`, `control-plane`, `observability`, `strategy`) dibersihkan tuntas tanpa menyentuh class yang aktif dipakai TSX.
- **233 deklarasi warna mentah dimigrasikan ke CSS design tokens**: hex mentah (`#1f6feb`, `#f5f7fb`, `#ffffff`, `#172033`, `#e5e7eb`, `#d0d5dd`, `#067647`, `#b42318`, `#d92d20`) diganti dengan `var(--primary)`, `var(--bg)`, `var(--surface)`, `var(--text)`, `var(--border)`, `var(--success-*)`, `var(--danger-*)`.
- **Token baru `--neutral-muted: #f2f4f7`** ditambahkan ke `globals.css` untuk background netral sekunder.
- **Verifikasi**: build Next.js lulus, lint 0 error, verifikasi browser headless di `/observability`, `/market`, `/strategy`, `/control-plane` mengonfirmasi background `#f5f7fb`, tombol primary `#1f6feb`, badge sinyal, dan garis level ter-render dengan kontras yang tepat dan nol overflow.

### Changed — Fase 3 "Menu Profesional": Navigasi Sidebar Dirapikan
- **Item aktif kini tint lembut + pill aksen** di tepi kiri (3px) — blok biru penuh sebelumnya membuat sidebar terlihat seperti deretan tombol besar; ikon item aktif diberi warna aksen agar mata langsung menangkap posisi halaman.
- **"Masuk" dihapus dari navigasi** — selalu tampil walau sudah login dan membingungkan; alur masuk tetap lewat footer ("Masuk untuk melihat akun MT5 →") dan halaman `/login`.
- **Tombol "Keluar" di blok sesi footer** — hanya menghapus token browser (tidak menyentuh state eksekusi/arming MT5 sama sekali); info terminal/akun ikut di-reset supaya footer tidak menampilkan data stale.
- **Aksesibilitas keyboard**: `focus-visible` ring di semua item nav + tombol Keluar; label grup sejajar dengan teks item.
- **Konsolidasi**: ikon `key` dihapus (dead code setelah item Masuk dihapus).
- **Terverifikasi** (browser, geometri DOM): 4 grup · 7 item konsisten di 3 halaman, item aktif benar per halaman, pill aksen 3px ter-render, nol overflow; alur Keluar → footer reset jujur → masuk lagi → info akun kembali. Lint + build web hijau.

### Added — Fase 2 "Realistis": SL/TP ATR di Backtest, Posisi Live, dan Chart
- **Backtest kini memakai SL/TP nyata** (2×ATR stop, 4×ATR target — default engine yang sama dipakai live): `_simulate` menerima high/low bar asli dan mengisi `stop_loss`/`take_profit`/`atr_at_entry` per trade + `exit_reason` eksplisit (`stop_loss`/`take_profit`/`signal_reversal`/`end_of_data`). Konvensi konservatif: 1 bar menyentuh SL **dan** TP → SL menang. Tanpa high/low → SL/TP tetap `null`, bukan angka karangan.
- **`atr_series` baru** di `indicators.py` — seri None-aware yang konsisten persis dengan `atr()` (nilai terakhir seri = nilai fungsi latest, dikunci test).
- **SL/TP posisi live di peta**: `Position.sl`/`tp` kini diambil dari MT5; `0.0` (tidak dipasang) dipetakan ke `null` jujur. `position_monitor` menormalkan `null`→`0.0` sesuai konvensi internalnya (semua logika `sl <= 0`).
- **Endpoint `GET /chart/analysis`** (read-only): analisa `TradingEngine` NYATA atas bar live — sinyal, keyakinan, entry, SL, TP, ATR, alasan, plus posisi terbuka simbol yang sama (pencocokan suffix broker `XAUUSD` ↔ `XAUUSDc`) dan provenance formula (2×ATR, R:R 2:1, risiko 2%/trade).
- **Halaman Pasar kini menampilkan**: garis Entry/SL/TP di chart (termasuk SL/TP posisi terbuka yang benar-benar terpasang), panel hasil analisa engine (badge sinyal, keyakinan, level, alasan, provenance), dan tabel posisi terbuka dengan kolom SL/TP — posisi tanpa SL/TP tampil "tidak dipasang", bukan nol.
- **Preview trade backtest** menampilkan kolom SL/TP + alasan keluar berlabel Indonesia ("Stop loss", "Take profit", "Sinyal berbalik", "Data habis") — kode mentah engine tetap dipakai logika.
- **Bug nyata diperbaiki**: `_parse_ohlc` di `trading/engine.py` memakai `float(x)` sebagai default `getattr` yang dievaluasi eager → `analyze()` crash untuk bar objek (termasuk bar nyata connector). Kini bercabang lewat `hasattr`.
- **Anti-slop**: `position_size` mentah TIDAK ditampilkan sebagai "lot" (satuannya belum dinormalisasi ke lot broker — butuh contract size); UI menampilkan risiko 2%/trade dari config engine yang sebenarnya.
- **Test**: 20 test baru (`test_backtest_sltp.py` 12, `test_charting.py` +8) — perilaku SL/TP intrabar, `exit_reason`, konsistensi `atr_series`, mapping `0.0`→`null`, endpoint analisa. Suite Python **1309 passed**; Node 45/45; lint bersih; build web+API sukses.
- **Terverifikasi end-to-end** (data nyata): `/chart/analysis` XAUUSD H1 → BUY entry 4359.14, SL 4315.85 (2×ATR), TP 4445.73 (4×ATR), 3 posisi SELL live tanpa SL/TP tampil jujur; backtest XAUUSD H1 500 bar → 40 trades dengan `exit_reason` + SL/TP per trade; halaman Pasar ter-render dengan 3 garis level di chart, panel analisa, dan tabel posisi tanpa overflow.

### Added — Fase 1 "Pasar": Chart Candlestick Multi-Timeframe (nol dependency)
- **Halaman baru `/market`** ("Pasar") di grup Operasional: chart candlestick SVG inline — nol library chart baru, konsisten dengan pola `TrendChart` (ide #8).
- **Semua timeframe** M1/M5/M15/M30/H1/H4/D1/W1/MN1 dari bar NYATA MT5 read-only (`mt5.connector.get_ohlc`), 100–500 bar, simbol bebas (chip + input manual).
- **Overlay indikator nyata**: EMA 20/50, Bollinger 20; sub-panel RSI 14 (garis 30/70) + MACD 12/26/9 (line/signal/histogram). Semua dihitung `src/trading/indicators.py` yang SAMA dipakai engine — tidak ada perhitungan duplikat yang bisa drift.
- **Seri indikator baru** di `indicators.py`: `ema_series`, `sma_series`, `rsi_series`, `macd_series`, `bollinger_series` — None-aware, nilai terakhir TERBUKTI sama dengan fungsi lama (dikunci test).
- **Aturan jujur**: warm-up indikator = `null` → garis putus (bukan 0 palsu); MT5 tidak live → `ok:false` + alasan, bukan chart karangan; tooltip OHLC menampilkan nilai bar yang benar-benar di-hover.
- **Endpoint**: `GET /chart/candles` (Python, validasi simbol/timeframe/period) + proxy Node.
- **Test**: 29 test baru (`test_indicator_series.py` 14, `test_charting.py` 15). Suite Python **1289 passed**; Node 45/45; build web+API sukses.
- **Terverifikasi end-to-end** (browser, data nyata): XAUUSD H1 120 bar (10–18 Sep 2026), 300 candle ter-render, EMA/RSI/MACD terhitung, tooltip hover menampilkan OHLC + EMA 20/50 + RSI + MACD nyata; geometri 0 elemen keluar viewBox, 9 tombol timeframe 1 baris, tanpa overflow.

### Fixed — Tabel "Penggunaan model LLM" menampilkan baris palsu
- Tabel di AI Control sebelumnya membaca daftar registry (termasuk model yang belum pernah dipanggil) dengan angka nol — terbaca seolah "usage". Sekarang dibangun dari counter nyata per model di `LLMAdvisor` (`model_usage`): hanya model yang benar-benar dipanggil yang tampil; belum ada panggilan = empty state jujur.

### Added — UI/UX Ide #1: Penasihat LLM (9Router) dengan Guardrail Fail-Closed
- **Advisory-only**: LLM TIDAK menyentuh pipeline trading — keluaran hanya teks untuk manusia, tidak ada yang mengonsumsinya otomatis.
- **Guardrail berlapis (fail-closed, urut dari termurah)**: (1) knob `llm_advisor_enabled` default NONAKTIF — nol token sampai operator opt-in; (2) budget token lewat `SupervisorAgent.check_token_budget` NYATA (budget sama dengan yang di-edit di Pengaturan); (3) ketersediaan data pasar nyata; (4) batas keras `max_tokens=512` + timeout 30 dtk.
- **Pemilihan model jujur**: daftar model live gateway diambil langsung (read-only, nol token); hanya model `*free` yang dipilih — model berbayar tidak pernah dipilih diam-diam. Model terverifikasi: `codebuddy-deepseekv4.1flashfree` + fallback `codebuddy-free`.
- **Endpoint**: `GET /ai/advisor/status`, `POST /ai/advisor/advise` (Python) + proxy Node + panel UI di AI Control (status guardrail, form analisis, usage nyata).
- **Usage nyata**: setiap panggilan mencatat model, token, biaya, latency dari respons gateway — bukan placeholder. Fallback rule-based (upstream down) DIFLAG `is_fallback` supaya UI jujur menyatakan teks bukan keluaran model.
- **Terverifikasi end-to-end**: panggilan LLM nyata via UI → 232 token asli (153 prompt + 79 completion), biaya $0, latency 1,58 dtk, budget ter-commit 1200/8000. Knob baru muncul di Pengaturan sebagai checkbox dengan label jujur.
- **Test**: 13 test baru (`test_llm_advisor.py`) — guardrail default-OFF, budget fail-closed, peran invalid ditolak, data kosong ditolak, fallback diflag, pemilihan model live. Suite Python **1257 passed**.
- **Catatan**: `KillSwitch` ditemukan TIDAK ter-wire ke runtime mana pun (hanya dipakai `circuit_breaker` yang juga hanya dipakai test) — memakainya sebagai guardrail akan jadi teater; diganti dengan knob opt-in yang benar-benar mengontrol perilaku.



### Added — UI/UX Ide #6: Pusat Riset Tersambung (ResearchEngine nyata)
- **Temuan:** `ResearchEngine` (583 baris) sudah lengkap — hipotesis, versi strategi, eksperimen, backtest deterministik (EMA crossover dengan `trading.indicators.ema` NYATA), walk-forward 70/30, perbandingan — tapi **terisolasi total** (nol pemakai). Halaman `/` hanya teater: baris eksperimen hardcoded kosong + tombol backtest tak tersambung.
- **Router baru** `src/research/endpoints.py`: `/research/overview`, `/research/experiments` (GET/POST), `/research/experiments/{id}` (detail + provenance + trades preview), `/research/experiments/{id}/backtest`, `/research/compare`.
- **Data nyata**: backtest menolak (ok:false + alasan) saat live mode OFF atau bar < 60 — **tidak pernah** simulasi di atas data acak. Provenance per run: simbol, timeframe, jumlah bar, akun MT5 read-only.
- **Accessor read-only** di `engine.py` (`list_experiments`, `get_backtest_result`, dst) — engine tidak diubah perilakunya.
- **Proxy Node**: GET via `sendProxy`, POST via `sendPostProxy` (status 4xx Python dipertahankan → pesan validasi jujur di UI).
- **UI `/` dirombak total** (23 KB): 3 tab (Eksperimen/Backtest/Perbandingan) — buat eksperimen dari pasangan EMA, jalankan backtest atas bar nyata, lihat metrik + walk-forward + trade preview, bandingkan 2 eksperimen. Catatan jujur selalu tampil: hasil di memori layanan (hilang saat restart), PnL = selisih harga per unit (ukuran posisi tidak dimodelkan).
- **Test**: 9 test baru (`test_research_endpoints.py`) — penolakan live-off, bar kurang, simbol/timeframe invalid, 400/404 validasi, payload JSON-safe (inf → null). Suite Python **1244 passed**; Node 41/41; tsc 0; ESLint 0; build sukses.
- **Terbukti end-to-end** (browser, data nyata akun demo 49662626): backtest XAUUSD H1 500 bar → 50 trades, win rate 28%, PF 1.15, PnL +103.61/unit; eksperimen EMA 5/15 → 32 trades, PF 1.04; perbandingan A/B menampilkan delta lengkap.

### Added — UI/UX Ide #9: Laporan Harian (deal nyata MT5, read-only)
- **Modul `src/reports/daily.py`** (baru): agregasi deal tertutup dari
  `mt5.history_deals_get` terminal terpilih — read-only, tanpa order. Deal
  dengan profit persis 0 dihitung *breakeven* (bukan menang, bukan kalah);
  win rate `null` bila tidak ada keputusan (bukan 0% karangan).
- **Endpoint** `GET /reports/daily?days=7|14|30` (Python) + proxy Node.
- **Tab "Laporan Harian"** di grup Trading Control Plane: KPI (net, trade
  tertutup, win rate, hari terbaik/terburuk), tabel per hari + per simbol.
  Akun yang dibaca selalu dicantumkan; `ok:false` menampilkan alasan backend.
- Test baru 11 (agregasi murni: breakeven, day buckets, simbol, honesty) →
  total suite Python 1235 passed.

### Added — UI/UX Ide #8: Grafik Tren Nyata (sampler + SVG inline)
- **Sampler ring-buffer nyata** (`services/python/src/observability/sampler.py`): menyampel
  equity/balance akun MT5 (read-only) + stats scheduler tiap 15 dtk (240 sampel ≈ 1 jam).
  Sampel yang gagal dibaca disimpan `null` — grafik memutus garis, bukan mengarang nol.
- **Endpoint** `GET /observability/trend` (Python) + proxy Node `/observability/trend`.
- **Komponen `TrendChart`** — SVG inline, nol dependency baru; sumbu Y + garis + label.
  Menampilkan akun yang dibaca (`login` + server) supaya tidak menyesatkan.
- **Knob ke-3 `trend_sample_interval`** (2–300 dtk) di Pengaturan → benar-benar mengubah
  interval sampler secara live (terbukti 15→5→15 tanpa restart).
- Halaman Observability: kartu "Tren Nyata" dengan 4 grafik (Equity, Balance, Event,
  Trade diblokir) + ringkasan awal→akhir→delta.
- Test baru 12 (sampler: ring-buffer, null honesty, settings hook) → total 1224 passed.

### Changed — UI/UX Ide #7: Pengaturan Tersambung ke Backend (anti-slop)

Halaman Pengaturan sebelumnya adalah teater: seluruh form disimpan ke
localStorage dan tidak dibaca siapa pun — termasuk toggle "Kill switch" dan
"Emergency stop" yang mengklaim memblokir order padahal tidak tersambung ke
apa pun. Pada akun LIVE itu berbahaya, jadi halaman ini dirombak.

**Backend**
- `src/system/settings_store.py` (baru): store JSON dengan allowlist ketat —
  hanya dua knob yang benar-benar dikonsumsi sistem: `supervisor_token_budget`
  (dibaca `SupervisorAgent.token_budget`) dan `scheduler_poll_interval` (dibaca
  `Scheduler.poll_interval`). Kunci asing ditolak, nilai di luar rentang ditolak.
- `GET /settings` mengembalikan knob yang bisa ditulis + limit risiko NYATA
  (read-only) dari `RiskEngine`/`RiskGate` yang sedang dipakai.
- `PUT /settings` memvalidasi lalu MENERAPKAN ke objek runtime tanpa restart.
- `src/main.py`: nilai tersimpan diterapkan saat startup dan menang atas default
  environment.
- Node: `PUT` didukung di `pythonClient` (`putJson`) + route `GET/PUT /settings`.

**UI**
- Tab "Runtime": hanya knob tersambung; tiap baris mencantumkan objek pembacanya
  ("dipakai oleh …") supaya klaimnya bisa diaudit.
- Tab "Batas risiko": nilai nyata, sengaja read-only (logika safety).
- Field yang tidak tersambung DIHAPUS, bukan dipalsukan.
- 401 (belum masuk) dibedakan dari "layanan tidak menjawab".

**Verifikasi:** 18 test Python baru + 2 test Node baru; full suite 1212 passed;
tsc 0 error; ESLint 0 warning; build sukses. Uji end-to-end dari UI: ubah nilai
-> "Tersimpan & diterapkan" -> file persist berubah; nilai invalid & kunci
asing ditolak. `runtime_settings.json` masuk .gitignore (state, bukan kode).

### Added — UI/UX Ide #3, #4, #5: Masuk, Tab Bergrup, Filter Terminal

Tiga perbaikan UI yang dikerjakan bertahap dari daftar ide yang dipilih user
(1,3,4,5,6,7,8,9). Tanpa dependency baru, tanpa menyentuh logika safety.

- **#3 Halaman Masuk (`apps/web/app/login/page.tsx` + `login.module.css`)**: menggantikan alur manual "jalankan token.bat → buka DevTools → tempel localStorage". Dua jalur: tempel token, atau buat token dev sekali klik (`POST /auth/token`, sama seperti token.bat). **Token diverifikasi ke `/mt5/terminals` sebelum disimpan** — token salah (401) tidak pernah masuk localStorage. Backend auth tidak diubah. Sidebar AppShell dapat menu "Masuk" + ikon `key`; footer yang butuh token kini menaut ke `/login` alih-alih menyuruh buka console.
- **#4 Tab Control Plane bergrup**: 16 tab datar → 5 grup (Ringkasan, Trading, Organisasi AI, Risiko & Eksekusi, Sistem) dengan baris tab kontekstual di bawahnya. Semua tab tetap terjangkau (maksimal dua klik), tidak ada yang dihapus. Judul halaman mengikuti tab aktif.
- **#5 Filter terminal nonaktif**: terminal STOPPED disembunyikan secara default (9 terminal → 2 yang berjalan), dengan tombol "Tampilkan nonaktif (N)" dan pilihan tersimpan di localStorage. Terminal terpilih selalu tampil.

### Changed — UI/UX Fase 4: 5 Halaman Dirapikan (anti-slop)

Rapikan semua halaman agar konsisten: bahasa Indonesia untuk label/aksi
(istilah teknis baku tetap Inggris), empty state jujur, dan penghapusan
klaim fabrikasi. Tanpa dependency baru, tanpa menyentuh logika safety.

- **Halaman Pengaturan baru (`apps/web/app/settings/page.tsx`)**: `SettingsView` dipindah keluar dari home → home kini hanya **satu strip tab** (sebelumnya dua baris tab bertumpuk: level-1 + sub-tab). Sidebar AppShell dapat grup "Sistem" + ikon `sliders` (SVG inline). CSS dipakai bersama `app/page.module.css` (tanpa duplikasi 545 baris).
- **Hapus klaim fabrikasi**: tombol "Flush order queue" dihapus — mengklaim "0 order pending (aman)" padahal **tidak ada endpoint flush** di backend.
- **Hapus badge mode bohong**: badge `PAPER` statis (home) dan `LIVE` statis (strategy) dihapus — status mode nyata hanya dari footer AppShell (read-only, sumber API).
- **Pesan error jujur**: `Reasoning unavailable — Python service unreachable` → membedakan **401 butuh token**, HTTP non-OK, dan API tidak terjangkau. Banner kuning di Control Plane menjelaskan saat token belum ada (data kosong bukan "tidak ada data").
- **Bahasa konsisten**: label tab control-plane (16), observability, judul halaman (Pusat Riset / Pusat Kontrol AI / Pusat Strategi / Observability Sistem / Pengaturan), header tabel, tombol (`Muat ulang`, `Jalankan Siklus`), dan eyebrow — semua Indonesia; istilah teknis (Trading, Sharpe, Drawdown, Backtest, Pipeline, Token) tetap Inggris.
- **Tipografi (masalah #11)**: H2 seragam **18px** (control-plane sebelumnya 15px — tenggelam di bawah H1 24px).
- **Dead code**: `showNotice` di `TabContent`, `FormEvent`/`Fragment` import, dan handler settings lama di home dihapus.

### Added — UI/UX Fase 3: Panel Terminal & Akun MT5 di Atas Control Plane

Panel terminal dipromosikan dari tab "Trading" ke posisi teratas Control Plane
(selalu terlihat di semua tab), dengan info akun per-terminal yang diambil
lewat probe read-only. Tanpa dependency baru, tanpa menyentuh jalur eksekusi.

- **`services/python/src/mt5/terminals.py`**: `probe_accounts()` — probe read-only: simpan binding asli, attach tiap terminal berjalan satu per satu, baca akun, lalu **selalu** restore binding asli di `finally` (kegagalan restore dilaporkan, bukan disembunyikan). Hasil di-cache di `_account_cache` (per folder) dan dipakai `list_terminals()` untuk enrich tanpa menyentuh binding. `_binding_lock` baru menyinkronkan probe vs `select_terminal` (satu binding = satu lock).
- **`services/python/src/mt5/endpoints.py`**: `POST /mt5/terminals/probe` (read-only, tanpa jalur order).
- **`apps/api/src/index.ts`**: proxy `POST /mt5/terminals/probe` + parameter timeout opsional di `sendPostProxy` (probe bisa >10s karena attach per terminal).
- **`apps/web/app/control-plane/page.tsx` + `page.module.css`**: tabel terminal kini punya kolom **Akun, Server, Mode, Balance** (badge LIVE/DEMO), tombol **"Cek akun"** (disabled tanpa token), footer "Terpilih: … · akun dicek HH.MM", dan zona berbahaya terpisah visual untuk arm/disarm. Kolom kosong menampilkan "—" (tanpa fabrikasi); probe belum pernah dijalankan → "Belum diperiksa".
- **Test**: `tests/test_mt5_terminals.py` +7 test (32 total di file) mengunci read-only + restore + anti-fabrikasi; suite Python **1194 passed**.

### Added — UI/UX Fase 1+2: Design Tokens & Single AppShell

Redesign dashboard web (rencana: `docs/UI_UX_REDESIGN_PLAN.md`) dengan prinsip
konsolidasi, bukan akumulasi — tanpa dependency baru, tanpa rewrite, tanpa
menyentuh logika safety.

- **F1 — design tokens (`apps/web/app/globals.css`)**: 55 CSS custom property (palet semantic, spacing scale, type scale, radius) menggantikan 120+ hex tersebar; selector bocor (`formTitle-p`, `registry-span`) dihapus.
- **F2 — `apps/web/components/AppShell.tsx` + `AppShell.module.css`**: satu kerangka (sidebar tergrup, ikon SVG inline, topbar, footer) menggantikan 5 shell/sidebar duplikat di `app/page.tsx`, `control-plane`, `ai-control`, `strategy`, `observability`; badge PAPER ganda dihilangkan; pemilih section pindah dari sidebar ke tab strip in-page.
- **Footer akun MT5 (read-only)**: menampilkan terminal terpilih + login/server/trade_mode (badge DEMO/LIVE/CONTEST) dari `GET /mt5/accounts/info`; membedakan 401 (butuh token) dari "tidak terdeteksi" agar tidak menyesatkan.
- **`apps/api/src/index.ts`**: proxy read-only `GET /mt5/accounts/info` (di belakang auth middleware; tanpa jalur order).
- **Perbaikan verifikasi (temuan sampingan)**: `apps/web/tsconfig.json` `include` menunjuk `src/**` yang tidak ada sehingga `tsc` tidak memeriksa apa pun (false green) — kini `app/`, `lib/`, `components/`; ESLint diperluas ke `components/`+`lib/`; 2 dead code dihapus.

### Fixed — Agent Wiring: Supervisor Now Delegates to Real Specialists

Tiga bug wiring yang membuat seluruh agent analyst tidak pernah terpanggil di
jalur produksi (ditemukan lewat audit otonomi AI):

- **Split-brain registry**: `src/main.py` mendaftarkan agent ke `src.agents.registry`, sedangkan `src/orchestration/runtime.py` meng-inject `agents.registry` ke Supervisor — dua modul berbeda dengan dua singleton berbeda, sehingga setiap delegasi menjawab `Agent '<nama>' not registered`. Kini keduanya memakai singleton yang sama.
- **Registry ter-clobber**: `SupervisorAgent.analyze()` menimpa `_registry_cache` dengan `None` setiap kali context pipeline tidak menyertakan key `registry` — wiring produksi hilang pada siklus pertama. Kini context hanya menimpa bila key `registry` benar-benar ada.
- **Routing salah sasaran**: `MOMENTUM_`/`RSI_`/`STOCH_` diarahkan ke `technical_analyst` (bukan `momentum_analyst`), `VOLATILITY_` ke `technical_analyst` (bukan `volatility_analyst`), dan `NEWS_`/`SOCIAL_` ke `sentiment_analyst` yang berstatus UNSUPPORTED (bukan `news_sentiment` yang nyata).

### Added — Default Analyst Registration at Startup

- **`src/main.py`**: `register_default_agents()` (idempotent) mendaftarkan 5 agent saat startup — `technical_analyst`, `momentum_analyst`, `structure_analyst`, `volatility_analyst`, `news_sentiment`. Semua deterministik dan analysis-only (tidak bisa menyentuh MT5, Risk Gate, atau Execution Engine).
- **Bukti live**: `GET /health` kini melaporkan `agents_registered: 5` (sebelumnya 1); `POST /pipeline/run` untuk event `MOMENTUM_BULLISH` benar-benar didelegasikan ke `momentum_analyst`.
- **Test**: `tests/test_agent_wiring.py` (7 test) mengunci ketiga perbaikan + idempotensi registrasi; suite Python **1187 passed**.

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

### Fixed — CI Linux Path Handling (Run 24b)

CI untuk `383b9b9` gagal di job `test` (step "Run backend tests", exit 1) — hijau di Windows lokal.

- **Akar masalah**: path terminal MT5 selalu path Windows, tapi `terminals.py` menurunkan folder dengan `os.path`. Di runner Linux `os.path` = `posixpath` yang tidak menganggap `\` sebagai separator → `dirname(r"C:\mt\A\terminal64.exe") == ""` → pencocokan folder selalu gagal (`running`/`attached` = `False`).
- **Perbaikan**: semua operasi path Windows (`normcase`/`normpath`/`dirname`/`basename`) kini memakai `ntpath` eksplisit — semantik Windows di OS apa pun.
- **Regression test**: test baru menyimulasikan `posixpath` (kondisi CI) dan memverifikasi folder matching tetap benar; suite Python **1180 passed**.
- **Verifikasi**: reproduksi versi lama di bawah simulasi `posixpath` → gagal; versi fix → lolos; **CI 8/8 hijau untuk `ca83368`** (test, lint, build, security, type-check, validate-config, deploy, notify).

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