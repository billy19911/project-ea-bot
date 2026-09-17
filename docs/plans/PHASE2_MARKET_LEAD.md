# PHASE 2 — MarketLead Intelligence Upgrade

> Bagian dari [MASTER_PLAN.md](./MASTER_PLAN.md) | Status: PENDING FASE 1

## Goal

Tingkatkan kecerdasan `MarketLead`:
1. Tambah **Market Regime Detection** — kenali kondisi pasar saat ini (Trending, Ranging, High Volatility/News Shock).
2. Tambah **Adaptive Specialist Weighting** — bobot analis disesuaikan dengan rezim (bukan fixed weight).
3. Sambungkan ke **agent produksi nyata** (`TechnicalAnalystAgent`, `StructureAnalystAgent`, `MomentumAnalystAgent`, `VolatilityAnalystAgent`, `NewsSentimentAgent`, `FundamentalAnalystAgent`), bukan stub mini duplikat.
4. Perbaiki **Supervisor compatibility**:
   - `agent_type = "department_lead"` (bukan `"lead"`).
   - `can_handle(event_type, context)` (signature sesuai BaseAgent).
   - `analyze()` return plain dict yang dimengerti Supervisor.
5. Daftarkan di `main.py` sehingga Supervisor otomatis mendeteksi dan mendelegasikan event pasar ke `MarketLead`.

## Lokasi

- **File utama:** `services/python/src/market/intelligence.py`
- **Register:** `services/python/src/main.py:register_default_agents()`
- **Test:** `services/python/tests/test_market_intelligence.py` + `test_market_lead_v2.py` (baru)

## Desain Logika Baru (Ilmu Tambahan)

### 1. Market Regime Detection (3 Rezim)

| Rezim | Indikator Kunci | Bobot Dominan | Bobot Dikurangi |
|-------|----------------|----------------|-----------------|
| **TRENDING** | ADX > 25, trend != "NEUTRAL" | Technical (0.30), Momentum (0.25) | Structure (0.15) |
| **RANGING / SIDEWAYS** | ADX < 20, trend == "NEUTRAL" | Structure (0.35) — S/R levels | Momentum (0.10) |
| **NEWS SHOCK / VOLATILITY** | Ada high-impact event / ATR spike / IV tinggi | News (0.30), Fundamental (0.30) | Technical (0.10) |

Deteksi deterministik dari data di `context`:
- `context.get("market_state")` → `adx_value`, `trend_direction`
- `context.get("volatility")` / `context.get("atr")`
- `context.get("sentiment")` / `context.get("economic_events")`

### 2. Adaptive Specialist Weighting

Alih-alih `reliability` fixed 0.5:
```python
def get_weights(regime: str) -> dict[str, float]:
    if regime == "TRENDING":
        return {
            "TechnicalAnalyst": 0.30, "MomentumAnalyst": 0.25,
            "StructureAnalyst": 0.15, "VolatilityAnalyst": 0.10,
            "NewsSentimentAnalyst": 0.10, "FundamentalAnalyst": 0.10,
        }
    elif regime == "RANGING":
        return {
            "StructureAnalyst": 0.35, "TechnicalAnalyst": 0.20,
            "VolatilityAnalyst": 0.15, "MomentumAnalyst": 0.10,
            "NewsSentimentAnalyst": 0.10, "FundamentalAnalyst": 0.10,
        }
    elif regime == "NEWS_SHOCK":
        return {
            "NewsSentimentAnalyst": 0.30, "FundamentalAnalyst": 0.30,
            "VolatilityAnalyst": 0.15, "TechnicalAnalyst": 0.10,
            "MomentumAnalyst": 0.10, "StructureAnalyst": 0.05,
        }
    # DEFAULT_BALANCED
    return {k: 1.0/6 for k in [...]}
```

Total bobot selalu = 1.0.

### 3. Kompatibilitas Supervisor (Bug Fixes)

```python
class MarketLead(BaseAgent):
    def __init__(self):
        super().__init__(
            name="market_lead",                      # huruf kecil, konsisten dgn routing
            agent_type="department_lead",            # FIX BUG #1: Supervisor bisa deteksi
            description="Leads Market Intelligence Department with adaptive regime weighting",
            priority=AgentPriority.HIGH,
        )

    def can_handle(self, event_type: str, context: dict[str, Any]) -> bool:
        # FIX BUG #2: signature cocok BaseAgent.can_handle(event_type, context)
        # Handle semua event market
        market_prefixes = ("TREND_", "MOMENTUM_", "RSI_", "STOCH_", "EMA_", "MACD_",
                           "BREAKOUT", "BREAKDOWN", "REVERSAL", "STRUCTURE_", "PRICE_ACTION",
                           "LEVEL_SCAN", "MARKET_", "VOLATILITY_", "NEWS_", "SOCIAL_",
                           "EARNINGS_", "ECONOMIC_")
        return any(event_type.startswith(p) for p in market_prefixes) or event_type == "MARKET_CHECK"

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        # FIX BUG #3: return plain dict, bukan AnalystReport
        decision = self.synthesize_with_regime(context)
        return {
            "agent": self.name,
            "role": "department_lead",
            "department": "market",
            "signal": decision.direction,
            "confidence": decision.confidence,
            "reasons": [decision.rationale] + decision.agreements,
            "regime": decision.regime,
            "committee_decision": decision.to_dict(),
            "specialist_results": {r.analyst: r.to_dict() for r in decision.reports},
            "unresolved_conflict": len(decision.conflicts) > 0,
        }
```

### 4. Backward Compatibility

Method `synthesize(market_data: dict) -> CommitteeDecision` tetap dipertahankan
sebagai wrapper di atas `synthesize_with_regime` agar tes lama (`test_market_intelligence.py`)
tidak patah.

## Langkah Implementasi

1. Tulis test baru: `tests/test_market_lead_v2.py`
   - test regime detection (trending vs ranging vs news_shock)
   - test adaptive weighting sesuai rezim
   - test `can_handle` cocok BaseAgent signature
   - test `analyze` return dict kompatibel Supervisor
   - test backward-compatibility `synthesize`
2. Update `src/market/intelligence.py`:
   - Tambah `FundamentalAnalyst` ke specialists committee
   - Tambah method `detect_regime(context) -> str`
   - Tambah method `get_adaptive_weights(regime) -> dict`
   - Update `_weighted_consensus` menggunakan bobot adaptif
   - Fix `agent_type="department_lead"`, nama `"market_lead"`
   - Fix `can_handle` dan `analyze`
3. Update `src/main.py`: register `MarketLead()` di `register_default_agents()`.
4. Jalankan `pytest tests/test_market_intelligence* tests/test_market_lead_v2.py` — semua pass.
5. Cek integrasi: `test_supervisor_department_routing.py` tetap pass.

## Acceptance Criteria

- [ ] MarketLead terdaftar sebagai `agent_type="department_lead"` di registry
- [ ] Supervisor otomatis route event pasar ke `market_lead`
- [ ] Deteksi rezim: Trending (ADX>25), Ranging (ADX<20), News Shock (ada high impact)
- [ ] Bobot adaptif berubah sesuai rezim
- [ ] Semua tes lama + baru pass
- [ ] Flake8 bersih
