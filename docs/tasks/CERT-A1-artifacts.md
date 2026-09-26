# CERT-A1 — CI/Artifacts generator (Gate A)

Kamu bekerja di repo `C:/xampp/htdocs/project-ea-bot` (Windows, Git Bash). Bahasa laporan: Indonesia.

## Konteks
Halaman Production Certification menampilkan Gate A 0/6. Gate A mencari bukti artefak NYATA di disk lewat collector
`services/python/src/live_readiness/certification_evidence.py` (glob: `**/pytest*.txt`, `**/node_tests*.json`,
`**/web_build*.txt`, `**/typecheck*.txt`|`**/tsc*.txt`, `**/lint*.txt`|`**/flake8*.txt`, `**/security*.json`|`**/bandit*.json`).
Artefak itu belum pernah digenerate. Tugasmu: buat generator artefak + jalankan supaya artefak NYATA ada di disk.

## Deliverable
1. **Script baru `scripts/cert_artifacts.ps1`** (PowerShell) yang menjalankan perintah NYATA dan menulis:
   - `reports/pytest-report.txt` ← cwd `services/python`: `./.venv/Scripts/python.exe -m pytest -q` (tulis SEMUA output, termasuk exit code di akhir file)
   - `reports/node_tests.json` ← `npm test --workspace=project-ea-bot-api` (format JSON: `{"command": ..., "exit_code": N, "output": "<stdout+stderr>"}`; jika script test tidak ada, jalankan `npm run test --workspace=project-ea-bot-api` dan catat apa adanya)
   - `reports/web_build.txt` ← `npm run build --workspace=project-ea-bot-web`
   - `reports/typecheck.txt` ← type-check nyata: web `npm run typecheck --workspace=project-ea-bot-web` (atau `npx tsc --noEmit` di `apps/web`), API `npx tsc --noEmit` di `apps/api`
   - `reports/lint.txt` ← `services/python/.venv/Scripts/python.exe -m flake8 --max-line-length=100 --extend-ignore=E203,W503 src` (cwd `services/python`) + `black --check src` + `npm run lint --workspace=project-ea-bot-web` + `npm run lint --workspace=project-ea-bot-api`
   - `reports/security.json` ← `pip-audit -f json` (cwd `services/python`; jika pip-audit tidak ada → tulis `{"pip_audit": {"error": "not installed", "exit_code": -1}}`) + `npm audit --json` (root); gabung `{"pip_audit": ..., "npm_audit": ...}`
   - Semua file ditulis di `reports/` (root repo). Buat dir jika belum ada.
   - Setiap perintah: **jangan pipe ke head/tail**; tulis output penuh; file tetap ditulis walau perintah gagal (catat exit code jujur).
2. **Jalankan script** sampai selesai (full pytest bisa 10–20 menit — jalankan di background dengan output ke file, lalu cek berkala).
3. **Update `.github/workflows/ci.yml`**: tambahkan langkah CI yang menulis artefak sama (pytest report txt, node tests json, web build txt, lint txt, security json) dan `actions/upload-artifact` supaya desain CI konsisten dengan gate. Jangan rusak langkah existing — edit minimal (append langkah; boleh modifikasi langkah test existing agar menulis file).
4. **Test baru** `services/python/tests/test_cert_artifacts_script.py` (atau nama serupa): verifikasi script file ada, dan artefak yang dihasilkan parse-able (json valid; txt non-kosong). Test ringan, tidak menjalankan full pytest dari dalam pytest.

## Guardrails
- **DILARANG commit / git add / git stash.** Tinggalkan uncommitted.
- Jangan reformat file lain. Jangan sentuh `services/python/src/config.py`, `services/python/src/main.py`, `apps/api/src/index.ts` (ada perubahan user).
- Jangan sentuh `CHANGELOG.md`, `docs/audit/*`, `docs/hermes_multibot/*`.
- Jangan ubah `certification_evidence.py` (collector) — tugas ini hanya menghasilkan artefak.
- `reports/` jangan ditaruh dalam dir yang di-exclude collector (temp_pytest, .venv, node_modules, .next, dist, build, __pycache__, dir hidden).

## Acceptance / verifikasi sendiri
- `reports/` berisi 6 file, semua size > 0, JSON valid, isi = output nyata (bukan dummy).
- Live cek: `curl -s -H "X-API-Key: <baca dari .env.runtime baris PYTHON_API_KEY>" http://127.0.0.1:8787/v2/certification/gate` → Gate A 6/6 true (jika service hidup). Catat hasil apa adanya.
- Tulis laporan `docs/tasks/CERT-A1-report.md` (Indonesia): apa yang dibuat, perintah dijalankan, hasil, kegagalan jujur (mis. web build TS error pre-existing `envSchema.ts:86` — catat saja), bukti file.

## Selesai = 
`reports/*` ada + ci.yml update + test baru hijau + report tertulis + gate A live 6/6 (atau jelaskan jujur kenapa belum).
