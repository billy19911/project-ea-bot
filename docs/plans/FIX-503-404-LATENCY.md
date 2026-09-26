# FIX-503 — Model Discovery Blocking + 404 Route + Loading Lambat

Status: SELESAI + TERVERIFIKASI LIVE (2026-09-26 08:30) — T1/T2/T3 dieksekusi via OpenCode,
diverifikasi ulang oleh supervisor (test+lint sendiri), lalu restart service via jalur resmi.

## Hasil live (after)
- `/ai/models`: call1 0.68 dtk -> call2/call3 0.003 dtk (negative cache); `source=gateway`,
  state CONNECTED, **658 model** (sebelum: defaults/DISCONNECTED/6 model).
- `/health` saat `/ai/models` jalan: 0.0027 dtk (event loop bebas; sebelumnya semua endpoint ~5 dtk).
- Endpoint eks-503 via Node: `/ai/models` 200/8ms, `/mt5/terminals` 200/8ms, `/mt5/mode` 200,
  `/learning/analytics` 200, `/reconciliation/status` 200.
- `/ea-api/research/strategies` via web: **200** (3 strategi; sebelumnya 404).
- Chain web `/ea-api/*` 200 semua; bil2 re-select+re-armed (restart mengosongkan arm = by design).
- Verifikasi supervisor: full pytest **2193 passed** (2183+5+5); api npm test **55 pass/0 fail**;
  tsc 0; flake8/black (file baru) 0. Diff direview minimal; tidak ada commit.

## Verifikasi (acceptance asli)
- T1: test baru hijau; test_model_discovery + test_system_endpoints + test_llm* hijau; concurrency test
  membuktikan /health tetap cepat saat discovery lambat.
- T2: test_env_bootstrap hijau; full pytest hijau (baseline 2183 passed, tidak boleh merah).
- T3: `npm run build` hijau; live curl route -> 200.
- Lint: flake8 (max 100, ignore E203,W503) + black --check hijau; tsc/eslint hijau.
- Live: restart Python via `scripts/restart-py.ps1` -> `/ai/models` <1 dtk, `source=gateway`,
  state CONNECTED; console tanpa 503; terminal tampil; bil2 re-armed. SEMUA TERPENUHI.

## Catatan operasional
- Node live di-restart manual (kill port-scoped + `node dist/index.js` dari `apps/api`); tidak ada
  script restart Node di repo. Route baru + loadEnv aktif di proses baru.
- 2 penyimpangan pre-existing didokumentasikan di report (flake8 di file user lain; black
  endpoints.py) — bukan dari fix ini.
- Risiko sisa (T1): repeat window 60 dtk tetap 1 percobaan jaringan/window; lock per-registry.
Tanggal: 2026-09-26
Konteks: Laporan user — terminal MT5 kadang hilang dari UI, console 404+503 massal, loading lambat.

## Gejala (bukti live)
- Console web: 404 pada `/ea-api/research/strategies` + `/ea-api/risk`; 503 massal pada `/ai/models`,
  `/learning/analytics`, `/reconciliation/status`, `/mt5/mode`, `/mt5/terminals` (masing-masing 3x).
- `/ai/models` Python: 1.75-8.7 dtk (endpoint lain 2-8 ms); saat discovery jalan SEMUA endpoint ikut
  melambat ~5 dtk (probe konkurensi: 4.97s vs 0-22ms normal).
- `/ai/models` health: `DISCONNECTED`, `source=defaults` (discovery tidak pernah sukses).
- Node proxy timeout 5 dtk (`apps/api/src/pythonClient.ts` DEFAULT_TIMEOUT_MS=5000) -> 503 saat Python sibuk.
- Panel terminal kosong ("Tidak ada terminal terdeteksi") = gejala turunan 503, bukan terminal lepas
  (saat service luang: bil2 armed:true normal).

## Root Cause (terkonfirmasi, bukan hipotesis)
1. Service Python live dijalankan TANPA env `NINE_ROUTER_BASE_URL` (cmdline uvicorn polos; jalur
   `start-all.ps1`/`restart-py.ps1` memang mengekspor env — service sekarang bukan dari jalur itu).
2. Tanpa env, `NineRouterClient` (src/llm/nine_router.py:91-93) jatuh ke default internet
   `https://api.9router.com/v1` -> 404 HTML setelah 1.75-8.7 dtk.
3. `ModelRegistry.discover_from_gateway()` (src/llm/registry.py:146-202) dipanggil SINKRON di handler
   `async def ai_models()` (src/system/endpoints.py:154-166) -> event loop Python terblokir; cache
   hanya berlaku setelah SUKSES -> setiap request mengulang jaringan -> request lain antre ->
   proxy Node timeout 5 dtk -> 503.
4. 404: Node API tidak punya route `GET /research/strategies` (dipanggil apps/web/app/backtest/page.tsx:129;
   Python punya, 200) dan `GET /risk` (tanpa caller di web source saat ini).

## Fix Plan (dieksekusi OpenCode, TDD ketat)
### T1 — Python INTI: discovery non-blocking + negative cache + timeout pendek
Files: `services/python/src/llm/registry.py`, `services/python/src/system/endpoints.py`, tests.
- registry.py: `failure_ttl` (default 60 dtk) — setelah gagal, panggilan berikutnya return langsung
  tanpa jaringan sampai window lewat; `threading.Lock` single-flight; httpx timeout 5.0 -> 1.5 dtk.
- endpoints.py: `await asyncio.to_thread(registry.discover_from_gateway, force=False)`.
- Test baru: (a) negative cache (call kedua tidak menembak gateway, health tetap DISCONNECTED),
  (b) expiry window, (c) concurrency: discovery sleep 1 dtk -> `/health` bersamaan < 0.5 dtk
  (mereproduksi failure mode; RED sebelum fix).
### T2 — Python DURABEL: self-load `.env.runtime` saat startup
Files: `services/python/src/env_bootstrap.py` (baru), `services/python/src/main.py` (patch minimal),
`services/python/tests/test_env_bootstrap.py` (baru).
- Loader hanya mengisi key KOSONG (tidak menimpa env eksplisit); file absen = no-op; TIDAK load saat
  pytest (`"pytest" in sys.modules` guard) supaya full suite tetap hijau.
- Dipanggil di lifespan startup main.py (file punya perubahan user — patch 2-4 baris, no reformat).
### T3 — Node kecil: proxy route 404
Files: `apps/api/src/index.ts` (patch, pola sama dengan route research lain ~baris 1021-1056), test
mengikuti pola `apps/api/test/`.
- Tambah `GET /research/strategies` -> sendProxy. TIDAK tambah `/risk` (tanpa caller).
### T4 — OPSIONAL (skip): bedakan "gagal memuat" vs "kosong" di panel Terminal.

## Acceptance
- T1: test baru hijau; test_model_discovery + test_system_endpoints + test_llm* hijau; concurrency test
  membuktikan /health tetap cepat saat discovery lambat.
- T2: test_env_bootstrap hijau; full pytest hijau (baseline 2183 passed, tidak boleh merah).
- T3: `npm run build` hijau; live curl route -> 200.
- Lint: flake8 (max 100, ignore E203,W503) + black --check hijau; tsc/eslint hijau.
- Live (ops, supervisor): restart Python via `scripts/restart-py.ps1` -> `/ai/models` <1 dtk,
  `source=gateway`, state CONNECTED; console tanpa 503; terminal tampil; re-arm bil2.

## Guardrails
- JANGAN commit. JANGAN reformat file lain. Preserve perubahan user (index.ts, main.py, config.py).
- Tanpa dependency baru. Tanpa secret di output. `.env.runtime` read-only (baca saja).
- TDD ketat: test RED dulu -> implementasi -> GREEN.

## Ops setelah merge (supervisor, bukan OpenCode)
1. Restart Python: `powershell -File scripts/restart-py.ps1` (mengekspor .env.runtime).
   CATATAN: `MARKET_FEED_ENABLED=true` di .env.runtime -> feed loop ikut ON setelah restart.
2. Re-select + re-arm terminal `bil2` (state arm in-memory hilang saat restart).
3. Verifikasi live: `/ai/models` cepat + CONNECTED; `/mt5/terminals` tampil; console bersih.
