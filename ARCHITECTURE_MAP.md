# ARCHITECTURE_MAP.md

**Tujuan:** Terpusatkan semua dokumen referensi sistem, diagram, dan jalur kritis untuk EPIC 01–30.  Catatan ini bertujuan untuk memastikan tim dapat dengan cepat:

1. **Menemukan** artifact yang menentukan arah (ARDS, PRD V2, diagram alur)
2. **Memverifikasi** prerequisite untuk deployment (runtime, dependency, environment)
3. **Melacak** keputusan penting (workflow, kepemilikan, pengecualian)
4. **Memverifikasi** status saat ini (ceklist + file `CURRENT_STATE.md` di `docs/audit`)

---

## Ringkasan EPIC 00 (Audit Compliance)

> **Status catatan (revisi audit RC):** Angka test di bawah disinkronkan dengan hasil eksekusi
> release-candidate terakhir — **Python 1943 passed** (`pytest tests/`), **Node API 46/46**,
> **Web `tsc` + lint bersih**. Lihat `docs/audit/RELEASE_READINESS_REPORT.md` untuk audit RC
> terkini. Klaim "safety boundary" di catatan lama terlalu kuat: beberapa gate bersifat
> *caller-enforced* dan sebagian modul governance/learning belum ter-wire ke runtime — detail
> di laporan RC (bagian Component Verification & Dead/Orphaned Code).

- ✅ **Tests**: 1943 Python + 46 Node passing; Web typecheck/lint bersih (**+10 test RC → 1953** setelah perbaikan B-3/B-6, commit `02a577c`)
- ✅ **Safety boundary**: Risk Gate deterministik ter-wire di pipeline (fail-closed) **dan** kini ditegakkan di executor: `ExecutionEngine(require_approval=True)` menolak order tanpa `approval_token` (fail-closed). Sebagian guard lain (permission guards, `MT5WriteGuard`, `MultiLevelBreaker` di jalur trade) **belum ter-wire** ke runtime produksi. Lihat `docs/audit/RELEASE_READINESS_REPORT.md`.
- ✅ **DevOps and linting:** Black, isort, flake8 passing, CI/CD blueprint integrated
- ✅ **Documentation:** README, CHANGELOG, PRD V2, ARCHITECTURE_MAP dibuat

---

## Iterasi TIMELINE

| EPIC | Judul | File | Status |
|------|-------|------|--------|
| EPIC 00 | Audit Kondisi Sekarang | `docs/audit/CURRENT_STATE.md` | **Complete** |
| EPIC 01 | Department Model | `src/agents/departments.py`, `src/agents/permissions.py` | **Complete** |
| EPIC 02 | Agent Registry metadata (ditambahkan ke `base.py`) | `src/agents/base.py` | **Complete** |
| EPIC 03 | Supervisor routing to department leads | `src/agents/supervisor.py` | **Complete** |
| EPIC 04 | Market Intelligence Department (analyst aggregation & consensus) | `src/market/` | **Complete** |
| EPIC 05 | Risk Intelligence Department (advisory only) | `src/risk/intelligence.py` | **Complete** |
| EPIC 07 | Deterministic Risk & Safety (KillSwitch, CircuitBreaker) | `src/risk/` | **Complete** |
| EPIC 08 | Execution Engine (OrderBuilder, RecoveryEngine) | `src/execution/` | **Complete** |
| EPIC 09 | Position Monitoring (lifecycle, trailing, abnormal detection) | `src/monitoring/` | **Complete** |
| EPIC 11 | Advanced Trade Review (root-cause, patterns, journal) | `src/review/` | **Complete** |
| EPIC 12 | Research Engine (hypotheses, experiments, backtests) | `src/research/` | **Complete** |
| EPIC 13 | Strategy Versioning & Promotion (registry, gates, activation) | `src/strategy/` | **Complete** |
| EPIC 14 | Learning Loop (review→pattern→hypothesis→experiment→validation) | `src/learning/` | **Complete** |
| EPIC 15 | Dashboard & Control Plane (16 halaman, 13 endpoint) | `apps/web/app/control-plane/`, `apps/api/` | **Complete** |
| EPIC 16 | Observability (traces, domain metrics, alerts) | `src/observability/` | **Complete** |
| EPIC 17 | Security (tool permissions, tamper-evident audit) | `src/security/` | **Complete** |
| EPIC 18 | Testing & Failure Simulation (13 skenario) | `tests/test_failure_simulation.py` | **Complete** |
| EPIC 19 | Live Readiness (14 gate + explicit LIVE activation) | `src/readiness/` | **Complete** |
| — | Agent wiring produksi (5 analyst terdaftar + delegasi Supervisor) | `src/main.py`, `src/agents/supervisor.py`, `src/orchestration/runtime.py` | **Complete** |

---

## Document Junction

### Keputusan Desain

- **Department Lead**: Dipilih melalui skema `role = "department_lead"` → Supervisor rutes ke leads terlebih dahulu.
- **Agent metadata**: `role`, `permissions`, `dependencies`, `model_policy`, `timeout_seconds` didefinisikan sebagai atribut `BaseAgent` sehingga direktori agen di registry dapat di-query (get_by_role, get_by_permission).
- **Permission guards**: Helper `require_permission` tersedia (`src/agents/permissions.py`). **Catatan:** guard ini saat ini **tidak dipanggil** dari jalur runtime produksi (dipakai di test) — lihat laporan RC (Dead/Orphaned Code).

### Nama Modul / Entry Points

| Modul | Path | Pintu Masuk |
|-------|------|-----------|
| Manajemen Agent | `src/agents/` | Supervisor, Registry, Department, Permissions |
| Sistem Trading | `src/trading/` | EventEngine, MarketRegime, TradingEngine |
| Risk Gate | `src/risk/` | RiskGate (implementation) |
| Eksekusi | `src/execution/` | ExecutionEngine |
| MT5 | `src/mt5/` | Mt5Connector |
| LLM Gateway | `src/llm/` | NineRouter |

### Dokumen Core

- **ARD (Architecture Requirements Documents)** → `PRD_V1_...md` (ada)
- **PRD V2** → `PRD_V2.md` (ada, disinkronisasi dengan auditor)
- **Alur EPIC**: `MASTER_TASKS.md` (ada, dilaksanakan)
- **Pemeriksaan:** `docs/audit/CURRENT_STATE.md`

### Pathway QR Codes

Direkomendasikan untuk memungkinkan scanner-kode QR (di aplikasi web dashboard) untuk beralih cepat ke:

- [[EPIC_00_REPORT]](docs/audit/CURRENT_STATE.md)
- [[PRD_V2]](PRD_V2.md)
- [[SUPERVISOR_REFERENCE]](src/agents/supervisor.py)
- [[DEPARTMENT_GUIDE]](src/agents/departments.py)

(Generate QR code markdown setelah PRM DIBUTUHKAN)

---

## Dokumen FAANG HALANG

| Dokumen | Isi | Lokasi |
|----------|------|--------|
| `README.md` | Struktur monorepo, README cepat | Root |
| `CHANGELOG.md` | Riwayat rilis | Root |
| `PRD_V2.md` | Spesifikasi PRD saat ini | Root |
| `docs/audit/CURRENT_STATE.md` | Status saat ini + perubahan dikurangi | `docs/audit/` |
| `docs/audit/AUDIT_EPIC00_DETAILED.md` | Audit EPIC 00 yang luas | `docs/audit/` |
| `docs/audit/AUDIT_EPIC00.md` | Checklist tingkat tinggi | `docs/audit/` |

---

## Mengecek Prerequisite Deployment

### Framework

- Python 3.11+, Node.js ≥18, PostgreSQL, Redis, MT5 terminal
- `services/python/.venv` virtual env (pip install -r requirements.txt)
- `package-lock.json` (workspace-level) untuk kepastian, platform Node.js

### Environment 

- File `.env` (contoh di `.env.example`)
- `CONFIG_VALIDATE` → `node config-validate.js`

### Isi CI/CD

- `docs/development-setup.md` (panduan manual)
- `MASTER_BUILD_PROMPT.md` (CI flows)
- `MASTER_TASKS.md` (eksekusi)

---

## Keputusan Lintas EPIC

- **Orkestrasi:** Supervisor sebagai router utama (policy default `all_match`).
- **Enforcement:** `RiskGate` deterministik **wajib dipanggil di pipeline** sebelum eksekusi (fail-closed),
  **dan kini ditegakkan di executor** (fix B-3, commit `02a577c`): `ExecutionEngine(require_approval=True)`
  menolak order tanpa `approval_token` (fail-closed). Catatan: `POST /mt5/orders/execute` masih menuju
  permukaan paper/refusing connector (bukan executor). Detail: `docs/audit/RELEASE_READINESS_REPORT.md`.
- **Dependency:** Semua agent test diverifikasi lewat pytest.
- **Integrasi:** Node backend + frontend — dirakit melalui NPM workspaces, Docker Compose opsional.

---

## Next EPIC Quick View

| Tasks |
|-------|
| MCP client untuk MT5 (bisa menulis order) |
| Monetary gate (Forex/CFDs) hard limits (risiko max-trade, max-drawdown) |
| Validasi MT5 real-time (koneksi, tick) |
| Operational dashboard widget (status real-time) |

---

**Author:** [ChatCohere]  
**Date:** 2026-09-14  
**Revisi audit RC:** disinkronkan dengan source & test commit `cfc8551` (lihat `docs/audit/RELEASE_READINESS_REPORT.md`)
