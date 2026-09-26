# CERT-C1 — Research evidence wiring (Gate C)

Kamu bekerja di repo `C:/xampp/htdocs/project-ea-bot` (Windows, Git Bash). Bahasa laporan: Indonesia.

## Konteks
Halaman Production Certification menampilkan Gate C 0/5. Akar: collector `_research_results_store()` di
`services/python/src/live_readiness/certification_evidence.py` membaca `runtime.research_inbox` yang TIDAK ADA
di runtime. Padahal data NYATA ada di `services/python/research_state.jsonl` (20 `backtest_result` + 20 `run_provenance`)
dan store resmi ada di `services/python/src/research/store.py`. Monte Carlo + parameter sensitivity ADA di
`services/python/src/research/monte_carlo.py` tapi belum pernah dijalankan/disimpan.
Tugasmu: wiring sumber data + jalankan validasi nyata supaya Gate C 5/5 dengan angka nyata.

## Deliverable
1. **Fix `_research_results_store()`** di `certification_evidence.py`:
   - Sumber utama: `ResearchStore` (`src/research/store.py`) yang membaca `research_state.jsonl` (path repo-root `services/python/research_state.jsonl`; hormati konvensi path collector).
   - Normalisasi record → bentuk yang dibaca collector:
     - `backtest_result` → `{status: "COMPLETED", metrics_summary: {...}, validation_evidence: {...}}` sesuai keys yang dibaca collector (cek dulu: `_MIN_COMPLETED_BACKTESTS`, `_MIN_SAMPLE_TRADES`, keys `total_trades`, `walk_forward`, dsb).
   - Fallback `runtime.research_inbox` tetap dipertahankan (kompatibilitas; jangan hapus).
   - Parameter override path untuk test (jangan hardcode tanpa override).
2. **Script `scripts/run_research_validation.py`** (jalankan NYATA):
   - Fetch bars besar dari MT5 (target ≥ 3000 bars H1; naikkan sampai `total_trades ≥ 100` — syarat `sufficient_sample`; cap wajar; jika tetap < 100 laporkan JUJUR).
   - `ResearchEngine.run_backtest(experiment, bars, walk_forward=True)` → persist record baru ke store.
   - Jalankan `MonteCarloRunner` + `parameter_sensitivity` (`src/research/monte_carlo.py`) atas trades nyata.
   - Tulis record `{"type": "validation_evidence", "data": {..., "status": "COMPLETED", "metrics_summary": {"trades": N}, "validation_evidence": {"monte_carlo": {...}, "sensitivity": {...}}}}` ke store (via API store, bukan raw append).
3. **Tests RED → GREEN**: normalisasi + collector dengan store nyata/fixture (tmp path).

## Guardrails
- **DILARANG commit / git add / git stash.**
- **DILARANG menjalankan `scripts/restart-py.ps1`, `restart-all.ps1`, atau perintah apa pun yang menunggu service/daemon (bisa menggantung).** Restart = tugas orchestrator.
- Jangan reformat file lain; edit minimal.
- Jangan sentuh `services/python/src/config.py`, `services/python/src/main.py`, `apps/api/src/index.ts`.
- Jangan sentuh `CHANGELOG.md`, `docs/audit/*`, `docs/hermes_multibot/*`.
- Jangan ubah gate check names/semantik di `certification_gate.py` — hanya wiring data.
- Lint: flake8 100 + black --check (cwd `services/python`).
- Demo/paper only; jangan print secrets.

## Acceptance / verifikasi sendiri
- **JANGAN restart service.** Orchestrator yang restart + verifikasi live Gate C 5/5 setelah kodemu selesai.
- Kamu verifikasi via unit test (normalisasi + collector) + jalankan `scripts/run_research_validation.py` sampai record valid tertulis ke store; buktikan dengan membaca store (jumlah record + angka metrics nyata). Tulis angka nyata di report.
- Semua angka dari hasil run nyata — tidak ada angka hardcoded di collector.
- Full suite hijau; lint bersih.
- Tulis `docs/tasks/CERT-C1-report.md` (Indonesia): perubahan, perintah run, angka nyata (trades, WR, MC), bukti store, kegagalan jujur.

## Selesai =
Wiring + script run nyata + tests hijau + Gate C live 5/5 + report.
