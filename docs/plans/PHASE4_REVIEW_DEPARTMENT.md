# PHASE 4 — Review Department & PostTradeReviewAgent

> Bagian dari [MASTER_PLAN.md](./MASTER_PLAN.md) | Status: PENDING FASE 3

## Goal

Buat departemen baru: **Review Department** dengan `PostTradeReviewAgent` yang
menganalisis hasil trade (win/loss) untuk mengekstrak pelajaran (lessons) dan
menyimpan ke `trade_memory.py` storage. Departemen ini dipimpin oleh `ReviewLead`
sebagai `department_lead` ketiga (selain MarketLead & RiskLead).

## Lokasi

- **Agent baru:** `services/python/src/agents/analysts/review_agent.py`
- **Lead baru:** `services/python/src/review/intelligence.py` (pattern: risk/intelligence.py)
- **Storage existing:** `services/python/src/memory/trade_memory.py` (sudah ada, jangan modifikasi)
- **Register:** `services/python/src/main.py`
- **Test:** `services/python/tests/test_review_agent.py` + `tests/test_review_lead_wiring.py`

## Desain

### PostTradeReviewAgent

Agent spesialis yang:
1. Menerima data trade hasil (entry, exit, P/L, duration, symbol, strategy).
2. Menentukan apakah trade **good** (followed plan) atau **bad** (deviated from plan).
3. Mengekstrak **lesson learned** (rule, bukan narasi).
4. Menyimpan lesson ke `TradeMemoryStore`.

```python
class PostTradeReviewAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="post_trade_review",
            agent_type="review",
            description="Reviews closed trades to extract lessons",
            priority=AgentPriority.LOW,  # post-trade, tidak time-critical
        )

    def can_handle(self, event_type: str, context: dict[str, Any]) -> bool:
        return event_type.startswith("TRADE_CLOSE") or event_type == "POST_TRADE_REVIEW"

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        trade = context.get("closed_trade", {})
        if not trade:
            return self._unsupported("No closed trade data")
        # Deterministic review
        outcome = trade.get("outcome")  # "win" / "loss" / "breakeven"
        signal_used = trade.get("signal")  # BULLISH/BEARISH
        actual_direction = trade.get("actual_direction")
        followed_plan = (signal_used == actual_direction)
        lessons = self._extract_lessons(trade, outcome, followed_plan)
        # Store to memory
        store = get_trade_memory_store()
        store.add_lesson(lessons)
        return {
            "agent": self.name,
            "signal": "NEUTRAL",           # review doesn't signal direction
            "confidence": 0.8,
            "reasons": lessons,
            "outcome": outcome,
            "followed_plan": followed_plan,
            "lessons_extracted": len(lessons),
        }
```

### ReviewLead (Department Lead)

Pattern sama dengan MarketLead / RiskLead:
- `agent_type="department_lead"`
- `can_handle` event `TRADE_CLOSE` / `POST_TRADE_REVIEW`
- `analyze()` return dict kompatibel Supervisor
- Komite: `PostTradeReviewAgent` (single specialist for now)

```python
class ReviewLead(BaseAgent):
    def __init__(self):
        super().__init__(
            name="review_lead",
            agent_type="department_lead",
            description="Leads Review Department (post-trade analysis)",
            priority=AgentPriority.MEDIUM,
        )

    def can_handle(self, event_type: str, context: dict[str, Any]) -> bool:
        return event_type.startswith("TRADE_CLOSE") or event_type == "POST_TRADE_REVIEW"

    def analyze(self, context: dict[str, Analy] -> dict[str, Any]:
        result = self.post_trade_review.analyze(context)
        return {
            "agent": self.name,
            "role": "department_lead",
            "department": "review",
            "signal": result["signal"],
            "confidence": result["confidence"],
            "reasons": result["reasons"],
            "specialist_results": {result["agent"]: result},
        }
```

### Trade Memory Storage (SUDAH ADA — JANGAN MODIFIKASI)

`src/memory/trade_memory.py` punya `TradeMemoryStore`. Baca strukturnya sebelum implement
untuk memastikan method yang tersedia (`add_lesson`, `get_lessons`, dst).

## Langkah Implementasi

1. Baca `src/memory/trade_memory.py` — catat API public.
2. Tulis test: `tests/test_review_agent.py`
   - test review win trade → lessons about good entry
   - test review loss trade → lessons about wrong direction
   - test review breakeven → NEUTRAL
   - test no trade data → UNSUPPORTED
   - test lesson stored to memory (mock store)
3. Tulis test: `tests/test_review_lead_wiring.py`
   - test `agent_type == "department_lead"`
   - test `can_handle("TRADE_CLOSE", {})` → True
   - test `can_handle("TREND_UP", {})` → False
   - test `analyze` return dict
4. Implement `src/review/intelligence.py` (ReviewLead).
5. Implement `src/agents/analysts/review_agent.py` (PostTradeReviewAgent).
6. Update `src/agents/analysts/__init__.py` — export.
7. Update `src/main.py` — register ReviewLead + PostTradeReviewAgent.

## Acceptance Criteria

- [ ] `PostTradeReviewAgent` punya logika review deterministik
- [ ] Lesson disimpan ke `trade_memory.py` store
- [ ] `ReviewLead` terdaftar sebagai `department_lead`
- [ ] Supervisor route event `TRADE_CLOSE` ke `review_lead`
- [ ] 3 department leads aktif (market, risk, review)
- [ ] Full suite pass
- [ ] Flake8 bersih
