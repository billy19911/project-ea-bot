# CERT-D1 — Ops drills (Gate D)

Kamu bekerja di repo `C:/xampp/htdocs/project-ea-bot` (Windows, Git Bash). Bahasa laporan: Indonesia.
Prerequisite: CERT-B2 selesai (kill switch clear, service stabil). Drills mengganggu service live — jalankan berurutan, jangan paralel.

## Konteks
Halaman Production Certification menampilkan Gate D 0/7 dengan alasan "drill operasional belum dijalankan".
Tidak ada sumber bukti drill di collector. Tugasmu: buat evidence store + runner drill NYATA + wiring collector.

## Deliverable
1. **Collector** — ⚠️ SUDAH DI-WIRE ORCHESTRATOR di `certification_evidence.py` (`_collect_gate_d(drills_path=None)`): baca `services/python/logs/ops_drills.jsonl` (env override `OPS_DRILLS_PATH`, param override `drills_path`), format per baris `{"drill": ..., "status": "passed", "at": ..., "method": ...}`, record terakhir per drill menang, `passed` → True + reason, absen → unknown. **JANGAN edit `certification_evidence.py`.**
   - Tugasmu: tests collector di file BARU `services/python/tests/test_ops_drills.py` (tmp store + param override; record → True + reason; absen → unknown; status failed → False; file rusak → unknown).
2. **Runner `scripts/run_ops_drills.py`** (Python; rollback + health check sebelum/sesudah tiap drill):
   ⚠️ **Kamu HANYA menulis runner + collector + tests. JANGAN menjalankan drill nyata** (drill = orchestrator yang jalankan; drill mengganggu service live dan bisa menggantung prosesmu). Runner harus:
   - Punya CLI `--drill <name>` (jalankan satu drill) dan `--all` (semua, berurutan), timeout per drill, rollback di `finally`, tulis record ke `ops_drills.jsonl`.
   - `mt5_restart` — stop proses terminal MT5 → start ulang → verifikasi reconnect + service sehat.
   - `pc_restart` — full-stack restart (`scripts/restart-all.ps1`) → verifikasi semua service sehat + state selamat (kill switch, ledger). **Metode ditulis jujur: "restart layanan penuh (bukan reboot OS)"** — reboot host TIDAK dijalankan.
   - `mt5_disconnect` — putuskan koneksi terminal → verifikasi service mendeteksi (degrade, bukan crash) → reconnect → sehat.
   - `database_failure` — rename DB sqlite (cek lokasi aktual dulu, mis. `services/python/ea_bot.db` atau path lain) → hit endpoint → verifikasi degrade → restore → sehat.
   - `llm_failure` — restart service dengan base URL LLM invalid (env override sementara) → jalankan 1 siklus → verifikasi fail-safe → restart normal.
   - `nine_router_failure` — stop proses 9router (`:20128`) → 1 siklus → verifikasi degrade → start ulang → sehat.
   - `telegram_failure` — simulasi token/API gagal (env override) → verifikasi notifier fail-safe → restore.
   - Semua drill: timeout per drill; rollback di `finally`; tulis record ke `ops_drills.jsonl` + detail jujur.
3. **Tests collector** (RED → GREEN): record → True + reason; absen → unknown. Uji juga runner dengan mock (tanpa benar-benar stop service).

## Guardrails
- **DILARANG commit / git add / git stash.**
- **DILARANG menjalankan `scripts/restart-py.ps1`, `restart-all.ps1`, `run_ops_drills.py`, atau perintah apa pun yang menunggu service/daemon (bisa menggantung).** Restart + drill nyata = tugas orchestrator.
- Jangan reformat file lain; edit minimal.
- Jangan sentuh `services/python/src/config.py`, `services/python/src/main.py`, `apps/api/src/index.ts`.
- Jangan sentuh `CHANGELOG.md`, `docs/audit/*`, `docs/hermes_multibot/*`.
- Jangan print secrets (env override ditulis tanpa nilai sensitif di log; redact).
- Setelah semua drill: service `:8787` + `:3789` + `:4321` + `:20128` WAJIB sehat kembali. Kalau ada yang mati → hidupkan lagi sebelum selesai.
- Lint: flake8 100 + black --check (cwd `services/python`).

## Acceptance / verifikasi sendiri
- **JANGAN jalankan drill nyata / restart service.** Orchestrator yang menjalankan `scripts/run_ops_drills.py` + verifikasi live Gate D 7/7 setelah kodemu selesai.
- Kamu buktikan via unit test: collector baca record → True + reason; absen → unknown; runner mengelola timeout + rollback (mock).
- Full suite hijau; lint bersih.
- Tulis `docs/tasks/CERT-D1-report.md` (Indonesia): desain runner, cara pakai, hasil unit test, daftar drill + metode masing-masing, catatan jujur `pc_restart` = restart layanan penuh (bukan reboot OS). Hasil drill nyata diisi orchestrator (atau lampirkan bila diminta).

## Selesai =
Collector + runner + 7 record passed + tests hijau + Gate D live 7/7 + report.
