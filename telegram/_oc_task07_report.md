[0m
All changes are within TASK 07 scope. Let me update the todo and produce the completion report.
TASK 07 complete. Here is the completion report.

---

# COMPLETION REPORT — TASK 07

**TASK:** 07 — RISK / FINAL ORDER INVARIANT
**STATUS: PASS**

## FILES CHANGED
- `services/python/src/risk/gate.py` — added monetary-risk check + broker contract-size resolver.
- `services/python/src/orchestration/pipeline.py` — final-order re-validation (single-terminal path) + `final_order` on the result.
- `services/python/src/execution/fanout.py` — broker-spec augmentation + byte-parity guard on the built request.
- `services/python/src/orchestration/runtime.py` — `MAX_RISK_PCT` env wires the production gate.
- `services/python/tests/test_task07_final_order_risk.py` — 16 new tests (STOP GATE 07).
- `services/python/tests/test_deterministic_risk_gate.py` — added `monetary_risk` to the required-shape set.
- `CHANGELOG.md` — TASK 07 entry.

## ROOT CAUSE
1. The deterministic `RiskGate.validate_proposal` never checked **monetary SL risk** (`abs(entry−SL)×contract_size×volume`) and never used the broker contract size / failed closed on a missing spec.
2. **Ordering violation (Risk Gate → normalize → execute):** the pipeline gate validated `validation["proposal"]` (only snap-DOWN normalized by `_cap_lot`), but `OrderBuilder._normalise_to_spec` then snapped the volume to the **nearest** broker step (can round UP) and rounded prices *after* the gate. The exact order sent could differ from the approved order.
3. The canonical fan-out gate received empty `market_info` (no provider wired), so it could not see the real broker contract size/spread; and there was no explicit guard proving sent == approved.

## FIX
- **New check `monetary_risk`** in `RiskGate`: computes `risk_money = abs(entry − initial_SL) × contract_size × volume` from an explicit broker value (`market_info["contract_size"]`) or the live broker spec (`market.symbol_spec`, `source == "broker"`). A labelled **fallback** spec is never accepted. When `max_risk_pct` is configured → budget check with **FAIL CLOSED** if contract size/distance/volume cannot be proven (no invented fallback). Unconfigured → informational (records `risk_money`, `risk_contract_source`); preserves all existing call sites.
- **Final-order re-validation** (`TradingPipeline._revalidate_final_order`): after the order builder normalizes, if the built request differs from the gate-approved values, the gate is **re-run on the EXACT final values**; only then may execution proceed. `sent == approved` is recorded on `PipelineResult.final_order`.
- **Fan-out**: `_augment_market_info` backfills missing `contract_size`/`point`/`spread_limit` from the real broker spec; `_proposal_from_request` + `_differs_from_approved` re-validate the built request when it differs and record the exact sent values on the dispatch ledger.
- **Projected exposure** uses the existing `RiskEngine.check_projected_exposure` (current + proposed ≤ limit) now exercised with the final volume/price.
- **Runtime**: `MAX_RISK_PCT` (env, safety logic stays out of UI settings) configures the budget; unset → informational.

## TESTS
- `./.venv/Scripts/python.exe -m pytest services/python/tests/test_task07_final_order_risk.py -q` → **16 passed**
- `pytest services/python/tests -q --ignore=services/python/tests/test_trade_manager.py` → **3004 passed**
- Full suite `pytest services/python/tests -q` → **3012 passed, 1 failed**. The single failure (`test_trade_manager.py::test_manage_handles_multiple_positions_independently`) is **pre-existing and unrelated** — verified it also fails on clean HEAD (`bded560`) with my `src/`/test changes stashed.

Coverage maps to STOP GATE 07: monetary risk via market_info + broker spec; fail-closed on missing spec; invented-fallback rejected; projected exposure scenario F (25%+10%>30% → BLOCK); lot rounding **up and down**; `final sent == approved` (pipeline + fan-out); real-gate end-to-end block/allow.

## RUNTIME VERIFICATION
`_build_pipeline()` with `MAX_RISK_PCT=0.02` → `risk_gate._max_risk_pct == 0.02`; unset → `None`. `_revalidate_final_order` present; `ExecutionEngine.require_approval == True`; order_builder spec provider wired; fan-out coordinator uses the **same** gate instance and exposes the byte-parity helpers. `mt5.terminals.get_armed_terminals() == []` → **all terminals DISARMED by default**.

## REMAINING ISSUES
- Pre-existing unrelated failure in `test_trade_manager.py` (owned by a different area; fails on clean HEAD).
- Per-account live `positions_provider`/`account_state_provider` for fan-out still read from the target's account snapshot; a full per-account broker positions read (re-attach) belongs to TASK 08 (reconciliation/restart).
- Default runtime has `canonical_fanout_enabled` OFF, so production uses the single-terminal path (now final-order re-validated); fan-out path is verified by tests.

## NEXT TASK
NOT STARTED
