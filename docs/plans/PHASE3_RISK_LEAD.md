# PHASE 3 — RiskLead Wiring & Upgrade

> Bagian dari [MASTER_PLAN.md](./MASTER_PLAN.md) | Status: PENDING FASE 2

## Goal

Sambungkan `RiskLead` (`src/risk/intelligence.py`) ke sistem produksi dengan
interface yang kompatibel Supervisor, tanpa mengubah logika analisis risk yang sudah ada
(365 baris kode + test `test_risk_intelligence.py` sudah berjalan).

## Lokasi

- **File utama:** `services/python/src/risk/intelligence.py`
- **Register:** `services/python/src/main.py`
- **Test existing:** `services/python/tests/test_risk_intelligence.py`
- **Test baru:** `services/python/tests/test_risk_lead_wiring.py`

## Masalah (Bug sama dengan MarketLead)

1. `agent_type` kemungkinan `"lead"` → Supervisor tidak deteksi. Cek & fix ke `"department_lead"`.
2. `can_handle(task_type)` signature lama → fix ke `can_handle(event_type, context)`.
3. `analyze()` return `RiskAssessmentReport` dataclass → tambah adapter dict
   (atau ubah return jadi dict, dengan tetap expose report via key `risk_report`).
4. Belum di-register di `main.py`.

## Penting: JANGAN Ubah Logika Risk

- `RiskGate` (`src/risk/gate.py`) dan `RiskEngine` (`src/risk/engine.py`) adalah **deterministic gate** —
  jangan sentuh. RiskLead adalah **advisory layer** di atasnya (PRD §7).
- Semua tes existing (`test_risk_intelligence.py`, `test_deterministic_risk_gate.py`) harus tetap pass.
- 4 risk analysts di komite (`DrawdownAnalyst`, `ExposureAnalyst`, `CorrelationAnalyst`, `VolatilityRiskAnalyst` atau
  nama aktual di file) tetap dipertahankan.

## Desain

### Interface Adapter

```python
class RiskLead(BaseAgent):
    def __init__(self):
        super().__init__(
            name="risk_lead",
            agent_type="department_lead",           # FIX
            description="Leads Risk Intelligence Department (advisory)",
            priority=AgentPriority.HIGH,
        )

    def can_handle(self, event_type: str, context: dict[str, Any]) -> bool:
        risk_prefixes = ("RISK_", "DRAWDOWN_", "EXPOSURE_", "CORRELATION_",
                         "RISK_CHECK", "PORTFOLIO_", "MARGIN_")
        return any(event_type.startswith(p) for p in risk_prefixes)

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        report = self.assess(context)  # logic lama, tidak diubah
        return {
            "agent": self.name,
            "role": "department_lead",
            "department": "risk",
            "signal": "RISK_ON" | "RISK_OFF" | "NEUTRAL",   # mapping dari report
            "confidence": report.confidence,
            "reasons": report.findings,
            "risk_report": report.to_dict(),
            "veto": report.veto,          # bila RiskLead punya hak veto (cek file)
        }
```

### Registrasi Supervisor

Cek `supervisor.py` routing untuk event `RISK_` — tambah bila belum ada.
Supervisor sudah generik mencari `department_lead` via `registry.get_by_type()`,
jadi begitu RiskLead terdaftar + `can_handle` cocok, otomatis terpakai.

### Safety (KRITIS)

- RiskLead **tidak boleh** memicu order eksekusi.
- Semua output advisory — Risk Gate deterministik tetap pemegang keputusan akhir.
- MT5 tetap read-only (`armed=false`).

## Langkah Implementasi

1. Baca `src/risk/intelligence.py` lengkap — catat nama class & method aktual.
2. Tulis test: `tests/test_risk_lead_wiring.py`
   - test `agent_type == "department_lead"`
   - test `can_handle("RISK_CHECK", {})` → True
   - test `can_handle("TREND_UP", {})` → False
   - test `analyze()` return dict dengan key wajib
   - test logic lama tidak berubah (regression dari test_risk_intelligence.py)
3. Update `src/risk/intelligence.py` — fix interface, pertahankan logika.
4. Update `src/main.py` — register `RiskLead()`.
5. Jalankan: `pytest tests/test_risk_intelligence.py tests/test_risk_lead_wiring.py tests/test_deterministic_risk_gate.py -q`.

## Acceptance Criteria

- [ ] `RiskLead` terdaftar sebagai `department_lead`
- [ ] `can_handle` kompatibel + `analyze` return dict
- [ ] Semua tes risk existing pass (tidak ada regresi)
- [ ] Tidak ada perubahan pada `gate.py` / `engine.py`
- [ ] Flake8 bersih
