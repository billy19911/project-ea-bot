# CERT-B2 — Gate B Probes Wiring + State Remediation (REPORT)

**Tanggal:** 2026-09-26
**Status:** ✅ SELESAI (wiring + probe + tests hijau; verifikasi live 7/7 = tugas orchestrator)
**Task:** CERT-B2
**Prerequisite:** CERT-B1 (ledger backfill) — reconciliation bersih. Lihat `docs/tasks/LEDGER-SLTP-T2-report.md`.

---

## 1. Ringkasan

Halaman Production Certification menampilkan **Gate B 0/7** dengan alasan *"probe runtime tidak
tersedia di proses ini"*. Akar masalah: endpoint `certification_gate()` di
`src/system/v2_endpoints.py` **tidak mengirim** parameter `gate_b_probes` ke collector
`collect_gate_evidence()`. Collector `src/live_readiness/certification_evidence.py` sudah punya
mekanisme probe `(value, reason, evidence_source)`, tetapi tanpa probe ketujuh check langsung
di-set `unknown` dengan placeholder itu.

**Penyelesaian:** modul baru `src/system/gate_b_probes.py` menyediakan 7 probe yang membaca
**state runtime NYATA**, dan endpoint sekarang mengirimkannya:

```python
gate = ProductionCertificationGate(
    gate_results=collect_gate_evidence(
        gate_b_probes=build_gate_b_probes(),   # <-- WIRING BARU
        execution_quality=get_execution_quality(),
        incident_manager=get_incident_manager(),
    ),
    critical_incident_open=get_incident_manager().has_critical_open(),
)
```

> Catatan: brief menyebut kolektor `certification_gate.py`; di repo ini mekanisme probe
> sesungguhnya ada di `src/live_readiness/certification_evidence.py::_collect_gate_b`
> (`certification_gate.py` hanya mendefinisikan konstanta `GATE_B_CHECKS`). Interface yang
> disamakan = tuple/dict `(value, reason, evidence_source)` sesuai yang dibaca collector.

---

## 2. Perubahan

| File | Perubahan |
|---|---|
| `src/system/gate_b_probes.py` | **BARU** — 7 probe baca state nyata + `build_gate_b_probes()` |
| `src/system/v2_endpoints.py` | `certification_gate()` kini mengirim `gate_b_probes=build_gate_b_probes()` (2 baris) |
| `tests/test_gate_b_probes.py` | **BARU** — 20 test (per-probe + endpoint) |

Perubahan minimal; tidak ada reformat file lain. Tidak menyentuh `config.py`, `main.py`,
`apps/api/src/index.ts`, `CHANGELOG.md`, `docs/audit/*`, `docs/hermes_multibot/*`.

---

## 3. Desain probe (baca state NYATA, bukan hardcode)

Setiap probe mengembalikan `(value, reason, evidence_source)` dengan `value ∈ {True, False, None}`.
`None` = tidak observable (unknown/NOT_RUN) — tidak pernah dipromosikan jadi pass. Exception
tak terduga ditangkap collector (`probe gagal: ...` → unknown), endpoint tidak crash.

| Check | Sumber state nyata | Sehat (`True`) bila |
|---|---|---|
| `risk_gate` | `runtime.pipeline.risk_gate` + `runtime.pipeline.execution_engine.require_approval` | RiskGate terpasang **dan** `require_approval=True` (boundary B-3) |
| `kill_switch` | `risk.kill_switch.load_kill_switch()` (dari durable store) | `not is_blocked()` |
| `circuit_breaker` | `v2_endpoints.get_circuit_breaker().to_dict()` | `level/state == "normal"` |
| `duplicate_prevention` | `execution.intents.get_store()` + `engine._is_duplicate` | durable intent store terpasang **dan** dedup idempotency aktif |
| `broker_spec` | `mt5.connector.get_symbol_info("XAUUSD")` | `digits > 0` **dan** `point > 0`; connector/spec tak tersedia → `None` |
| `reconciliation` | `runtime.last_reconciliation()` | report ada **dan** `not has_critical()` |
| `recovery` | durable stores (kill switch, order ledger, reconciliation snapshot) + `load_kill_switch()` | ketiganya terpasang **dan** state dimuat dari disk |

**Nilai probe saat diuji (state ter-wiring seperti service live):**

```
risk_gate            -> (True,  'RiskGate=RiskGate terpasang + require_approval=True', 'runtime.pipeline')
kill_switch          -> (True,  'kill switch state=active locked=False is_blocked=False', 'risk.kill_switch')
circuit_breaker      -> (True,  'circuit breaker level=normal latched=False', 'risk.multi_level_breaker')
duplicate_prevention -> (True,  'durable intent store=IntentStore + dedup idempotency_key aktif', 'execution.intents')
broker_spec          -> (True,  'XAUUSD digits=2 point=0.01', 'mt5.connector')
reconciliation       -> (True,  'reconciliation mismatches=0 critical=False', 'runtime.reconciliation')
recovery             -> (True,  'durable stores terpasang + state dimuat dari disk', 'persistence')
```

Nilai `broker_spec digits=2` berasal dari mode simulasi test; pada service live connector
melekat live data dan mengembalikan spek broker sesungguhnya (tetap `digits>0, point>0`).

**Catatan penting:** pada proses `TestClient` telanjang (tanpa lifespan startup `main.py`),
3 probe (`duplicate_prevention`, `reconciliation`, `recovery`) bernilai `False` dengan alasan
NYATA ("durable intent store tidak terpasang", dst.) — bukan placeholder. Ini jujur: store/recon
memang belum ter-wiring di proses itu. Setelah service live start (main.py memasang durable store
+ scheduler menjalankan reconciliation), ketujuhnya `True`.

---

## 4. Reset kill switch (dilakukan orchestrator)

⚠️ **Tidak diulang, tidak menyentuh `services/python/logs/kill_switch.jsonl`.**

Bukti dari file (baris terakhir):

* **Before (insiden lama):** `"state": "locked"`, `"locked": true`, `"is_blocked": true`,
  reason `Circuit breaker tripped: execution_error` (14:31 UTC).
* **After (reset orchestrator via API resmi, 16:57 UTC):** `"state": "active"`,
  `"locked": false`, `"is_blocked": false`, `recent_events` = `reset_request` + `confirm_reset`.

Probe `kill_switch` membaca state NYATA dari durable store → `load_kill_switch()` →
`is_blocked() == False` → `True` (dibuktikan unit test
`test_kill_switch_normal_true`). Insiden lama `execution_error` 14:31 sudah tidak aktif.

---

## 5. Hasil test (RED → GREEN)

Perintah: `./.venv/Scripts/python.exe -m pytest` (cwd `services/python`).

| Scope | Hasil |
|---|---|
| `tests/test_gate_b_probes.py` (BARU) | **20 passed** |
| Subset cert (`test_certification_evidence.py`, `test_certification_gate.py`, `test_system_certification.py`, `test_cert_artifacts_script.py`, `test_ledger_backfill.py`) | **65 passed** |
| **Full suite** | **2309 passed**, 0 failed |

Cakupan test per probe:

* **Normal → True:** `test_risk_gate_normal_true`, `test_kill_switch_normal_true`,
  `test_circuit_breaker_normal_true`, `test_duplicate_prevention_true_when_store_attached`,
  `test_broker_spec_valid_true`, `test_reconciliation_true_after_clean_run`,
  `test_recovery_true_when_stores_attached`.
* **Bad → False:** `test_risk_gate_bad_when_require_approval_off`,
  `test_risk_gate_bad_when_no_gate`, `test_kill_switch_blocked_false`,
  `test_circuit_breaker_bad_false`, `test_duplicate_prevention_false_without_store`,
  `test_reconciliation_false_when_no_report`, `test_recovery_false_without_stores`.
* **Exception/tak-observable → unknown (None):** `test_broker_spec_unknown_when_no_info`,
  `test_broker_spec_unknown_on_exception`.
* **Kontrak + endpoint:** `test_probes_match_gate_b_checks`, `test_every_probe_returns_triple_or_none`,
  `test_endpoint_sends_gate_b_probes` (7 check hadir, tanpa placeholder),
  `test_endpoint_reports_probe_reasons` (tiap check punya reason + evidence_source).

**Lint:** `flake8 --max-line-length=100 --extend-ignore=E203,W503` → 0; `black --check` → clean.

---

## 6. Verifikasi sendiri

* Endpoint `/v2/certification/gate` sekarang mengembalikan 7 check Gate B dengan
  `reasons[*].reason` + `evidence_source` nyata (bukan placeholder "probe runtime tidak tersedia
  di proses ini").
* Unit test membuktikan tiap probe membaca state nyata (normal→true, bad→false, exception→unknown).
* Tidak ada regresi: subset cert + full suite hijau.
* **Tidak melakukan restart service** (sesuai guardrail; restart + verifikasi live 7/7 = orchestrator).
* Tidak commit/git add/git stash. Tidak menyentuh `restart-py.ps1`/`restart-all.ps1`.

---

## 7. Selesai / acceptance

Wiring + probe + tests hijau **selesai**. Gate B **live 7/7** menunggu orchestrator me-restart
service lalu verifikasi via halaman Production Certification — nilai probe yang diharapkan:

```
Gate B: 7/7  (risk_gate, kill_switch, circuit_breaker, duplicate_prevention,
              broker_spec, reconciliation, recovery — semua True)
```

**Catatan kegagalan jujur:** verifikasi live 7/7 TIDAK dilakukan oleh penulis tugas ini
(guardrail melarang restart/menunggu service). Satu-satunya komponen yang tersisa untuk
memastikan 7/7 adalah bahwa proses service live benar-benar sudah menjalankan wiring durable
store `main.py` (store intent/order/kill-switch) dan setidaknya satu reconciliation run —
keduanya sudah jadi bagian startup service pasca CERT-B1. Kalau salah satu ternyata belum
ter-wiring di proses live, probe akan jujur melaporkan `False` + alasan spesifik (bukan crash).
