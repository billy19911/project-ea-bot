# Changelog
Semua perubahan penting pada project ini dicatat di dokumen ini.
Format mengikuti [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) dan versi menggunakan prinsip [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
## [Unreleased]

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