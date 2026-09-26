# T2 — FIX-503: Python self-load .env.runtime saat startup (hanya isi key kosong)

Repo: C:/xampp/htdocs/project-ea-bot (Windows; shell Git Bash).
Konteks: docs/plans/FIX-503-404-LATENCY.md (bagian T2). Baca dulu.
Dependensi: T1 sudah selesai — JANGAN sentuh file T1 (src/llm/registry.py, src/system/endpoints.py,
tests/test_discovery_nonblocking.py).
Scope: services/python saja.

## Masalah
Service Python kadang di-start lewat jalur yang TIDAK mengekspor env (mis. `python main.py` manual
atau proses lain), sehingga NINE_ROUTER_BASE_URL kosong -> discovery menembak internet. Node sudah
punya pola ini (apps/api/src/loadEnv.ts, baca .env.runtime, isi hanya yang kosong); Python belum.

## Target
- Startup Python memuat C:/xampp/htdocs/project-ea-bot/.env.runtime dan mengisi HANYA env var yang
  belum ada / bernilai kosong. Env eksplisit TIDAK boleh ditimpa.
- File tidak ada = no-op (tanpa error). Nilai TIDAK boleh di-log (cukup jumlah key yang di-load).
- Saat pytest: bootstrap TIDAK aktif (guard di call-site main.py: `if "pytest" not in sys.modules`).

## Implementasi
- File baru: services/python/src/env_bootstrap.py
  `def load_runtime_env(path=None) -> int` — parser .env sederhana (KEY=VALUE; abaikan komentar #
  dan baris kosong; dukung nilai dengan kutip tunggal/ganda; hanya isi key kosong/belum ada;
  kembalikan jumlah key yang di-load). Default path: .env.runtime di root repo (hitung dari __file__
  naik ke root; fallback C:/xampp/htdocs/project-ea-bot/.env.runtime).
- Patch minimal: services/python/src/main.py — di lifespan startup, panggil load_runtime_env()
  SEBELUM komponen membaca env, dengan guard pytest. File ini punya perubahan user lain:
  patch 2-5 baris, JANGAN reformat, JANGAN ubah baris lain.
- Jangan sentuh services/python/src/config.py.

## TDD
1. RED dulu: services/python/tests/test_env_bootstrap.py
   a. test_loads_missing_keys (tmp_path)
   b. test_does_not_override_existing
   c. test_missing_file_noop
   d. test_quotes_and_comments
2. Implementasi -> GREEN.
3. Verifikasi:
   ./.venv/Scripts/python.exe -m pytest tests/test_env_bootstrap.py -q
   ./.venv/Scripts/python.exe -m pytest -q    (baseline 2183 passed)
   ./.venv/Scripts/python.exe -m flake8 src tests --max-line-length=100 --extend-ignore=E203,W503
   ./.venv/Scripts/python.exe -m black --check src/env_bootstrap.py src/main.py tests/test_env_bootstrap.py

## Larangan
- JANGAN git commit / git add. JANGAN reformat file lain. Tanpa dependency baru (tanpa python-dotenv).
- JANGAN menulis/mengubah file .env.runtime (read-only; test pakai tmp_path). Tanpa nilai secret di output.
- Jangan start/stop service apa pun; cukup unit test.

## Laporan
Tulis docs/tasks/FIX-503-T2-report.md: status RED->GREEN, file diubah, hasil pytest + lint, sisa risiko.
