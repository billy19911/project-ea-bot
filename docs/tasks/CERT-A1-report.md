# CERT-A1 — Laporan CI/Artifacts generator (Gate A)

**Status:** SELESAI — `reports/` berisi 6 artefak, `ci.yml` ter-update, test baru hijau, Gate A live **6/6 true**.
**Repo:** `C:/xampp/htdocs/project-ea-bot` · commit base `bc8f6d8` (semua work uncommitted)
**Lingkungan:** Windows + Git Bash · PowerShell 5.1 (`powershell.exe`) · Python 3.11.16 (venv `services/python/.venv`) · Node v26.7.0

---

## 1. Ringkasan

Halaman Production Certification menampilkan Gate A 0/6 karena collector
`services/python/src/live_readiness/certification_evidence.py` tidak menemukan
artefak bukti apa pun di disk. Tugas ini membuat **generator artefak nyata**
(`scripts/cert_artifacts.ps1`) yang menjalankan perintah CI sungguhan dan
menulis output penuh (plus exit code jujur) ke `reports/`, lalu menjalankannya
sehingga artefak nyata ada di disk.

Collector **tidak diubah** — hanya konsumen. Semua file ditulis di
`reports/` (root repo), di luar direktori yang di-exclude collector
(`temp_pytest`, `.venv`, `node_modules`, `.next`, `dist`, `build`,
`__pycache__`, dir hidden).

---

## 2. Yang dibuat

| File | Jenis | Keterangan |
|---|---|---|
| `scripts/cert_artifacts.ps1` | baru | Generator PowerShell; jalankan perintah nyata, tulis 6 artefak. Mendukung `-Only <step>` (`pytest,node_tests,web_build,typecheck,lint,security`). |
| `reports/pytest-report.txt` | baru | Output lengkap pytest + `EXIT_CODE`. |
| `reports/node_tests.json` | baru | `{command, exit_code, output}` hasil `npm test --workspace=project-ea-bot-api`. |
| `reports/web_build.txt` | baru | Output lengkap `npm run build --workspace=project-ea-bot-web`. |
| `reports/typecheck.txt` | baru | `npx tsc --noEmit` di `apps/web` + `apps/api`. |
| `reports/lint.txt` | baru | flake8 + `black --check src` + eslint (web & api). |
| `reports/security.json` | baru | `{pip_audit, npm_audit}` gabungan. |
| `services/python/tests/test_cert_artifacts_script.py` | baru | 11 test ringan (script ada, artefak parse-able). |
| `.github/workflows/ci.yml` | modifikasi | Langkah CI menulis artefak sama + `actions/upload-artifact`. |

### Detail implementasi script

- **Output penuh, tanpa `head`/`tail`.** Menggunakan
  `System.Diagnostics.Process` + `ReadToEnd()` untuk menangkap stdout **dan**
  stderr.
- **File tetap ditulis walau gagal.** Exit code asli dicatat apa adanya
  (`EXIT_CODE: N`) di akhir setiap bagian.
- **JSON valid tanpa BOM.** PowerShell 5.1 `Set-Content -Encoding UTF8`
  menambahkan BOM (`EF BB BF`) yang membuat JSON tidak valid; script menulis
  lewat `UTF8Encoding($false)` (`Write-Utf8NoBom`) sehingga JSON murni.
- **Resolusi executable.** `npm`/`npx` di mesin ini hanya tersedia sebagai
  shim `.ps1` yang tidak bisa di-`Start()` oleh .NET Process. `Resolve-Executable`
  memilih `npm.cmd`/`npx.cmd` (sibling atau via `where.exe`).
- **pip-audit JSON bersih.** pip-audit menulis ringkasan manusia ke stderr dan
  JSON ke stdout; script juga memakai `-o <tmp.json>` lalu membacanya sebagai
  sumber utama (fallback: parsing output gabungan).
- **Basetemp pytest dibersihkan.** `pytest.ini` memaksa
  `--basetemp=./temp_pytest`. Sisa direktori numbered dari run sebelumnya
  membuat pytest 9.x melempar
  `ValueError: <name> is not a normalized and relative path` pada fixture
  `tmp_path`. Script menghapus `services/python/temp_pytest` (scratch dir yang
  di-exclude collector) sebelum menjalankan pytest agar deterministik.

---

## 3. Perintah yang dijalankan (nyata)

```powershell
# jalur utama
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/cert_artifacts.ps1

# sub-set (dipakai saat iterasi)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/cert_artifacts.ps1 -Only node_tests,security
```

Perintah per artefak (cwd sesuai):

| Artefak | Perintah | cwd |
|---|---|---|
| `pytest-report.txt` | `./.venv/Scripts/python.exe -m pytest -q` | `services/python` |
| `node_tests.json` | `npm test --workspace=project-ea-bot-api` | root |
| `web_build.txt` | `npm run build --workspace=project-ea-bot-web` | root |
| `typecheck.txt` | `npm run typecheck --workspace=project-ea-bot-web` **atau** `npx tsc --noEmit` (web & api) | `apps/web`, `apps/api` |
| `lint.txt` | `flake8 --max-line-length=100 --extend-ignore=E203,W503 src` · `black --check src` · `npm run lint --workspace=project-ea-bot-web` · `npm run lint --workspace=project-ea-bot-api` | `services/python` / root |
| `security.json` | `pip-audit -f json` · `npm audit --json` | `services/python` / root |

---

## 4. Hasil

### 4.1 Ukuran & validitas (`reports/`)

| File | Size | Valid |
|---|---:|---|
| `pytest-report.txt` | 3 490 B | teks non-kosong ✓ |
| `node_tests.json` | 4 782 B | JSON valid ✓ (`command`, `exit_code`, `output`) |
| `web_build.txt` | 3 857 B | teks non-kosong ✓ |
| `typecheck.txt` | 520 B | teks non-kosong ✓ |
| `lint.txt` | 3 289 B | teks non-kosong ✓ |
| `security.json` | 65 610 B | JSON valid ✓ (`pip_audit`, `npm_audit`) |

Semua **> 0 byte** dan berisi output nyata (bukan dummy).

### 4.2 Exit code jujur per perintah

| Perintah | exit | Catatan |
|---|---:|---|
| pytest | **0** | `2280 passed, 1 warning in 79.48s` (termasuk 11 test CERT-A1 baru) |
| `npm test --workspace=project-ea-bot-api` | **0** | `npm run build && node --test` lulus |
| web build | **0** | Next.js 15.5.25 compiled + 42/42 static pages |
| typecheck web | **0** | `npx tsc --noEmit` bersih |
| typecheck api | **0** | `npx tsc --noEmit` bersih |
| flake8 | **1** | 5 temuan (lihat 4.3) |
| `black --check src` | **1** | 7 file "would reformat" |
| eslint web | **0** | bersih |
| eslint api | **0** | 6 warning (0 error) |
| pip-audit | **1** | 14 kerentanan (exit 1 = ditemukan) |
| `npm audit --json` | **0** | 0 kerentanan |

### 4.3 Temuan lint (jujur, bukan blocker Gate A)

`lint.txt` mencatat ketidakbersihan nyata (Gate A hanya butuh artefaknya ada):

```
flake8 (services/python):
  structure_analyst.py:100 E501 (102>100)
  structure_analyst.py:123 E501 (106>100)
  structure_analyst.py:124 E501 (109>100)
  structure_analyst.py:365 E741 ambiguous variable name 'l'
  research/engine.py:16  F401 'trading.indicators.ema' imported but unused

black --check:
  7 file would be reformatted (telegram/transport.py, system/settings_store.py,
  telegram/gateway.py, system/endpoints.py, agents/analysts/momentum_analyst.py,
  telegram/signal_lifecycle.py, agents/analysts/structure_analyst.py)

eslint (api): 6 warning @typescript-eslint/no-unused-vars (0 error, exit 0)
```

### 4.4 Keamanan (jujur)

`pip_audit` exit **1** (bukan error — berarti ada kerentanan): 82 dependensi
diaudit, **14 kerentanan** pada 2 paket:
- `pip` (12) — `PYSEC-2026-*` (CVE-2025-8869, CVE-2026-1703, dll.)
- `setuptools` (2) — `PYSEC-2026-3447` (CVE-2026-59890)

`npm_audit` exit **0**: 0 kerentanan (0 info/low/moderate/high/critical).

### 4.5 Catatan web build vs dugaan `envSchema.ts:86`

Brief menyebut potensi TS error pre-existing di `envSchema.ts:86`. Pada run ini
**tidak ada** error tersebut — `npm run build` (exit 0) dan `npx tsc --noEmit`
(exit 0) keduanya bersih. Pencarian `grep -rl envSchema apps/web` **tidak
menemukan** file itu di tree saat ini, jadi kondisi tersebut sudah tidak berlaku
(tidak ada yang perlu di-workaround). Dicatat apa adanya.

---

## 5. Update CI (`.github/workflows/ci.yml`)

Edit minimal, langkah existing tidak dirusak:

- Job **`test`**:
  - `Run backend tests` → menulis `reports/pytest-report.txt` (full output +
    `EXIT_CODE`).
  - `Run Node API tests` → menulis `reports/node_tests.json`
    (`{command, exit_code, output}` via `node -e`).
  - `Lint frontend` / `Lint backend` → menulis `reports/lint.txt`.
  - `Type-check frontend` → menulis `reports/typecheck.txt`.
  - **Baru:** `Upload Gate A certification artifacts` (`actions/upload-artifact@v4`,
    `if: always()`, path `reports/`, retention 7 hari).
- Job **`build`**: `Build frontend` → menulis `reports/web_build.txt`; ditambah
  step upload artefak `cert-gate-a-web-build`.
- Job **`security`**: step audit menulis `reports/security.json`
  (`{pip_audit, npm_audit}`); ditambah step upload artefak
  `cert-gate-a-security`.

YAML divalidasi: `python -c "import yaml; yaml.safe_load(...)"` → **valid**.
Desain CI kini konsisten dengan gate (nama artefak identik dengan yang di-glob
collector).

---

## 6. Test baru

`services/python/tests/test_cert_artifacts_script.py` — **11 test**, **PASSED**,
runtime **0.62s** (ringan; tidak memanggil pytest penuh/heavy command):

```
TestGeneratorScript
  test_script_exists_and_non_empty ......................... PASSED
  test_script_mentions_all_artifact_names ................... PASSED
  test_reports_dir_is_not_excluded_by_collector ............. PASSED
TestGeneratedArtifacts
  test_artifact_present_non_empty_and_parseable[lint.txt] ... PASSED
  test_artifact_present_non_empty_and_parseable[node_tests.json] PASSED
  test_artifact_present_non_empty_and_parseable[pytest-report.txt] PASSED
  test_artifact_present_non_empty_and_parseable[security.json] PASSED
  test_artifact_present_non_empty_and_parseable[typecheck.txt] PASSED
  test_artifact_present_non_empty_and_parseable[web_build.txt] PASSED
  test_node_tests_json_shape ................................ PASSED
  test_security_json_shape .................................. PASSED
```

Test `skip` (bukan gagal) bila artefak belum digenerate, sehingga suite tetap
hijau di environment bersih.

---

## 7. Verifikasi live Gate A (service hidup)

`curl -s -H "X-API-Key: <PYTHON_API_KEY dari .env.runtime>" http://127.0.0.1:8787/v2/certification/gate`

```json
Gate A passed: true
checks: {
  "python_tests": true,
  "node_tests": true,
  "web_build": true,
  "type_check": true,
  "lint": true,
  "security_scan": true
}
failed: []
```

`evidence_source` tiap check menunjuk ke file nyata:
`file:reports/pytest-report.txt`, `file:reports/node_tests.json`,
`file:reports/web_build.txt`, `file:reports/typecheck.txt`,
`file:reports/lint.txt`, `file:reports/security.json`.

**Gate A 6/6 benar (live).** Gate lain (B–E) tetap `NOT_READY`/`null` — di luar
cakupan CERT-A1.

---

## 8. Kegagalan / catatan jujur

1. **PowerShell 5.1 vs .NET Core API.** Awalnya memakai
   `ProcessStartInfo.ArgumentList` (tidak ada di .NET Framework) → error.
   Diganti ke string `Arguments` dengan quoting manual. `npm`/`npx` shim `.ps1`
   tidak bisa di-`Start()` → ditambah resolver ke `*.cmd`.
2. **pytest 9.x `tmp_path` ValueError.** Run kedua gagal (exit 1, 3 setup
   error) karena sisa `temp_pytest` dari run pertama. Diperbaiki: script
   membersihkan `temp_pytest` sebelum pytest. Setelah itu run konsisten exit 0
   (2280 passed).
3. **BOM JSON.** `Set-Content -Encoding UTF8` menambah BOM → JSON invalid;
   diperbaiki dengan tulis UTF-8 tanpa BOM.
4. **pip-audit exit 1** berarti ada kerentanan, bukan crash — dipertahankan
   sebagai fakta (14 vuln pada pip & setuptools).
5. **Lint tidak bersih** (flake8 5 temuan, black 7 file). Tidak diubah karena
   di luar cakupan dan brief melarang reformat file lain; Gate A hanya butuh
   artefaknya ada.
6. **`envSchema.ts:86`** tidak ditemukan di tree saat ini; web build &
   typecheck bersih (lihat 4.5).

---

## 9. Guardrails — dipatuhi

- **Tidak ada** `git add`/`commit`/`stash`; semua perubahan uncommitted
  (`git status` menunjukkan `?? reports/`, `?? scripts/cert_artifacts.ps1`,
  `?? services/python/tests/test_cert_artifacts_script.py`, `M ci.yml`).
- Tidak menyentuh `services/python/src/config.py`, `services/python/src/main.py`,
  `apps/api/src/index.ts`.
- Tidak menyentuh `CHANGELOG.md`, `docs/audit/*`, `docs/hermes_multibot/*`.
- Tidak mengubah `certification_evidence.py` (collector).
- `reports/` di root, di luar dir yang di-exclude collector.
