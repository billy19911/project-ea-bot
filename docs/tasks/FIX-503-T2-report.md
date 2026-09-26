# FIX-503 T2 — Python self-load `.env.runtime` saat startup

Status: SELESAI (RED -> GREEN). Tanggal: 2026-09-26.
Scope: `services/python` saja. Tanpa commit, tanpa dependency baru.

## Tujuan
Service Python kadang di-start lewat jalur yang TIDAK mengekspor env (mis.
`python main.py` manual / proses lain), sehingga `NINE_ROUTER_BASE_URL` kosong
-> discovery menembak internet. T2 menambahkan self-loader `.env.runtime` di
startup (paritas dengan `apps/api/src/loadEnv.ts`), mengisi HANYA env var yang
belum ada / kosong.

## Hasil TDD

### 1. RED
`tests/test_env_bootstrap.py` dibuat lebih dulu; run pertama gagal koleksi:
```
ImportError: cannot import name 'env_bootstrap' from 'src'
1 error in 0.22s
```

### 2. GREEN
Implementasi `src/env_bootstrap.py` + patch `src/main.py`. Hasil:
```
tests/test_env_bootstrap.py ..... [100%]
5 passed in 0.69s
```

## File diubah
| File | Jenis | Catatan |
| --- | --- | --- |
| `services/python/src/env_bootstrap.py` | baru | `load_runtime_env(path=None) -> int`. Parser `.env` sederhana: `KEY=VALUE`, abaikan `#` dan baris kosong, dukung kutip tunggal/ganda & `export `, isi hanya key kosong/belum ada, kembalikan jumlah key yang di-load. Default path = `.env.runtime` di root repo (dihitung `__file__.parents[3]`), fallback `C:/xampp/htdocs/project-ea-bot/.env.runtime`. File absen = `0` (no-op, tanpa error). Nilai TIDAK pernah di-log — hanya jumlah key + path. |
| `services/python/src/main.py` | patch minimal | Tambah `import sys` dan blok bootstrap ~8 baris di awal `lifespan()` (SEBELUM komponen membaca env), dengan guard `if "pytest" not in sys.modules`. Tidak ada reformat / perubahan baris lain. |
| `services/python/tests/test_env_bootstrap.py` | baru | 5 test: `test_loads_missing_keys`, `test_does_not_override_existing`, `test_blank_existing_is_filled`, `test_missing_file_noop`, `test_quotes_and_comments`. Semua pakai `tmp_path` + `monkeypatch`; TIDAK menyentuh `.env.runtime` asli. |

`src/config.py` TIDAK disentuh. File T1 (`src/llm/registry.py`,
`src/system/endpoints.py`, `tests/test_discovery_nonblocking.py`) TIDAK disentuh.

## Verifikasi
| Perintah | Hasil |
| --- | --- |
| `pytest tests/test_env_bootstrap.py -q` | `5 passed` |
| `pytest -q` (full suite) | `2193 passed, 1 warning in 69.96s` — nol regresi |
| `flake8 src/env_bootstrap.py src/main.py tests/test_env_bootstrap.py --max-line-length=100 --extend-ignore=E203,W503` | exit 0 (bersih) |
| `black --check src/env_bootstrap.py src/main.py tests/test_env_bootstrap.py` | `3 files would be left unchanged` (exit 0) |

Catatan lint: `flake8 src tests` secara keseluruhan masih melaporkan pelanggaran
PRE-EXISTING di file di luar scope yang tidak saya ubah:
`src/agents/analysts/structure_analyst.py` (E501/E741),
`src/research/engine.py` (F401), `tests/test_research_engine.py` (E501). Ketiga
file itu sudah berstatus `M` (modified) sebelum task ini — bukan dari T2.

## Perilaku
- File ada + key kosong -> diisi, increment counter; key terisi -> dilewati
  (env eksplisit menang); key blank (`""`) -> diisi.
- File tidak ada / tidak bisa dibaca / parsing aneh -> `return 0` tanpa error.
- Di bawah pytest, blok di `main.py` di-skip via guard `"pytest" not in sys.modules`,
  jadi suite tidak pernah mewarisi secret runtime.
- Nilai tidak ada di output log (hanya `Loaded N runtime env key(s) from <path>`).

## Sisa risiko / catatan
- `settings` (config.py) di-instantiate di module import (baris ~23), SEBELUM
  `lifespan()` berjalan. Karena `env_bootstrap` hanya mengisi saat lifespan
  startup, var yang dibaca config pada import-time (mis. `SCHEDULER_ENABLED`,
  `MT5_LIVE_DATA`) TIDAK ikut terisi oleh loader ini. T2 dirancang sesuai
  permintaan ("call-site main.py, sebelum komponen membaca env") dan target
  utama `NINE_ROUTER_BASE_URL` dibaca lazily oleh `NineRouterClient`/registry,
  sehingga tetap terisi. Jika kelak ingin mengisi config import-time juga, perlu
  memanggil `load_runtime_env()` di paling atas `main.py` sebelum `from .config import settings`.
- Loader mengasumsikan `.env.runtime` format sederhana; nilai multi-baris atau
  `${VAR}` expansion tidak didukung (tidak dibutuhkan untuk kasus ini).
- `.env.runtime` tetap read-only: tidak ada kode yang menulisnya.
