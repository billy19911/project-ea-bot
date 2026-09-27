# TASK T2 — B-4 demo harness must send SL/TP (Python script + tests)

## Context (verified — do NOT re-investigate)
- `scripts/b4_demo_validation.py` builds the live DEMO order WITHOUT SL/TP:
  - `_build_request()` (~line 404-428) constructs `OrderRequest(symbol, order_type="BUY", volume, price=0.0, magic, comment)` — `sl`/`tp` fall back to `0.0`.
  - `_order_check()` (~line 430-469) sends the payload with `"sl": 0.0, "tp": 0.0`.
- The B-4 plan requires "SL/TP diset". The production path always sets SL = ATR*1.5 / TP = ATR*3.0 via `MoneyManager.calculate_sl_tp` (`services/python/src/risk/money_management.py:93-110`). The harness must use the SAME helper — no separate formula, no guessing.

## Deliverable — `scripts/b4_demo_validation.py`
1. `_build_request(symbol_info)`:
   - Entry price = current tick ask (reuse the harness's existing tick access, `self._tick`).
   - Resolve ATR: `mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_H1, 0, 15)` -> compute with the EXISTING indicator in `services/python/src/trading/indicators.py` (read `atr(...)` signature first — grep how it is called elsewhere; use the same call shape).
   - **Fail-closed**: missing/empty rates or ATR <= 0 -> raise `ValidationAbort("cannot resolve ATR for SL/TP (fail-closed)")`. NO order without SL/TP.
   - `sl, tp = MoneyManager().calculate_sl_tp(entry_price=ask, direction="long", atr_value=atr)`; round both to `symbol_info.digits`.
   - Build `OrderRequest(..., sl=sl, tp=tp)`.
   - Extend `self.evidence["request"]` with `"sl": sl, "tp": tp`.
2. `_order_check()`: use the SAME sl/tp so the payload carries `"sl": sl, "tp": tp` (no longer 0.0). Update call sites so the request/sl/tp flows in (find where `_order_check` is called; pass what you need — e.g. keep the built request on `self` or pass it as an argument).
3. `_verify_fill(ticket)`: when the position appears, compare `pos.sl`/`pos.tp` against the requested values (tolerance: round to symbol digits). Record:
   - `self.evidence["sl_tp_attach"] = {"requested": {"sl":..., "tp":...}, "observed": {"sl":..., "tp":...}, "matched": bool}`
   - `self._record("fill_verify_sl_tp", matched, "...")`.
   - A mismatch logs a WARNING and records ok=False but must NOT abort (the position is already open; the run must still report and continue).
4. The dry-run path keeps working (dry-run = order_check only, no submit).

## Tests — update `services/python/tests/test_b4_demo_validation.py`
- FakeMT5: add `copy_rates_from_pos` returning deterministic bars and the `TIMEFRAME_H1` constant. FakePosition already has `sl`/`tp` (line ~84-85) — set them from the request in the fake fill flow if needed.
- Cases (new or updated):
  1. built `OrderRequest` has `sl != 0.0`, `tp != 0.0`, and equals the MoneyManager formula for the fake ATR (assert exact expected numbers).
  2. the captured `order_check` payload has `sl`/`tp` equal to the request values (capture payload in FakeMT5).
  3. `evidence["request"]` contains sl/tp.
  4. ATR unresolvable (copy_rates returns empty/None) -> harness aborts with the fail-closed message and does NOT call order_check.
  5. `_verify_fill` records `sl_tp_attach.matched is True` on match; and `False` + warning on mismatch (run still completes, no exception).
- Run SERIAL from `services/python`: `services/python/.venv/Scripts/python.exe -m pytest tests/test_b4_demo_validation.py -q`
- NOTE: the harness lives at repo root `scripts/`; the test loads it by path. Keep that mechanism working.

## Verify before finishing
- pytest above, then `-m flake8 scripts/b4_demo_validation.py tests/test_b4_demo_validation.py --max-line-length=100 --extend-ignore=E203,W503`
- `-m black --line-length 100 scripts/b4_demo_validation.py tests/test_b4_demo_validation.py`

## Hard constraints
- Only edit: `scripts/b4_demo_validation.py`, `services/python/tests/test_b4_demo_validation.py`.
- Do NOT touch the live service, do NOT run restart scripts, do NOT wait for services, do NOT submit any real/demo order.
- Do NOT use `&` in shell commands. Do NOT commit.
- Report in your final message: files changed, exact test commands + results, and any deviation.
