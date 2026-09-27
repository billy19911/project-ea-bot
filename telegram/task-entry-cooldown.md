# TASK T1 — Entry cooldown between signals + price-distance guard (Python)

## Context (verified root cause — do NOT re-investigate)
- `single_entry_policy` in `services/python/src/orchestration/pipeline.py` (~line 465-475, "Step B4") only blocks while one of OUR positions (matched by `entry_magic`) is OPEN.
- After the position closes, the very next event can open a new entry at almost the same price. This is the user's complaint (msg 130191: "masa tiap 2 mnt muncul entry baru trs padahal jarak untuk entry nya selisih sedikit").
- There is NO entry cooldown between successive entries and NO price-distance guard anywhere (grep + git log -S confirmed).

## Deliverable
Add BOTH guards to `TradingPipeline` in `services/python/src/orchestration/pipeline.py`:
1. **Entry cooldown**: when `entry_cooldown_s > 0`, a new entry for the same symbol is blocked if the last SUCCESSFUL entry for that symbol was less than `entry_cooldown_s` seconds ago.
2. **Price-distance guard**: when `entry_min_distance_atr > 0`, block when ATR > 0, a last-entry price exists, and `abs(new_entry_price - last_entry_price) < entry_min_distance_atr * atr`.

### Constructor (backward compatible)
- Add params `entry_cooldown_s: float = 0.0` and `entry_min_distance_atr: float = 0.0` (0.0 = disabled; existing tests/callers unaffected).
- State: `self._last_entries: dict[str, dict[str, float]] = {}` keyed by upper-case symbol, value `{"price": float, "ts": float}`.

### Guard placement in `run()`
- AFTER the Step B4 one-entry policy block and BEFORE the Step C execution block (~line 468-490). Mirror the exact style of the single-entry block:
  - If blocked: `result.status = STATUS_BLOCKED`, `result.risk_reason = <reason>`, `result.add_stage("entry_cooldown", STAGE_BLOCKED, <reason>)`, `result.add_stage("execution", STAGE_SKIPPED, "entry cooldown guard")`, `self._finalise(result)`, `return result`.
- Reason strings are user-facing (Telegram report). Examples: `f"entry cooldown: {remaining:.0f}s left for {symbol}"` and `f"jarak entry terlalu dekat: {distance:.5f} < {min_dist:.5f} ({k}xATR)"`.

### Resolve ATR deterministically
- Use the EXISTING helper `extract_price_atr(analysis_context)` from `trading/level_plan.py` (the same one the SL/TP completion already uses — grep `extract_price_atr` in pipeline.py). No new ATR math, no guessing. If ATR <= 0: skip ONLY the distance check; the time cooldown still applies.

### Record successful entries
- After an execution completes successfully (status EXECUTED / `result.executed is True` — find the exact point in `run()`), record `self._last_entries[symbol] = {"price": <entry price used in the order>, "ts": time.time()}`. Blocked/failed entries must NOT record.
- Entry price = the price used in the order request (proposal `entry_price`; fall back to `validation["market_info"]` ask/bid when <= 0). `float()` defensively; skip recording when price <= 0 (fail-open).

### Fail-open rules
- Any exception inside the guard is swallowed (`logger.debug`/`warning`) and must NOT block the cycle. The guard only blocks on positive evidence.

## Runtime wiring (production default ON) — `services/python/src/orchestration/runtime.py`
- Where `one_entry_policy` / `entry_magic` env reads happen (~line 155-168) and the `TradingPipeline(...)` construction (~line 180-191): read `ENTRY_COOLDOWN_S` (default `900`) and `ENTRY_MIN_DISTANCE_ATR` (default `1.0`) with the SAME try/except pattern used for `ONE_ENTRY_POLICY` (invalid -> default). Pass both into `TradingPipeline(...)`.
- DO NOT touch `services/python/src/config.py` (user-owned) and DO NOT touch `services/python/src/main.py` (user fix).

## Tests (TDD — write tests first, then implement)
New file `services/python/tests/test_entry_cooldown_guard.py`. Reuse the existing pipeline-test fakes (grep `TradingPipeline(` under `services/python/tests/` for the simplest fake supervisor/gate/engine setup that produces EXECUTED).
Required cases:
1. cooldown active: first cycle EXECUTED records the entry; immediate second cycle (same symbol) is BLOCKED with stage `entry_cooldown` and a reason.
2. cooldown elapsed (backdate `pipeline._last_entries[symbol]["ts"]` by e.g. -3600): second cycle proceeds.
3. distance guard: cooldown elapsed but new price within `< k*ATR` of the last entry -> BLOCKED (reason mentions distance).
4. distance OK: new price >= k*ATR away -> proceeds.
5. defaults 0.0/0.0 -> guard never blocks (two consecutive EXECUTED cycles pass).
6. ATR unavailable (0) -> distance check skipped, no crash, cooldown still enforced.
Run SERIAL (never two pytest processes at once), from `services/python`:
`services/python/.venv/Scripts/python.exe -m pytest tests/test_entry_cooldown_guard.py -q`

## Verify before finishing
- `services/python/.venv/Scripts/python.exe -m pytest tests/test_entry_cooldown_guard.py -q` plus the existing pipeline/runtime test files (find with `ls tests | grep -i pipeline` / `grep -i runtime`).
- `services/python/.venv/Scripts/python.exe -m flake8 src/orchestration/pipeline.py src/orchestration/runtime.py tests/test_entry_cooldown_guard.py --max-line-length=100 --extend-ignore=E203,W503`
- `services/python/.venv/Scripts/python.exe -m black --line-length 100 <only your changed files>`

## Hard constraints
- Only edit: `services/python/src/orchestration/pipeline.py`, `services/python/src/orchestration/runtime.py`, `services/python/tests/test_entry_cooldown_guard.py` (new).
- Do NOT reformat unrelated code; keep the diff minimal.
- Do NOT run restart scripts (`restart-py.ps1` / `restart-all.ps1` / `run_ops_drills.py`) and do NOT wait for services.
- Do NOT use `&` in shell commands. Do NOT commit.
- Report in your final message: files changed, exact test commands + results, and any deviation.
