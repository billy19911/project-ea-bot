# MASTER PLAN V2 — Operational Loop (Fase 5–7)

> Lanjutan [MASTER_PLAN.md](./MASTER_PLAN.md) (Fase 1–4: Upgrade Kecerdasan Agent — SELESAI & TER-PUSH).
> Status: PENDING EKSEKUSI.

## Ringkasan

Audit integrasi (2026-09-18) menemukan rantai inti **sudah benar**
(supervisor → department lead → spesialis → hasil balik ke supervisor),
tetapi 3 sambungan operasional belum terpasang:

| # | Gap | Fase | Dampak |
|---|-----|------|--------|
| 1 | Report ke Telegram belum ada transport nyata (`transport=None`, tanpa token) | **Fase 5** | User tidak menerima report apapun |
| 2 | Scheduler queue selalu kosong — tidak ada yang feed event dari MT5 | **Fase 6** | Sistem tidak analisis sendiri; hanya saat dipicu manual |
| 3 | Lessons tersimpan tapi tidak dibaca kembali; `/learning/analytics` hardcoded `unavailable` | **Fase 7** | Tidak ada umpan balik belajar dari kesalahan |

## Root Causes (dari audit kode)

### Gap #1 — Telegram
- `TelegramGateway.notify()` ada dan benar, tetapi **selalu dibuat dengan `transport=None`**
  (`system/endpoints.py:85`), dan **tidak ada satu pun pemanggil `notify()` di produksi**.
- Grep seluruh repo: **nol** referensi `api.telegram.org` / `sendMessage` — tidak ada transport HTTP nyata.
- `/telegram/status` live: `enabled:false, configured:false, connected:false, has_token:false`.

### Gap #2 — Event Feed
- `EventDetector` mendukung `queue=`, tetapi di produksi (`events.py:648`) dibuat **tanpa queue**.
- `/events/detect` hanya mengembalikan hasil — **tidak** memasukkan ke queue runtime.
- Scheduler hidup (`running:true`) tapi `events_processed: 0` — queue tidak pernah terisi.

### Gap #3 — Learning Feedback
- `PostTradeReviewAgent` menulis lessons ke `InMemoryLessonStore` (terbukti: 2 lessons saat uji) —
  tetapi **tidak ada konsumen**: tidak ada yang membaca `all_lessons()` untuk analisis.
- `/learning/analytics` mengembalikan hardcoded `available:false, lessons:[]`.
- Lessons in-memory → **hilang saat restart**.

## Constraints (WAJIB)

- **Akun MT5 LIVE (uang nyata)** → semua operasi read-only; eksekusi order nyata DILARANG.
- **Nol dependency baru** — `httpx` (0.28.1) sudah ada di requirements.
- **Fail-closed & graceful degradation** — internet down / MT5 down / token kosong tidak boleh crash.
- **Backward-compat** — API lama tidak berubah; test lama tetap lulus.
- **Tidak menyentuh:** `risk/gate.py`, `risk/engine.py`, `execution/engine.py`, `memory/trade_memory.py`.
- **Rahasia:** bot token & chat ID hanya via `.env`; tidak pernah masuk kode, log, atau repo.
- **Telegram tetap read-only** — tidak bisa memicu order (guard test existing dipertahankan).
- Flake8 `--max-line-length=100`, black, isort; pre-commit hook sebagai gate.
- **TDD** — test ditulis lebih dulu (RED → GREEN).
- **Fase 6 default DISABLED** (`MARKET_FEED_ENABLED=false`) — feed aktif hanya bila operator menyalakan.

## Urutan Eksekusi

1. **Fase 5** — [PHASE5_TELEGRAM_REPORTS.md](./PHASE5_TELEGRAM_REPORTS.md)
   (paling cepat dirasakan: user langsung menerima report)
2. **Fase 6** — [PHASE6_MARKET_FEED_LOOP.md](./PHASE6_MARKET_FEED_LOOP.md)
   (sistem analisis sendiri saat market bergerak)
3. **Fase 7** — [PHASE7_LEARNING_FEEDBACK.md](./PHASE7_LEARNING_FEEDBACK.md)
   (belajar dari hasil trade: lessons dibaca kembali + analytics nyata)

## Prasyarat dari User (Fase 5)

- Buat bot via **@BotFather** di Telegram → dapat `TELEGRAM_BOT_TOKEN`.
- Kirim pesan ke bot → dapat `chat_id` (mis. via `@userinfobot`).
- Isi ke `services/python/.env` (tidak di-commit). Tanpa token, sistem tetap
  berjalan normal dan hanya status yang jujur melaporkan `configured:false`.
