# DEEP E2E FIX PLAN — Project EA Bot

**Companion to:** `docs/audit/DEEP_E2E_AUDIT.md`
**Baseline commit:** `51e6470` (+ P0 fixes applied in-session)
**Purpose:** exact implementation order for the remaining audit findings. P0 items are already fixed; this plan covers the OPEN items only.

> Rule: do NOT implement P1/P2/P3 automatically unless the change is small, isolated, and clearly safe. Each fix below lists the test that must accompany it.

---

## Implementation order (do in this sequence)

1. **P1-2** Wire breaker guard → 2. **P1-3** real account context → 3. **P1-1** retry idempotency →
4. **P0-3 follow-up** real reconciliation providers → 5. **P1-4** lot-step/digits normalization →
6. **P1-5** promotion gate enforcement → 7. **P1-6** live trade→review→learning →
8. P2 items → 9. P3 items.

Rationale: fail-closed gates first (they prevent unsafe trades), then correctness of inputs, then the "learning/governance" layer.

---

## P1 — HIGH

### P1-2. Wire `DependencyBreakers` into the production pipeline
- **Problem:** The §24 execution circuit breaker exists but is never injected; the pipeline's `dependency_guard` is `None` in production.
- **Root cause:** `OrchestrationRuntime._build_pipeline()` does not construct/pass a guard; `DependencyBreakers` has no production instantiation.
- **Affected files:** `src/orchestration/runtime.py`, `src/risk/dependency_breakers.py` (consumer), `src/orchestration/pipeline.py` (already supports it).
- **Proposed change:** Instantiate a process-wide `DependencyBreakers` in `runtime.py`; pass `dependency_guard=breakers`; feed breaker outcomes from the feed loop, execution engine, and LLM calls (record_success/record_failure). Expose via an existing endpoint.
- **Risk:** Low — the pipeline already handles the guard fail-closed; worst case is over-blocking.
- **Test required:** `test_dependency_breaker_wiring.py` — open the EXECUTION breaker → assert pipeline BLOCKED and no `execute_order` call; healthy breaker → EXECUTED.
- **Expected result:** An open execution circuit blocks new orders end-to-end.

### P1-3. Supply real account/positions/market to the risk gate in autonomous mode
- **Problem:** In the scheduler path the pipeline's `_build_validation_inputs` falls back to zeroed account state; the gate is not account-aware.
- **Root cause:** `runtime.py` `context_provider` returns only news context; no account/position/market provider.
- **Affected files:** `src/orchestration/runtime.py` (context provider), a new `mt5`-backed provider, `src/orchestration/pipeline.py` (no change if context keys are filled).
- **Proposed change:** Build a context provider that reads `connector.get_account_info()`, `connector.get_positions()`, and current spread; merge with news context. Fail-safe: on error, return the news context only (current behavior).
- **Risk:** Medium — must not block the loop if MT5 is down; wrap in try/except.
- **Test required:** `test_autonomous_risk_context.py` — with a fake connector, assert the pipeline's gate receives non-zero equity/positions; with MT5 down, assert the cycle still completes.
- **Expected result:** The risk gate evaluates against real account state in autonomous cycles.

### P1-1. Idempotent retry on lost response (Scenario F)
- **Problem:** The retry loop re-sends on `CONNECTION`/`timeout` without verifying whether a prior attempt landed → duplicate positions possible.
- **Root cause:** `ExecutionEngine.execute_order` retries `_send_to_mt5` blindly.
- **Affected files:** `src/execution/engine.py`, `src/execution/state_machine.py`.
- **Proposed change:** Before each retry after a transport/timeout error, query the broker for an existing order/position matching the client order id / magic+symbol+volume+recent-time; if found, treat as filled (idempotent success) instead of resending. Persist intent before first send.
- **Risk:** Medium — broker queries vary; must be conservative (only skip resend when a *matching* order is found).
- **Test required:** `test_execution_retry_idempotency.py` — connector that "loses" the first response but records the order; assert exactly one order is created across retries.
- **Expected result:** Retry never creates a second position when the first actually landed.

### P0-3 follow-up. Real reconciliation providers
- **Problem:** The reconciliation *gate* is now wired, but production providers are no-ops, so the gate always sees "clean".
- **Root cause:** `OrchestrationRuntime` defaults `reconciliation_providers=None`.
- **Affected files:** `src/orchestration/runtime.py`, new `mt5`-backed providers, `src/execution/reconciliation_runner.py` (no change).
- **Proposed change:** Implement `MT5ReconciliationProviders` mapping internal ledger ↔ `connector.get_positions()`/`get_orders()`; inject in production wiring.
- **Risk:** Medium — provider errors are already fail-safe but `last_ok=False` on error would block orders; intended (fail-closed) but should be observable.
- **Test required:** `test_reconciliation_providers.py` — fake connector with an orphan broker position → report critical → pipeline BLOCKED.
- **Expected result:** Real internal↔MT5 divergence blocks new orders.

### P1-4. lot-step / price-digits normalization
- **Problem:** Volume/prices are sent raw; broker rejects or reconciliation reports spurious mismatches.
- **Root cause:** `OrderBuilder` does not consult `SymbolSpec` (`symbol_spec.py`/`symbol_resolver.py` exist, unused here).
- **Affected files:** `src/execution/order_builder.py`, `src/execution/engine.py`, `src/mt5/symbol_spec.py` (consumer).
- **Proposed change:** Accept an optional symbol-spec source; snap volume to `volume_step` within `[min,max]`, round price/SL/TP to `digits`.
- **Risk:** Low-Medium — must not silently change a user intent; log any adjustment.
- **Test required:** `test_order_builder_normalization.py` — `0.123` → `0.12`; price rounded to digits.
- **Expected result:** Orders are broker-valid; reconciliation noise reduced.

### P1-5. Enforce the strategy promotion gate
- **Problem:** `PromotionGate.can_promote` is never called; `activate` has no evidence requirement.
- **Root cause:** `StrategyRegistry.activate` bypasses the gate; `LifecycleGovernor` unreachable.
- **Affected files:** `src/strategy/registry.py`, `src/strategy/endpoints.py`, `src/strategy/lifecycle.py`.
- **Proposed change:** Call `can_promote` inside `activate`; return 409 with reason when evidence is missing; expose a gated POST for lifecycle `propose`/`advance`.
- **Risk:** Low — governance-only, no execution coupling (verified).
- **Test required:** `test_strategy_promotion_gate.py` — activate without evidence → rejected; with evidence → allowed.
- **Expected result:** No strategy can be marked ACTIVE without validation evidence.

### P1-6. Live trade → review → learning path
- **Problem:** No production path closes a position, so the learning loop is not driven by live trades.
- **Root cause:** `ExecutionEngine` has no close/exit; only the unwired paper engine closes positions.
- **Affected files:** `src/execution/engine.py` or `src/monitoring/position_monitor.py`, `src/review/auto_trigger.py`.
- **Proposed change:** Add a deterministic close path (or wire `position_monitor` TP/SL-hit detection to trigger `ReviewAutoTrigger.on_position_closed`).
- **Risk:** HIGH — this path can close real positions; implement behind explicit enable + tests; do NOT auto-enable.
- **Test required:** `test_trade_close_review_loop.py` — a close event produces a review + lesson in the persistent store.
- **Expected result:** Closed live trades feed the lesson store.
- **NOTE:** Confirm with the operator whether live close is even in scope before implementing.

---

## P2 — MEDIUM

| # | Problem | Root cause / files | Proposed change | Test |
|---|---|---|---|---|
| P2-1 | `AppShell` fakes LIVE/DEGRADED realtime | `apps/web/components/AppShell.tsx:287-294` | Drive from the real WS/health feed or remove the fake toggle | web test / manual |
| P2-2 | Position monitor misses external SL/TP change, partial close, disappearance; no write path | `src/monitoring/position_monitor.py` | Diff successive position sets; emit events; add an apply path (gated) | `test_position_monitor_detection.py` |
| P2-3 | Fixed orchestration (1 lead/cycle) | `supervisor.py:115,280`; `runtime.py:162` | Decide policy (`all_match`/`priority_based`); wire real planner or document as intended | `test_supervisor_policy.py` |
| P2-4 | No committee debate; dissent unused | `synthesis.py:241`; `intelligence.py:751` | Consume `unresolved_conflict` to force WAIT; add a challenge round | `test_committee_challenge.py` |
| P2-5 | Unstructured specialist output | `analysts/*` | Emit the existing `EvidenceItem` schema; standardize `reasoning` key | analyst tests |
| P2-6 | Decision-quality conflates outcome | `src/review/trade_review.py:181` | Remove the `+25 if WIN`; score process independently | `test_trade_review.py` |
| P2-7 | Hardcoded contract/equity fallbacks | `position_monitor.py:603,613`; `write_guard.py:76`; `main.py:307` | Read from symbol spec / real account | targeted tests |
| P2-8 | Dead/data-less endpoints | `v2_endpoints.py:588`; decision replay | Populate or clearly mark NO_DATA | endpoint tests |
| P2-9 | `write_guard.send_order` stub; fail-open checks | `src/mt5/write_guard.py:140-190` | Implement real send or delete; make checks fail-closed | `test_mt5_write_guard.py` |
| P2-10 | Fictional exposure math | `write_guard.py:76-78` | Use real account/price inputs | unit test |
| P2-11 | Live secrets in `.env.runtime` on disk | `.env.runtime` (gitignored) | Rotate; keep out of any backup/share | n/a (ops) |
| P2-12 | Wide-open `cors()`; WS token in query | `apps/api/src/index.ts:62`; `websocket.ts:56` | Explicit origin allowlist; move token off query | api tests |
| P2-13 | Two `risk_gate.py` modules | `trading/risk_gate.py` vs `risk/gate.py` | Consolidate or document (`/health` uses the former) | n/a |
| P2-14 | Research modules unwired; walk-forward ignores params; MC thin | `research/*` | Wire `backtest_v2`/`walk_forward_v2`; implement param re-fit; re-simulate under perturbed costs | research tests |
| P2-15 | In-memory order state machine | `execution/state_machine.py:58` | Persist to DB if durable lifecycle is required | state tests |

---

## P3 — LOW

| # | Problem | File | Change |
|---|---|---|---|
| P3-1 | `MismatchEvent.timestamp` default is a format string | `order_builder.py:178-182` | Use `time.time()` factory |
| P3-2 | Docstring claims SL/TP mismatch detection; code = volume only | `order_builder.py:214,251` | Fix doc or add SL/TP check |
| P3-3 | Symbol suffix handling inconsistency | `engine.py` vs `symbol_resolver.py` | Route through resolver |
| P3-4 | Duplicate `FundamentalAnalystAgent` (stub vs real) | `agents/base.py:429` vs `analysts/` | Rename the stub or delete |
| P3-5 | `ResearchInbox.transition` no state validation | `research/scheduler.py:125` | Validate allowed transitions |
| P3-6 | Overview page no loading indicator | `apps/web/app/page.tsx` | Add a loading state |

---

## Definition of done (per fix)

For each item above:
1. **Problem, root cause, affected files, proposed change, risk, test, expected result** are already specified above.
2. Implement the change in an isolated commit.
3. Add the listed test; ensure it **fails before** and **passes after** the change.
4. Run the full Python suite (`pytest tests/`) — must stay green.
5. Run `black --check`, `isort --check-only`, `flake8` — must be clean.
6. Update `docs/audit/DEEP_E2E_AUDIT.md` status for the affected component.

---

## Verification commands

```powershell
# Tests
& "services\python\.venv\Scripts\python.exe" -m pytest services\python\tests\ -q

# Style
& "services\python\.venv\Scripts\python.exe" -m black --check services\python\src services\python\tests
& "services\python\.venv\Scripts\python.exe" -m isort --check-only services\python\src services\python\tests
& "services\python\.venv\Scripts\python.exe" -m flake8 services\python\src --max-line-length=100 --extend-ignore=E203,W503

# Node API + Web (from repo root)
npm test --workspace=project-ea-bot-api
npm run lint --workspace=project-ea-bot-web
npx --workspace=project-ea-bot-web tsc --noEmit
```
