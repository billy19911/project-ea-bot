# T1 — FIX-503: Discovery non-blocking + negative cache + timeout pendek

Repo: C:/xampp/htdocs/project-ea-bot (Windows; shell Git Bash).
Konteks lengkap: docs/plans/FIX-503-404-LATENCY.md (bagian T1). Baca dulu.
Scope: services/python saja. Jangan sentuh apps/*.

## Bug (root cause sudah dikonfirmasi)
Handler `GET /ai/models` (services/python/src/system/endpoints.py) memanggil
`ModelRegistry.discover_from_gateway()` SINKRON di dalam handler async -> event loop Python
terblokir 1.75-8.7 detik saat gateway LLM tidak terjangkau (env NINE_ROUTER_BASE_URL kosong ->
fallback default internet https://api.9router.com/v1 -> 404 + retry). Semua request lain antre;
proxy Node (apps/api/src/pythonClient.ts, timeout 5 dtk) menjawab 503. Cache hanya terisi saat
SUKSES, jadi tiap request mengulang panggilan jaringan.

## Reproduksi (jalankan SEBELUM fix; simpan angkanya)
cd /c/xampp/htdocs/project-ea-bot/services/python
./.venv/Scripts/python.exe -c "import os; os.environ.pop('NINE_ROUTER_BASE_URL', None); import time; from src.llm.registry import ModelRegistry; r=ModelRegistry(); t=time.time(); r.discover_from_gateway(); print('call1_s', round(time.time()-t,2)); t=time.time(); r.discover_from_gateway(); print('call2_s', round(time.time()-t,2))"
Ekspektasi lama: call1 dan call2 sama-sama 2-9 dtk (tidak ada negative cache -> selalu jaringan).

## Target numerik (acceptance)
1. Gateway unreachable: panggilan pertama <= 2.0 dtk (timeout discovery 1.5 dtk; maksimal 1
   percobaan jaringan per window).
2. Panggilan KEDUA dalam failure window (default 60 dtk): <= 0.05 dtk, TANPA panggilan jaringan baru.
3. Window lewat -> percobaan jaringan berikutnya boleh jalan lagi (recovery; sukses mengisi cache
   seperti perilaku lama).
4. Single-flight: 4 panggilan bersamaan saat discovery lambat -> tepat 1 percobaan jaringan.
5. Event loop bebas: selama discovery lambat (sleep 1 dtk), endpoint lain (/health) tetap <= 0.5 dtk.
6. Perilaku sukses tidak berubah (discovery sukses -> cache model terisi; test lama tetap hijau).

## Implementasi (patch minimal)
A. services/python/src/llm/registry.py
   - Negative cache: simpan timestamp gagal terakhir; konstanta failure_ttl = 60.0 detik.
     Jika now - last_failure < failure_ttl -> return cepat (state/defaults sekarang) tanpa jaringan.
   - Single-flight: threading.Lock dengan double-check di dalam lock.
   - Timeout jaringan discovery: 1.5 dtk, maksimal 1 percobaan per window (tanpa retry berantai).
     Cari di mana timeout httpx dipakai jalur discovery (kemungkinan services/python/src/llm/nine_router.py)
     dan turunkan HANYA untuk panggilan discovery/list_models — JANGAN ubah timeout chat/endpoint lain.
B. services/python/src/system/endpoints.py
   - Handler ai_models(): panggil discovery lewat `await asyncio.to_thread(...)` supaya tidak
     memblokir event loop; bentuk respons tidak berubah.
Jangan sentuh services/python/src/config.py dan services/python/src/main.py (ada perubahan user lain).

## TDD (wajib, urut)
1. RED dulu: services/python/tests/test_discovery_nonblocking.py
   a. test_negative_cache_after_failure
   b. test_failure_ttl_expiry (monkeypatch waktu atau failure_ttl kecil)
   c. test_single_flight_concurrent (4 thread)
   d. test_ai_models_endpoint_nonblocking (discovery lambat; /health tetap cepat; pola test ikut
      tests/test_system_endpoints.py yang sudah ada)
   Jalankan -> harus GAGAL dulu (bukti reproduksi).
2. Implementasi minimal -> GREEN.
3. Verifikasi:
   ./.venv/Scripts/python.exe -m pytest tests/test_discovery_nonblocking.py tests/test_model_discovery.py tests/test_system_endpoints.py -q
   ./.venv/Scripts/python.exe -m pytest -q    (baseline: 2183 passed; tidak boleh ada regresi)
   ./.venv/Scripts/python.exe -m flake8 src tests --max-line-length=100 --extend-ignore=E203,W503
   ./.venv/Scripts/python.exe -m black --check src/llm/registry.py src/system/endpoints.py tests/test_discovery_nonblocking.py

## Larangan
- JANGAN git commit / git add. JANGAN reformat file lain (patch minimal saja).
- Tanpa dependency baru. Tanpa secret/nilai env di output atau log.
- Jangan ubah default base URL di nine_router.py (fix ini soal non-blocking + cache, bukan default).
- Jangan start/stop service apa pun; cukup unit test.
- Jika test lama gagal karena perilaku baru, JANGAN hapus/lemahkan test: sesuaikan seminimal mungkin
  dan jelaskan di laporan.

## Laporan
Tulis docs/tasks/FIX-503-T1-report.md: status RED->GREEN, angka call1/call2 sebelum vs sesudah,
daftar file diubah, hasil pytest penuh + flake8/black exit code, sisa risiko.
