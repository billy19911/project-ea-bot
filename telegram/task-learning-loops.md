# TASK T3 — Wire 2 dead AI learning loops into production close path (Python)

## Context (verified root cause — do NOT re-investigate)
- `news_patterns.record_outcome` (`services/python/src/market/news_patterns.py:196`) and `agent_memory.record_outcome` (`services/python/src/agents/agent_memory.py:115`) are defined but **NEVER called outside tests**.
- `services/python/src/main.py:132-153` wires `_on_review(record)` which persists a lesson and updates the Telegram signal, but does NOT call either `record_outcome`.
- The close path is: `close_detector.on_position_closed` → `auto_trigger.trigger_review` → `_on_review(record)`.
- The `record` dict arriving in `_on_review` carries the review data including `agent_outputs` (dict of per-agent analyses) and `trade_result` (dict with `pnl`, `direction`, `symbol`, etc.) from `simulated_execution.py`.
- `news_patterns.jsonl` does NOT exist — the store has never been written to.
- `agent_memory.py:AgentMemoryStore` is a singleton created via `get_agent_memory()`.
- `news_patterns.py:NewsPatternStore` is a singleton created via `get_news_pattern_store()`.

## Deliverable
Wire both `record_outcome` calls into `_on_review` in `services/python/src/main.py` so that every reviewed trade feeds back into the learning stores.

### 1. agent_memory wiring (inside `_on_review`)
After the existing lesson + signal blocks (after line ~150), add a new try/except block:

```python
try:
    from agents.agent_memory import get_agent_memory
    mem = get_agent_memory()
    trade_result = (
        record.get("trade_result") or record.get("result") or {}
        if isinstance(record, dict) else
        (record.trade_result if hasattr(record, "trade_result") else {})
    )
    agent_outputs = (
        record.get("agent_outputs", {})
        if isinstance(record, dict) else
        getattr(record, "agent_outputs", {})
    )
    direction = str(trade_result.get("direction", "NEUTRAL")).upper()
    pnl = float(trade_result.get("pnl", 0.0))
    correct = pnl > 0
    symbol = str(trade_result.get("symbol", ""))
    regime = str(trade_result.get("regime", "unknown"))
    for agent_name, agent_data in agent_outputs.items():
        conf = float(agent_data.get("confidence", 0.0)) if isinstance(agent_data, dict) else 0.0
        mem.record_outcome(
            agent=agent_name,
            direction=direction,
            correct=correct,
            regime=regime,
            confidence=conf,
            symbol=symbol,
        )
except Exception:  # noqa: BLE001 - learning must never break review
    logger.warning("Agent memory recording failed (review continues)")
```

### 2. news_patterns wiring (inside `_on_review`, after agent_memory block)
```python
try:
    from market.news_patterns import get_news_pattern_store
    nps = get_news_pattern_store()
    trade_result = (
        record.get("trade_result") or record.get("result") or {}
        if isinstance(record, dict) else
        (record.trade_result if hasattr(record, "trade_result") else {})
    )
    news_events = (
        record.get("news_events", [])
        if isinstance(record, dict) else
        getattr(record, "news_events", [])
    )
    symbol = str(trade_result.get("symbol", ""))
    pnl = float(trade_result.get("pnl", 0.0))
    for evt in news_events:
        if isinstance(evt, dict) and evt.get("title"):
            nps.record_outcome(
                title=str(evt.get("title", "")),
                country=str(evt.get("country", "XX")),
                impact=str(evt.get("impact", "low")),
                symbol=symbol,
                realised_return=pnl,
                forecast=str(evt.get("forecast", "")),
                actual=str(evt.get("actual", "")),
            )
except Exception:  # noqa: BLE001 - learning must never break review
    logger.warning("News pattern recording failed (review continues)")
```

### Key shapes (verified from codebase)
- `AgentMemoryStore.record_outcome(agent, direction, correct, regime, confidence, symbol)`
- `NewsPatternStore.record_outcome(title, country, impact, symbol, realised_return, forecast, actual, horizon="H1")`
- `trade_result` keys: `pnl`, `direction`, `symbol`, `regime` (from `simulated_execution.py` close path).
- `news_events` = list of dicts from pipeline analysis context (may be empty; safe iteration).
- `agent_outputs` = dict keyed by agent name from pipeline analysis context.

## Tests (TDD — write tests first, then implement)
New file `services/python/tests/test_learning_loop_wiring.py`.

Required cases:
1. `_on_review` with valid `trade_result` + `agent_outputs` dict → `agent_memory.record_outcome` called once per agent with correct args.
2. `_on_review` with valid `trade_result` + `news_events` list → `news_patterns.record_outcome` called once per event.
3. `_on_review` with empty `agent_outputs` / empty `news_events` → no crash, no calls.
4. `_on_review` with missing `trade_result` → no crash, graceful skip.
5. `_on_review` with `record_outcome` raising exception → swallowed, review continues.
6. Existing lesson persist + signal lifecycle calls still happen (mock verify).

Test approach: patch `get_agent_memory` and `get_news_pattern_store` to return mocks; call `_on_review` with a test record; assert calls.

Run SERIAL from `services/python`:
`services/python/.venv/Scripts/python.exe -m pytest tests/test_learning_loop_wiring.py -q`

## Verify before finishing
- `services/python/.venv/Scripts/python.exe -m pytest tests/test_learning_loop_wiring.py -q`
- `services/python/.venv/Scripts/python.exe -m flake8 src/main.py tests/test_learning_loop_wiring.py --max-line-length=100 --extend-ignore=E203,W503`
- `services/python/.venv/Scripts/python.exe -m black --line-length 100 <only your changed files>`

## Hard constraints
- Only edit: `services/python/src/main.py` (patch `_on_review` only, minimal diff), `services/python/tests/test_learning_loop_wiring.py` (new).
- Do NOT touch `services/python/src/config.py`.
- Do NOT reformat unrelated code; keep the diff minimal.
- Do NOT run restart scripts (`restart-py.ps1` / `restart-all.ps1` / `run_ops_drills.py`) and do NOT wait for services.
- Do NOT use `&` in shell commands. Do NOT commit.
- Report in your final message: files changed, exact test commands + results, and any deviation.
