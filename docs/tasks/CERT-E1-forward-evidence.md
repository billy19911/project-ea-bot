# CERT-E1 — Forward testing evidence (Gate E)

Kamu bekerja di repo `C:/xampp/htdocs/project-ea-bot` (Windows, Git Bash). Bahasa laporan: Indonesia.
Prerequisite: CERT-D1 selesai (service stabil) + CERT-B1 selesai (guard unblocked) + kill switch clear (CERT-B2).
Gate E saat ini 2/5: `execution_quality` + `no_critical_incident` LOLOS. Yang gagal: `paper`, `demo`, `monitoring`.

## Konteks
Collector `_collect_gate_e()` mencari bukti paper/demo/monitoring yang belum ada. Module paper ADA di
`services/python/src/paper/` (`paper_account.py`, `simulated_execution.py`). Jalur demo live = `ExecutionEngine._send_to_mt5()`
dengan `OrderRequest.sl`/`.tp`; broker butuh filling **FOK**; symbol demo = `#BTCUSD` (crypto 24/7).
Terminal MT5 demo: folder `E:\MT5 XYNN EA\MetaTrader 5 BIL 2` (spasi — raw string), akun demo.

## Deliverable
1. **Collector** — ⚠️ SUDAH DI-WIRE ORCHESTRATOR di `certification_evidence.py` (`_collect_gate_e(..., forward_path=None)`): membaca `docs/evidence/forward-testing.json` (env override `FORWARD_EVIDENCE_PATH`, param override `forward_path`); key `paper`/`demo`/`monitoring` masing-masing `{"status": "passed", "at": ..., "metrics": {...}}` → True + reason + metrics; absen → unknown. **JANGAN edit `certification_evidence.py`.**
   - Tugasmu: tests collector di file BARU `services/python/tests/test_forward_evidence.py` (tmp store + param override; passed → True; absen → unknown; status failed → False).
2. **Store `docs/evidence/forward-testing.json`**: kamu TULIS dengan hasil run nyata dari script (bukan dummy) — format di atas dengan metrics NYATA per key.
3. **Script `scripts/run_forward_validation.py`** (jalankan NYATA):
   - **paper:** jalankan `SimulatedExecutionEngine` + `PaperAccount` atas data nyata (bars dari research store / MT5) — target ≥ 20 trade → summary (trades, win_rate, net_pnl). Persist hasil.
   - **demo:** arm terminal (pola B-4: re-select + re-arm) → place order kecil `#BTCUSD` **DENGAN SL/TP** (ini sekaligus menutup gap LEDGER T3: live SL/TP attach) → verifikasi fill + `sl/tp != 0` di broker → tutup posisi → catat ticket + hasil. TIDAK ada posisi menggantung di akhir.
   - **monitoring:** verifikasi monitoring kontinu nyata (feed loop tick + observasi position monitor) → catat metrics (ticks/cycles/window) ke store.
4. **Tests RED → GREEN**: collector E dengan store fixture (ada → true; absen → unknown).
5. **Jalankan script** sampai 3 sub-check punya bukti nyata. Jika salah satu langkah gagal (mis. arm ditolak, SL/TP ditolak broker) → LAPORKAN JUJUR, jangan fabrikasi; perbaiki bila memungkinkan (mis. filling mode, min stop distance `trade_stops_level`).

## Guardrails
- **DILARANG commit / git add / git stash.**
- Jangan reformat file lain; edit minimal.
- Jangan sentuh `services/python/src/config.py`, `services/python/src/main.py`, `apps/api/src/index.ts`.
- Jangan sentuh `CHANGELOG.md`, `docs/audit/*`, `docs/hermes_multibot/*`.
- **Demo only** — tidak ada live money; jangan print secrets.
- SL/TP wajib dihormati broker: cek `trade_stops_level`/min distance; filling FOK.
- Lint: flake8 100 + black --check (cwd `services/python`).

## Acceptance / verifikasi sendiri
- **JANGAN restart service.** Orchestrator yang restart + verifikasi live Gate E 5/5 setelah kodemu selesai.
- Demo order: bukti ticket, SL/TP terpasang di broker, posisi DITUTUP; tidak ada posisi menggantung. (Order demo + arm terminal BOLEH kamu jalankan — itu inti bukti.)
- Full suite hijau; lint bersih.
- Tulis `docs/tasks/CERT-E1-report.md` (Indonesia): per sub-check — apa dijalankan, angka nyata, ticket/hasil demo, bukti store, kegagalan jujur.

## Selesai =
Collector + script run nyata (paper ≥ 20 trade, demo order SL/TP + closed, monitoring metrics) + tests hijau + Gate E live 5/5 + report.
