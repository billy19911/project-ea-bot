# CERT-B2 — Gate B probes wiring + state remediation

Kamu bekerja di repo `C:/xampp/htdocs/project-ea-bot` (Windows, Git Bash). Bahasa laporan: Indonesia.
Prerequisite: CERT-B1 (ledger backfill) selesai — reconciliation bersih. Baca `docs/tasks/LEDGER-SLTP-T2-report.md` dulu.

## Konteks
Halaman Production Certification menampilkan Gate B 0/7 dengan alasan "probe runtime tidak tersedia di proses ini".
Akar: endpoint `certification_gate()` di `services/python/src/system/v2_endpoints.py` (sekitar baris 590–700)
TIDAK mengirim parameter `gate_b_probes` ke collector. Collector `certification_gate.py` sudah punya mekanisme
probe `(value, reason, source)`. Tugasmu: wiring + pastikan state nyata hijau.

## Deliverable
1. **Wiring `gate_b_probes`** di `v2_endpoints.py` pada call `certification_gate(...)`/collector:
   - Kirim dict berisi 7 probe: `risk_gate`, `kill_switch`, `circuit_breaker`, `duplicate_prevention`, `broker_spec`, `reconciliation`, `recovery`.
   - Setiap probe = callable/dict yang membaca state runtime NYATA; exception → `unknown` dengan reason (jangan crash endpoint).
   - Format persis ikuti interface yang sudah dibaca collector (cek `certification_gate.py` — probe menerima/mengembalikan `(value, reason, evidence_source)` atau dict `{value, reason, evidence_source}`; samakan dengan yang collector harapkan).
2. **Desain probe (baca state nyata, bukan hardcode):**
   - `risk_gate`: RiskGate terpasang di pipeline runtime (cek `runtime.pipeline` / `RiskGate(` wiring; boundary B-3) + `ExecutionEngine.require_approval=True`.
   - `kill_switch`: `load_kill_switch()` → `not is_blocked()`.
   - `circuit_breaker`: `get_circuit_breaker().to_dict()["state"] == "normal"`.
   - `duplicate_prevention`: durable intent store terpasang + dedup `idempotency_key` aktif di engine (`src/execution/intents.py`).
   - `broker_spec`: connector `get_symbol_info(symbol)` → spec valid (digits>0, point>0); connector tidak tersedia → unknown.
   - `reconciliation`: `runtime.last_reconciliation()` ada dan tidak `has_critical` (setelah B1 ini harus ok).
   - `recovery`: durable stores terpasang (kill switch store, order ledger, reconciliation snapshot) + state dimuat dari disk.
3. **Kill switch reset** — ⚠️ SUDAH DILAKUKAN ORCHESTRATOR (jangan ulangi):
   - State file `services/python/logs/kill_switch.jsonl` sekarang berakhir dengan `"state": "active"`, `"locked": false`, `"is_blocked": false` (reset 16:57 UTC via API resmi).
   - Tugasmu hanya: probe `kill_switch` membaca state NYATA dan unit test membuktikan state normal → true. JANGAN panggil `request_reset`/`confirm_reset` lagi, jangan sentuh file kill_switch.jsonl.
   - Catatan untuk report: reset dilakukan orchestrator (sistem stabil; insiden lama `execution_error` 14:31 sudah tidak aktif).
4. **Tests RED → GREEN**: unit per probe (state normal → true; state bad → false; exception → unknown) + test endpoint menyertakan `gate_b_probes`.

## Guardrails
- **DILARANG commit / git add / git stash.**
- **DILARANG menjalankan `scripts/restart-py.ps1`, `restart-all.ps1`, atau perintah apa pun yang menunggu service/daemon (bisa menggantung).** Restart = tugas orchestrator.
- Jangan reformat file lain; edit minimal.
- Jangan sentuh `services/python/src/config.py`, `services/python/src/main.py`, `apps/api/src/index.ts`.
- Jangan sentuh `CHANGELOG.md`, `docs/audit/*`, `docs/hermes_multibot/*`.
- Lint: `./.venv/Scripts/python.exe -m flake8 --max-line-length=100 --extend-ignore=E203,W503 <files>` + `black --check <files>` (cwd `services/python`).

## Acceptance / verifikasi sendiri
- **JANGAN restart service.** Orchestrator yang restart + verifikasi live Gate B 7/7 setelah kamu selesai.
- Kamu buktikan via unit test: endpoint mengirim `gate_b_probes` (7 probe), tiap probe membaca state nyata (normal→true, bad→false, exception→unknown). Tulis hasil unit test + nilai probe di report.
- Tidak ada regresi: test cert existing (`tests/test_certification_evidence.py`, `tests/test_certification_gate*.py`) tetap hijau; subset + full suite hijau.
- Tulis `docs/tasks/CERT-B2-report.md` (Indonesia): perubahan, probe state nyata (nilai + reason), reset kill switch (before/after dari file), hasil test, kegagalan jujur.

## Selesai =
Wiring + probe + reset + tests hijau + Gate B live 7/7 + report.
