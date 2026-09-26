# FIX-503 T1 — Laporan: Discovery non-blocking + negative cache + timeout pendek

Status: **GREEN** (RED terbukti lebih dulu).
Tanggal: 2026-09-26
Scope: `services/python` saja. Tidak menyentuh `apps/*`, `config.py`, `main.py`.
Tanpa dependency baru. Tanpa `git add`/`git commit`.

## Ringkasan

`ModelRegistry.discover_from_gateway()` dipanggil SINKRON di dalam handler async
`GET /ai/models`, sehingga event loop Python terblokir 2-9 detik saat gateway LLM
tidak terjangkau (env `NINE_ROUTER_BASE_URL` kosong -> default internet 404). Cache
hanya terisi saat SUKSES -> tiap request mengulang jaringan -> request lain antre ->
proxy Node timeout 5 dtk -> 503.

Perbaikan:
1. **Negative cache** (failure window default 60 dtk) — setelah gagal, panggilan
   berikutnya return langsung tanpa jaringan sampai window lewat.
2. **Single-flight** (`threading.Lock` + double-check) — panggilan bersamaan
   menyatu menjadi tepat 1 percobaan jaringan.
3. **Timeout discovery 1.5 dtk** — hanya untuk jalur discovery/`GET /models`;
   timeout chat/streaming tidak diubah.
4. **Handler non-blocking** — `await asyncio.to_thread(...)` agar event loop bebas.
   Bentuk respons `/ai/models` tidak berubah.

## Angka reproduksi (sebelum vs sesudah)

Command reproduksi (dari `services/python`):

    ./.venv/Scripts/python.exe -c "import os; os.environ.pop('NINE_ROUTER_BASE_URL', None); import time; from src.llm.registry import ModelRegistry; r=ModelRegistry(); t=time.time(); r.discover_from_gateway(); print('call1_s', round(time.time()-t,2)); t=time.time(); r.discover_from_gateway(); print('call2_s', round(time.time()-t,2))"

| | call1_s | call2_s |
|---|---|---|
| **Sebelum fix** | 2.06 | 0.28 (tetap ada panggilan jaringan baru) |
| **Sesudah fix** | 0.76 | 0.0 (tanpa jaringan baru) |
| Target | <= 2.0 | <= 0.05 |

Catatan: angka `call1`/`call2` bervariasi mengikuti latensi jaringan live (rentang
historis 1.75-8.7 dtk). Yang penting secara struktural: **sebelum fix call2 selalu
menembak jaringan lagi** (cache hanya mengisi saat sukses); sesudah fix call2 ~0 dtk
tanpa percobaan jaringan karena negative cache. Timeout discovery 1.5 dtk membatasi
call1.

## RED -> GREEN

Test baru: `services/python/tests/test_discovery_nonblocking.py`

- RED (sebelum implementasi): **4 failed, 1 passed** —
  `test_negative_cache_after_failure`, `test_failure_ttl_expiry`,
  `test_single_flight_concurrent`, `test_ai_models_endpoint_nonblocking` gagal;
  `test_negative_cache_then_recovery_success` lulus (hanya menguji perilaku lama).
- GREEN (sesudah implementasi): **5 passed**.

Test yang ditambahkan:
- `test_negative_cache_after_failure` — call kedua dalam window: tanpa jaringan, <= 0.05 dtk, health tetap DISCONNECTED, source=defaults.
- `test_negative_cache_then_recovery_success` — window lewat + gateway sehat -> cache terisi (CONNECTED).
- `test_failure_ttl_expiry` — dalam window tanpa retry; lewat window retry jalan lagi (via `failure_ttl` kecil).
- `test_single_flight_concurrent` — 4 thread saat discovery lambat -> tepat 1 percobaan jaringan.
- `test_ai_models_endpoint_nonblocking` — `/ai/models` (discovery sleep 1 dtk) + `/health` pada event loop yang sama -> `/health` <= 0.5 dtk.

## File diubah

| File | Perubahan |
|---|---|
| `services/python/src/llm/registry.py` | `failure_ttl=60.0`, `_last_failure`, `threading.Lock` + double-check single-flight, negative cache, konstanta `DISCOVERY_TIMEOUT_S=1.5`, timeout raw fetch 5.0 -> 1.5, fallback SDK `NineRouterClient(timeout=DISCOVERY_TIMEOUT_S)`. |
| `services/python/src/system/endpoints.py` | `import asyncio`; handler `ai_models()` memakai `await asyncio.to_thread(registry.discover_from_gateway, force=False)`. |
| `services/python/tests/test_discovery_nonblocking.py` | Baru — 5 test T1. |

`services/python/src/config.py` dan `services/python/src/main.py` **tidak disentuh**.
Default base URL di `nine_router.py` **tidak diubah** (hanya timeout instance
discovery lewat parameter `timeout`).

## Hasil verifikasi

1. Targeted:

        ./.venv/Scripts/python.exe -m pytest tests/test_discovery_nonblocking.py tests/test_model_discovery.py tests/test_system_endpoints.py -q
        -> 34 passed

2. Full suite:

        ./.venv/Scripts/python.exe -m pytest -q
        -> 2188 passed, 1 warning in ~58s
        (baseline 2183 + 5 test T1 baru; TIDAK ada regresi)

3. flake8:

        ./.venv/Scripts/python.exe -m flake8 src/llm/registry.py src/system/endpoints.py tests/test_discovery_nonblocking.py --max-line-length=100 --extend-ignore=E203,W503
        -> exit 0

        ./.venv/Scripts/python.exe -m flake8 src tests --max-line-length=100 --extend-ignore=E203,W503
        -> 14 error PRE-EXISTING di 3 file yang TIDAK saya sentuh:
           src/agents/analysts/structure_analyst.py (E501 x3, E741),
           src/research/engine.py (F401),
           tests/test_research_engine.py (E501 x9).
           File-file ini sudah dimodifikasi oleh pekerjaan user lain (git status: M).

4. black:

        ./.venv/Scripts/python.exe -m black --check src/llm/registry.py tests/test_discovery_nonblocking.py
        -> exit 0

        ./.venv/Scripts/python.exe -m black --check src/llm/registry.py src/system/endpoints.py tests/test_discovery_nonblocking.py
        -> exit 1 (HANYA `src/system/endpoints.py`, PRE-EXISTING)

## Penyimpangan yang perlu diputuskan: black `src/system/endpoints.py`

`black --check src/system/endpoints.py` **gagal**, tetapi kegagalannya **sudah ada
sebelum perubahan ini** dan **bukan berasal dari baris yang saya tambah**:

- `git show HEAD:services/python/src/system/endpoints.py` juga gagal `black --check`
  pada line-length 100 (pyproject `[tool.black] line-length = 100`).
- Repo campur format: `registry.py` sudah terformat 100, `endpoints.py` masih
  formatter 88. Full `black --check src/ tests/` melaporkan 12 file pre-existing
  "would reformat" (endpoints.py termasuk).
- Baris yang saya ubah (`import asyncio` + `await asyncio.to_thread(...)`) sudah
  **black-clean** pada 100.

Black ingin merapikan 4 blok pre-existing yang tidak berhubungan dengan FIX-503
(`_telegram_configuration`, `_apply_to_runtime`, dekorator `/settings`,
`learning_analytics`). Merapikannya berarti **reformat file** yang dilarang oleh
"Larangan: JANGAN reformat file lain (patch minimal saja)". Karena larangan ini
eksplisit, saya mempertahankan patch minimal (tidak me-reformat blok lain) dan
melaporkan konflik ini alih-alih memperluas diff.

Jika tim ingin `black --check endpoints.py` exit 0, jalankan `black
services/python/src/system/endpoints.py` (perubahan 100% mekanis, tanpa perubahan
logika) — keputusan tersebut sengaja tidak saya ambil agar tidak melanggar larangan
"patch minimal".

## Penyesuaian test lama

Tidak ada test lama yang dihapus/dilemahkan. Satu masalah urutan test sempat muncul:

- `tests/test_latency_and_news_resilience.py::test_scheduler_wake_processes_immediately`
  gagal HANYA saat dijalankan setelah file test baru, karena `asyncio.run()` menutup
  event loop dan tidak menyisakan current loop untuk test sinkron berikutnya
  (`RuntimeError: There is no current event loop`).
- Perbaikan dilakukan di **file test baru saya** (bukan test lama): helper `_run_coro`
  membuat loop privat lalu memulihkan current event loop setelahnya. Setelah ini
  full suite 2188 passed tanpa mengubah test lama.

## Sisa risiko

1. **Negative cache 60 dtk tetap mengulang tiap window.** Setelah 60 dtk, satu
   percobaan jaringan (<=1.5 dtk) dijalankan; selama gateway belum pulih setidaknya
   satu request per window membayar ~1.5 dtk. Ini disengaja (recovery). Bila ingin
   lebih agresif, jadikan `failure_ttl` konfigurabel.
2. **Single-flight memakai `threading.Lock` global per-registry.** Satu request yang
   memegang lock (maksimal ~1.5 dtk) membuat request bersamaan menunggu di lock, bukan
   menembak jaringan. Karena handler memakai `asyncio.to_thread`, penantian ini terjadi
   di worker thread dan tidak memblokir event loop.
3. **Jalur chat/streaming tidak diubah** — timeout-nya tetap; tidak ada regresi yang
   terdeteksi pada test LLM.
4. **Default base URL dibiarkan** — fix ini tidak mengubah fallback internet; dengan
   env yang benar (T2) discovery akan sukses. Tanpa env, tetap 404 tetapi kini murah
   dan non-blocking.
5. **black endpoints.py** — lihat bagian penyimpangan di atas.
