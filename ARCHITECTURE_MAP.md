# ARCHITECTURE_MAP.md

**Tujuan:** Terpusatkan semua dokumen referensi sistem, diagram, dan jalur kritis untuk EPIC 01–30.  Catatan ini bertujuan untuk memastikan tim dapat dengan cepat:

1. **Menemukan** artifact yang menentukan arah (ARDS, PRD V2, diagram alur)
2. **Memverifikasi** prerequisite untuk deployment (runtime, dependency, environment)
3. **Melacak** keputusan penting (workflow, kepemilikan, pengecualian)
4. **Memverifikasi** status saat ini (ceklist + file `CURRENT_STATE.md` di `docs/audit`)

---

## Ringkasan EPIC 00 (Audit Compliance)

- ✅ **Compliance verified**: 577 tests passing (including new department, registry, supervisor, permission tests)
- ✅ **Safety boundary 5/5**: Risk Gate, token budget, concurrency, duplicate prevention, permission guards
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
|| EPIC 04 | Market Intelligence Department (analyst aggregation & consensus) | `src/market/` | **Complete**
| EPIC 05 | Risk Intelligence Department (advisory only) | `src/risk/intelligence.py` | **Complete** |
| EPIC 07 | Deterministic Risk & Safety (KillSwitch, CircuitBreaker) | `src/risk/` | **Complete** |
| EPIC 08 | Execution Engine (OrderBuilder, RecoveryEngine) | `src/execution/` | **Complete** |
| EPIC 09 | Position Monitoring (lifecycle, trailing, abnormal detection) | `src/monitoring/` | **Complete** |
| EPIC 11 | Advanced Trade Review (root-cause, patterns, journal) | `src/review/` | **Complete** |
| EPIC 12 | Research Engine (hypotheses, experiments, backtests) | `src/research/` | **Complete** |
| EPIC 13 | Strategy Versioning & Promotion (registry, gates, activation) | `src/strategy/` | **Complete** |
| EPIC 14 | Learning Loop (review→pattern→hypothesis→experiment→validation) | `src/learning/` | **Complete** |
| EPIC 15 | Dashboard & Control Plane (16 halaman, 13 endpoint) | `apps/web/app/control-plane/`, `apps/api/` | **Complete** |

---

## Document Junction

### Keputusan Desain

- **Department Lead**: Dipilih melalui skema `role = "department_lead"` → Supervisor rutes ke leads terlebih dahulu.
- **Agent metadata**: `role`, `permissions`, `dependencies`, `model_policy`, `timeout_seconds` dEFINISI sebagai atribut `BaseAgent` sehingga direktori agen di registry dapat diQuery (get_by_role, get_by_permission).
- **Permission guards**: Dekorator `require_permission` yang kuat (Lemari besi bisa melakukan operasi Dangerous.

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

## Keputusan Lintas EPIC (TINGGAL)

- **Orkestrasi:** Supervisor sebagai router utama
- **Enforcement:** Hard-coded `RiskGate` mandatory (bahkan LLM tidak bisa bypass)
- **Dependency:** Saat ini, semua agent tests memverifikasi dan menjalankan melalui pytest
- **Integrasi:** Headers Node + backend + frontend — dirakit melalui NPM workspaces, Docker Compose opsional

---

## Next EPIC (EPIC 02) Quick View

| Tasks |
|-------|
| MCP client untuk MT5 (bisa menulis order) |
| Monetary gate (Forex/CFDs) hard limits (risiko max-trade, max-drawdown) |
| Validasi MT5 real-time (koneksi, tick) |
| Operational dashboard widget (status real-time) |

---

**Author:** [ChatCohere]  
**Date:** 2026-09-14  
**Updated by:** [Anda dapat mengedit]
