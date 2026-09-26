# CERTIFICATION GATE REMEDIATION — PLAN EKSEKUSI

**Tanggal:** 2026-09-26
**Repo:** `C:/xampp/htdocs/project-ea-bot`
**Tujuan:** Membuat 5 gate Production Certification HIJAU dengan **bukti nyata** (bukan fabrikasi).
**Proses:** plan (dokumen ini) → brief per task → delegasi OpenCode → monitoring anti-stuck → verifikasi independen.

---

## 0. Konteks & akar masalah

Endpoint `GET /v2/certification/gate` (halaman Production Certification) menunjukkan hampir semua gate FAIL.
**Bukan regresi** dari pekerjaan terakhir: commit `d9cd82d` mengubah collector (`certification_evidence.py`) agar hanya
mempercayai bukti filesystem/runtime NYATA. Bukti-bukti itu belum pernah digenerate, dan sebagian wiring-nya bolong.

| Gate | Checks | Kondisi | Akar masalah | Kelas |
|---|---|---|---|---|
| A Engineering | 6 | 0/6 | Tooling/CI tidak pernah menulis artefak (`pytest*.txt`, `node_tests*.json`, …) ke disk | kecil |
| B Trading safety | 7 | 0/7 | Endpoint tidak mengirim `gate_b_probes`; ledger stale (17 `position_confirmed`/0 closed); kill switch `triggered`+`locked` | kecil–sedang |
| C Research | 5 | 0/5 | Collector baca `runtime.research_inbox` yang tidak ada; data nyata ada di `services/python/research_state.jsonl` (20 backtest_result + 20 run_provenance); Monte Carlo/sensitivity belum pernah dijalankan & disimpan | sedang |
| D Ops drills | 7 | 0/7 | Collector selalu unknown (tidak ada sumber bukti); script drill belum ada; drill belum pernah dijalankan | besar |
| E Forward testing | 5 | 2/5 | `execution_quality` + `no_critical_incident` LOLOS; `paper`/`demo`/`monitoring` belum ada sumber bukti + wiring | besar |

**Prinsip keras:** bukti nyata atau jujur `unknown` — **dilarang fabrikasi**. Gate hanya boleh hijau karena artefak/record nyata.

**Alignment chain LEDGER-SLTP (deliverable user sebelumnya, belum selesai):**
B1 ≡ LEDGER T2 (backfill ledger) · E1 mencakup LEDGER T3 (live SL/TP attach) · Z ≡ LEDGER T4 (evidence + verifikasi).

---

## 1. Aturan main (berlaku untuk semua task)

1. **DILARANG commit** (`git add` / `git commit` / `git stash`) — tinggalkan semua sebagai uncommitted.
2. Jangan reformat file di luar scope; **edit minimal**.
3. **File terproteksi** (ada perubahan user — JANGAN disentuh): `services/python/src/config.py`, `services/python/src/main.py`, `apps/api/src/index.ts`.
4. **TDD**: tulis test RED dulu → implement → GREEN. Jalankan subset saat iterasi, full suite di akhir task.
5. Lint Python: `flake8 --max-line-length=100 --extend-ignore=E203,W503` + `black --check` (tidak ada ruff).
6. Python interpreter: `services/python/.venv/Scripts/python.exe`; cwd `services/python` untuk import `src.*`.
7. **Demo/paper only** — tidak ada live money.
8. Laporan jujur per task: `docs/tasks/CERT-<id>-report.md` (bahasa Indonesia), termasuk yang gagal.
9. Jangan sentuh dokumen historis (`CHANGELOG.md`, `docs/audit/*` kecuali diminta, `docs/hermes_multibot/*`).
10. Service Python berjalan di `:8787`; restart resmi = `scripts/restart-py.ps1` (wrapper timeout by design).

---

## 2. Urutan wave & dependency

```
A1 ─┬─► (paralel)
    │
B1 ─┴─► B2 ─► C1 ─► D1 ─► E1 ─► Z
```

- **A1 & B1 paralel** (independen: A1 = tooling/reports; B1 = ledger backfill).
- **B2** butuh B1 (reconciliation bersih) + mencakup kill-switch reset.
- **C1** setelah B2 (service stabil; tidak wajib tapi menjaga urutan monitoring).
- **D1** butuh B2 (kill switch clear) — drills mengganggu service, harus di window terkontrol.
- **E1** butuh D1 selesai (service stabil) + B1 (guard unblocked) + arm terminal (demo order SL/TP).
- **Z** verifikasi akhir oleh orchestrator (bukan OpenCode).

---

## 3. TASK A1 — CI artifacts generator (Gate A)

**Deliverable:**
- `scripts/cert_artifacts.ps1` (baru) — menjalankan perintah NYATA dan menulis:
  - `reports/pytest-report.txt` ← `services/python/.venv/Scripts/python.exe -m pytest -q` (cwd `services/python`)
  - `reports/node_tests.json` ← `npm test --workspace=project-ea-bot-api` (bungkus JSON: `{command, exit_code, output}`)
  - `reports/web_build.txt` ← `npm run build --workspace=project-ea-bot-web`
  - `reports/typecheck.txt` ← type-check web + API (perintah tsc nyata)
  - `reports/lint.txt` ← flake8 + `black --check` + `npm run lint` (web & api)
  - `reports/security.json` ← `pip-audit -f json` + `npm audit --json` → gabung `{pip_audit, npm_audit}`
- Update `.github/workflows/ci.yml` agar CI menulis artefak yang sama (konsistensi desain CI ↔ gate; jangan rusak workflow).
- `reports/` TIDAK boleh di dalam dir excluded collector: `temp_pytest`, `.venv`, `node_modules`, `.next`, `dist`, `build`, `__pycache__`, dir hidden. `reports/` aman.
- Pattern yang harus match glob collector: `**/pytest*.txt`, `**/node_tests*.json`, `**/web_build*.txt`, `**/typecheck*.txt`|`**/tsc*.txt`, `**/lint*.txt`|`**/flake8*.txt`, `**/security*.json`|`**/bandit*.json`.

**Acceptance:**
- `reports/*` ada, size > 0, berisi output nyata (bukan dummy).
- Live: `GET /v2/certification/gate` → Gate A **6/6 true**, evidence_source `file:reports/...`.
- Kalau salah satu perintah gagal (mis. web build TS error pre-existing `envSchema.ts:86`), file tetap ditulis berisi log + exit code **jujur**; catat di report.

**Risiko:** full pytest + web build = ~10-20 menit. Jangan pipe ke `tail` — tulis penuh ke file.

---

## 4. TASK B1 — Ledger backfill (Gate B prep) [≡ LEDGER-SLTP T2]

**Sumber desain:** `docs/tasks/LEDGER-SLTP-T2-stale-backfill.md` (brief yang sudah ada — baca dulu, laksanakan).
**Masalah:** `services/python/logs/order_state.jsonl` berisi 17 record `position_confirmed` BASI (posisi sudah tidak ada di broker, 0 record `closed`) → `ReconciliationGuard` fail-close SEMUA order baru (`last_ok=False`).

**Deliverable:**
- Script backfill (mis. `scripts/backfill_stale_positions.py`) yang:
  1. Membaca ledger via `src/persistence/order_state_store.py` (API store, bukan tulis raw).
  2. Menandai record stale → `closed` dengan alasan terrekam (mis. `reason="stale_backfill: tidak ada di broker"`, timestamp).
  3. **HAZARD:** bedakan "posisi hilang" vs "read gagal" — gunakan jalur `get_positions_ex` ok-flag (anti false-close); jika broker read gagal → JANGAN backfill.
- Restart service (`scripts/restart-py.ps1`) → verifikasi guard unblocked.
- Unit test untuk logika backfill (RED → GREEN).

**Acceptance:**
- `GET /reconciliation/status` → tidak ada mismatch kritikal; `last_ok=True`; guard tidak memblokir order baru.
- Ledger: record stale bertransisi ke `closed` (bukan dihapus).
- Tests existing lulus.

---

## 5. TASK B2 — Gate B probes wiring + state remediation

**Deliverable:**
1. Wiring `gate_b_probes` di `services/python/src/system/v2_endpoints.py` (`certification_gate()`):
   ```python
   gate_b_probes={
     "risk_gate": ..., "kill_switch": ..., "circuit_breaker": ...,
     "duplicate_prevention": ..., "broker_spec": ..., "reconciliation": ..., "recovery": ...,
   }
   ```
   Setiap probe = callable → `(value, reason, source)` ATAU dict `{value, reason, evidence_source}`; exception → unknown (jangan crash endpoint).
2. Desain probe (semua baca state runtime NYATA):
   - `risk_gate`: risk gate terpasang di pipeline runtime + `ExecutionEngine.require_approval=True` (boundary B-3).
   - `kill_switch`: `load_kill_switch()` → `not is_blocked()`.
   - `circuit_breaker`: `get_circuit_breaker().to_dict()["state"] == "normal"`.
   - `duplicate_prevention`: durable intent store terpasang + dedup `idempotency_key` aktif di engine.
   - `broker_spec`: connector `get_symbol_info(symbol)` mengembalikan spec valid (digits>0, point>0); connector tak tersedia → unknown.
   - `reconciliation`: `runtime.last_reconciliation()` ada dan tidak `has_critical` (butuh B1 selesai).
   - `recovery`: durable stores (kill switch store, order ledger, reconciliation snapshot) terpasang & state dimuat dari disk; bukti restart service (health 200 + state survive).
3. **Kill switch reset** (state saat ini `triggered`+`locked`, reason `execution_error` 14:31 — insiden lama):
   - `load_kill_switch()` → `request_reset(requested_by="operator")` → `confirm_reset()` → persist.
   - Restart service → verify state clear.
   - Dokumentasikan alasan reset di report (sistem stabil; tidak ada execution error aktif).
4. Tests: unit per probe + endpoint menyertakan probes (RED → GREEN).

**Acceptance:**
- Live `GET /v2/certification/gate` → Gate B **7/7 true** dengan reason nyata.
- Tidak ada regresi test cert existing.

---

## 6. TASK C1 — Research evidence wiring (Gate C)

**Deliverable:**
1. Fix `_research_results_store()` di `certification_evidence.py`:
   - Sumber utama: `ResearchStore` (`services/python/src/research/store.py`; baca `research_state.jsonl`).
   - Normalisasi record → bentuk yang dibaca collector:
     - `backtest_result` → `{status: "COMPLETED", metrics_summary: {trades: total_trades, walk_forward: ...}, validation_evidence: {walk_forward: bool}}`
     - `validation_evidence` (baru, lihat #2) → dipakai langsung.
   - Fallback `runtime.research_inbox` tetap ada (kompatibilitas).
2. Script `scripts/run_research_validation.py` (jalankan NYATA):
   - Fetch bars besar dari MT5 (target ≥ 3000 bars H1; naikkan sampai `total_trades ≥ 100` — syarat `sufficient_sample`; cap wajar, jika tetap < 100 laporkan jujur).
   - `ResearchEngine.run_backtest(experiment, bars, walk_forward=True)` → persist record baru.
   - Jalankan `MonteCarloRunner` + `parameter_sensitivity` (dari `src/research/monte_carlo.py`) atas trades nyata.
   - Tulis record `{"type": "validation_evidence", "data": {..., "status": "COMPLETED", "metrics_summary": {"trades": N}, "validation_evidence": {"monte_carlo": {...}, "sensitivity": {...}}}}` ke store.
3. Tests RED → GREEN (normalisasi + collector dengan store nyata/fixture).

**Acceptance:**
- Live `GET /v2/certification/gate` → Gate C **5/5 true** (backtest, walk_forward, monte_carlo, parameter_sensitivity, sufficient_sample).
- Semua angka berasal dari hasil run nyata; tidak ada angka hardcoded di collector.

---

## 7. TASK D1 — Ops drills (Gate D)

**Deliverable:**
1. Collector: `_collect_gate_d()` membaca evidence store default `services/python/logs/ops_drills.jsonl` (env override `OPS_DRILLS_PATH`), format per baris:
   `{"drill": "mt5_restart", "status": "passed", "at": "<iso>", "method": "...", "detail": "..."}`
   - Record `passed` → `True` + reason (timestamp + method); tidak ada record → unknown seperti sekarang (jangan false).
2. Runner `scripts/run_ops_drills.py` (atau `.ps1`) + rollback + health check sebelum/sesudah tiap drill:
   - `mt5_restart` — stop proses terminal MT5 → start ulang → verifikasi reconnect + service sehat.
   - `pc_restart` — full-stack restart (`scripts/restart-all.ps1`) → verifikasi semua service sehat + state selamat (kill switch, ledger). **Metode ditulis jujur di evidence: "restart layanan penuh (bukan reboot OS)"** — reboot host tidak dijalankan.
   - `mt5_disconnect` — putuskan koneksi terminal → verifikasi service mendeteksi (degrade, bukan crash) → reconnect → sehat.
   - `database_failure` — rename DB sqlite (`services/python/ea_bot.db`, cek lokasi aktual) → hit endpoint → verifikasi degrade → restore → sehat.
   - `llm_failure` — restart service dengan base URL LLM invalid (env override sementara) → jalankan 1 siklus → verifikasi fail-safe → restart normal.
   - `nine_router_failure` — stop proses 9router (`:20128`) → 1 siklus → verifikasi degrade → start ulang → sehat.
   - `telegram_failure` — simulasi token/API gagal (env override) → verifikasi notifier fail-safe → restore.
3. Semua drill: timeout per drill; rollback di `finally`; tulis record ke `ops_drills.jsonl` + report.
4. Tests collector (record → True; absen → unknown).

**Acceptance:**
- Live `GET /v2/certification/gate` → Gate D **7/7 true** dengan reason + timestamp + method.
- Setelah semua drill: service `:8787` + `:3789` + `:4321` + `:20128` sehat.
- Catatan jujur untuk `pc_restart` (metode yang dipakai).

**Risiko:** drill mengganggu service live (feed ON). Window terkontrol; jangan paralel dengan task lain.

---

## 8. TASK E1 — Forward evidence (Gate E)

**Deliverable:**
1. Evidence store `docs/evidence/forward-testing.json`:
   `{"paper": {...}, "demo": {...}, "monitoring": {...}}` dengan `status: "passed"`, timestamp, metrics nyata.
2. Collector: `_collect_gate_e()` membaca store tsb (path default; param override untuk test) → `paper`/`demo`/`monitoring` True bila record nyata ada; `execution_quality`/`no_critical_incident` tetap seperti sekarang.
3. Script `scripts/run_forward_validation.py` (jalankan NYATA):
   - **paper:** jalankan `SimulatedExecutionEngine` + `PaperAccount` atas data nyata (mis. bars dari research store) — target ≥ 20 trade → summary (trades, win_rate, net_pnl).
   - **demo:** arm terminal → place order kecil `#BTCUSD` **DENGAN SL/TP** (fix gap LEDGER T3: live SL/TP attach) → verifikasi fill + `sl/tp != 0` di broker → tutup posisi → catat ticket + hasil. (Butuh B1 selesai + kill switch clear.)
   - **monitoring:** verifikasi monitoring kontinu nyata (feed loop tick + observasi position monitor) → catat metrics (ticks/cycles/window).
4. Tests RED → GREEN (collector E dengan store fixture).

**Acceptance:**
- Live `GET /v2/certification/gate` → Gate E **5/5 true**.
- Demo order: bukti ticket, SL/TP terpasang, posisi ditutup; tidak ada posisi menggantung.
- Jika salah satu langkah gagal (mis. arm ditolak), laporkan jujur — jangan fabrikasi.

---

## 9. TASK Z — Verifikasi akhir (orchestrator)

- Full pytest `services/python` (target ≥ 2260 passed, no regression) + lint bersih.
- Live `GET /v2/certification/gate` → **semua gate A–E HIJAU**; screenshot/JSON bukti disimpan.
- `docs/evidence/CERTIFICATION-GATE-REMEDIATION.md` + tracker status di plan ini.
- Update status di report; tanpa commit.

---

## 10. Monitoring protocol (anti-stuck)

- Delegasi: `opencode run --dir "C:/xampp/htdocs/project-ea-bot" "$(cat docs/tasks/CERT-X.md)" > _oc_cert_x.log 2>&1; echo "OC_EXIT=$?" >> _oc_cert_x.log` (background).
- Watchdog per task:
  - Cek log mtime + tail berkala; proses hidup.
  - Batas wall: kecil 25 mnt, sedang 45 mnt, besar 90 mnt.
  - **Stuck** = log tidak berubah > 10 mnt tanpa child activity → kill PID → analisis → retry (maks 2×, brief diperkecil).
- Selesai → **verifikasi independen**: file yang diharapkan berubah, test subset, lint, bukti endpoint. Jangan percaya klaim log.
- Gagal verifikasi → follow-up task perbaikan; jangan tandai selesai.

## 11. Status tracker

| Task | Status | Log | Verifikasi |
|---|---|---|---|
| A1 | ✅ SELESAI | `_oc_cert_a1.log` (OC_EXIT=0) | Gate A 6/6 PASSED (live) |
| B1 | ✅ SELESAI | `_oc_cert_b1.log` (stuck→kill→takeover) | 15 closed; recon 0 mismatch; guard ok |
| B2 | ✅ SELESAI | `_oc_cert_b2.log` (OC_EXIT=0) | Gate B 7/7 PASSED (live) |
| C1 | ✅ SELESAI | `_oc_cert_c1.log` (OC_EXIT=0) | Gate C 5/5 PASSED (live) |
| D1 | ✅ SELESAI | `_oc_cert_d1.log` (OC_EXIT=0) + 19 patch orchestrator | Gate D 7/7 PASSED (live, store 7/7) |
| E1 | ✅ SELESAI | `_oc_cert_e1.log` (OC_EXIT=0) | Gate E 5/5 PASSED (live) |
| Z | ✅ SELESAI | — | **ALL GREEN — `READY_FOR_SMALL_LIVE`** |
