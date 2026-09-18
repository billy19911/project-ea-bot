# PHASE 1 — Fundamental Analyst Logic

> Bagian dari [MASTER_PLAN.md](./MASTER_PLAN.md) | Status: READY

## Goal

Ubah `FundamentalAnalystAgent` dari stub `UNSUPPORTED` menjadi agent analisis fundamental
deterministik yang mengonsumsi data kalender ekonomi real-time dari `NewsFeedProvider`.

## Lokasi

- **Baru:** `services/python/src/agents/analysts/fundamental_analyst.py`
- **Referensi stub:** `services/python/src/agents/base.py:316-348` (dihapus setelah migrasi)
- **Data source:** `services/python/src/market/news_feed.py` → `get_news_feed_provider()`
- **Test:** `services/python/tests/test_fundamental_analyst.py` (baru)

## Desain Logika

### Input
`analyze(context)` menerima context dict. Sumber data fundamental:
1. `context["economic_events"]` (opsional, dari pipeline) — list event ekonomi
2. Fallback: `get_news_feed_provider().fetch_calendar()` — fetch live calendar ForexFactory

### Skoring Deterministik (3 komponen)

**A. High-Impact Event Risk** — event mendekat = risiko tinggi
- Hitung event dengan impact `High`/`Critical` dalam window tertentu.
- Event berdampak pada currency pair → tambah `risk_score`.
- Alasan: trader tidak buka posisi besar menjelang NFP/FOMC.

**B. Hawkish/Dovish Bias** — dari judul event + berita
- Lexicon hawkish: `rate hike, hawkish, tighten, raise rates, strong jobs, beat forecast`.
- Lexicon dovish: `rate cut, dovish, ease, stimulus, weak jobs, miss forecast`.
- Net bias → signal direction (USD kuat = bearish XAUUSD, dst).

**C. Data Surprise** — actual vs forecast (bila tersedia)
- `forecast` vs `previous` dari `EconomicEventItem`: arah surprise.
- Tidak ada actual value di feed → pakai forecast-vs-previous sebagai proxy arah.

### Output Contract (WAJIB — dibaca Supervisor)

```python
{
    "agent": "fundamental_analyst",
    "status": "OK",                      # atau "UNSUPPORTED" bila feed offline
    "supported": True,
    "signal": "BULLISH" | "BEARISH" | "NEUTRAL",
    "confidence": 0.0-1.0,
    "reasons": ["...", "..."],
    "event_count": int,
    "metrics": {
        "high_impact_events": int,
        "net_bias": float,               # -1.0 .. +1.0
        "bias_label": "HAWKISH" | "DOVISH" | "NEUTRAL",
        "event_risk": "LOW" | "MEDIUM" | "HIGH",
    },
}
```

### Fail-closed
- Feed offline / exception → `status="UNSUPPORTED"`, `signal="NEUTRAL"`, `confidence=0.0`.
- Tidak ada event relevan → `NEUTRAL`, confidence `0.55` (konsisten dgn NewsSentimentAgent).

## Langkah Implementasi

1. Tulis test dulu (TDD): `tests/test_fundamental_analyst.py`
   - test event hawkish → BULLISH (USD) 
   - test event dovish → BEARISH
   - test no events → NEUTRAL 0.55
   - test feed offline (mock raise) → UNSUPPORTED, tidak crash
   - test high-impact event dekat → confidence turun / risk HIGH
2. Implement `FundamentalAnalystAgent(BaseAgent)`:
   - `__init__`: `name="fundamental_analyst"`, `agent_type="fundamental"`, priority NORMAL
   - `capabilities`: `economic_calendar`, `earnings_analysis`
   - `analyze(context)`: implement skoring A+B+C
   - `_load_events(context)`: context dulu, fallback provider, exception-safe
3. Update `src/agents/analysts/__init__.py` — export agent baru.
4. Update `src/agents/base.py` — hapus stub `FundamentalAnalystAgent`, tambah import alias backward-compat bila ada referensi lama.
5. Update `src/main.py` — register `FundamentalAnalystAgent()` di `register_default_agents()`.
6. Cek `supervisor.py` routing `"EARNINGS_"` / `"ECONOMIC_"` → sudah benar, tidak perlu ubah.

## Acceptance Criteria

- [x] `pytest tests/test_fundamental_analyst.py` — semua pass
- [x] Full suite pass (`pytest tests/ -q`)
- [x] `flake8 --max-line-length=100` bersih
- [x] Agent terdaftar di registry setelah startup
- [x] Feed offline → tidak crash, return UNSUPPORTED

## Commit Message

```
feat(agents): implement deterministic FundamentalAnalystAgent

Replace the UNSUPPORTED stub with a rules-based fundamental analyst that
consumes the live economic calendar feed (ForexFactory via NewsFeedProvider).
Scores high-impact event risk, hawkish/dovish bias, and forecast surprises.
Fails closed to UNSUPPORTED when the feed is unreachable.
```
