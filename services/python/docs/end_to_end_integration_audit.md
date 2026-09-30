# END-TO-END INTEGRATION AUDIT — Phase 1–6 Runtime Verification

## REAL RUNTIME PATH (verified in code)

```
MarketFeedLoop / scheduler.enqueue
  → OrchestrationRuntime.run_cycle / scheduler → TradingPipeline.run(event, context)
  → supervisor.analyze() → AgentSynthesizer.generate_proposal()
  → _complete_proposal (ATR SL/TP + sizing + _cap_lot)
  → B6 _zone_entry_plan → ZoneEntryGate + _evaluate_canonical_trigger
  → RiskGate.validate_proposal → approval_token
  → _build_order_request → ExecutionEngine.execute_order (order_locator, durable ledger)
  → MT5 native (armed-terminal gate) / simulation
  → confirm_execution + sync_position + reconciliation guard
  → result_hook → telegram signal lifecycle
  → position monitor → TRADE_CLOSE → ReviewAutoTrigger → lesson store +
     LearningEngineV2 + telegram
```

Callers/callees verified:
- scheduler.py:154 `pipeline.run(event, context)`; runtime.py:420 same.
- pipeline B6:722 `_zone_entry_plan`; gate at runtime.py:143; trigger gate
  `pipeline._evaluate_canonical_trigger` (Phase 4.5).
- RiskGate → approval_token (pipeline.py:765) → engine require_approval.
- Review leg: main.py:155 `_on_review` → lesson store + signal lifecycle;
  runtime.py:155 monitor wiring + TRADE_CLOSE enqueue.

## DORMANT / TEST / PAPER / DEMO PATHS

| Path | Classification | Evidence |
|------|---------------|----------|
| `CommitteeOrchestrator.run()` | DORMANT (additive) | No production caller; tests + smoke only |
| `CanonicalModelRouter.execute()` | ADVISORY (human text) | Only caller: `LLMAdvisor.advise` |
| `learning.canonical/review_store/research_phase5` | DORMANT (tests only) | No production importer outside tests |
| `mt5/endpoints /orders/execute`, `write_guard.send_order` | PAPER | simulation path, no live broker |
| `demo/demo_trading.py` | DEMO | own engine instance |
| `ZoneEntryGate._pending` + `EntryLifecycleManager` | LIVE pending-memory + canonical primitive | Both kept, different layers |
| Legacy `entry_zone.build_entry_plan` | ADAPTER (levels-only) | Gated by trigger since 4.5 |
| `intelligence.synthesize()` legacy winner | OBSERVABILITY/TEST | Production `analyze()` uses dominance gate |

## AUTHORITY MAP

| Decision | Authority | Status |
|----------|-----------|--------|
| Event detection | deterministic feed/scheduler | SINGLE ✓ |
| Market evidence | specialists + normalize | SINGLE ✓ |
| Market hypothesis | MarketLead + synthesis (evidence-weighted) | SINGLE ✓ |
| Setup validity | SetupCandidate + lifecycle | SINGLE ✓ |
| Trigger confirmation | TriggerEngine (+ adapter) | SINGLE ✓ |
| Entry state | DecisionState + EntryAssessment | SINGLE ✓ |
| Final risk decision | RiskGate | SINGLE ✓ |
| Final volume | MoneyManager._cap_lot | SINGLE ✓ |
| Order execution | ExecutionEngine | SINGLE ✓ |
| Broker state | MT5 + reconciliation guard | SINGLE ✓ |
| Trade outcome | TradeReviewer (deterministic) | SINGLE ✓ |
| Research metrics | ResearchEngine + PatternObserver | SINGLE ✓ |
| Strategy promotion | LifecycleGovernor + PromotionGate + HUMAN | SINGLE ✓ |

No decision has two authorities. legacy counts/scores are observability-only.

## INTEGRATION FINDINGS

### P0 — none found.
No AI→MT5 path, no gate bypass, no volume bypass, no auto-promotion path,
no future-leakage path in the live chain (all verified by grep + tests).

### P1 — CRITICAL INTEGRATION GAP
1. **Phase 5 canonical learning is dormant in production.** The live review leg
   (ReviewAutoTrigger → lesson store → LearningEngineV2) works, but NOTHING
   writes DecisionSnapshot/TradeReview/DecisionReview/CounterfactualReview/
   PatternObservation into `CanonicalStore`, and nothing enqueues
   `ResearchQueue`. Phase 5 is unit-complete but runtime-disconnected.
   FIX: small best-effort bridge from the live review hook (fail-closed,
   never blocks trading).

### P2 — HIGH
2. **CommitteeOrchestrator dormant by design** — documented additive path;
   the supervisor/synthesis path remains the live committee. Not a defect,
   but the two must not diverge: keep orchestrator tested (done).
3. **setup_id continuity gap**: pipeline proposals carry proposal_id/trace_id
   but no canonical setup_id; Phase 5 lineage expects setup_id end-to-end.
   FIX: best-effort setup_id passthrough (no behavior change when absent).

### P3 — DEBT
4. `intelligence.synthesize()` legacy winner pattern retained for tests.
5. Dual pending stores (ZoneEntryGate._pending vs EntryLifecycleManager).
6. `LearningJournal` in-memory; DecisionGraph vs DecisionSnapshot overlap.
7. Advisor rebuilds a router per call (cheap; could share singleton).

## IDENTITY CONTINUITY

Live chain: event_id → trace_id → decision_id → proposal_id →
client_order_id → execution_id → ticket → review record → lesson.
`setup_id` is STABLE within trigger-engine/zone lifecycle but NOT stamped onto
pipeline proposals (finding P1-2, fixed by passthrough).

## CONTRACTS (boundary → required → authority → failure)

- Event→Supervisor: {event_type, symbol, market data} → proposal|None; fail→WAIT.
- Supervisor→Gate: {symbol, direction, entry/SL/TP, size} → GateDecision; fail→BLOCK.
- Gate→Engine: OrderRequest+approval_token → ExecutionResult; fail→403/409/400.
- Engine→MT5: armed-terminal gate; timeout→UNKNOWN→locator→adopt|retry.
- MT5→Reconciliation: Reconciler report; critical→BLOCK new orders.
- Close→Review: ReviewAutoTrigger record → lesson store (durable JSONL).
- Review→Research: **MISSING IN PRODUCTION** (P1-1, fixed by bridge).

## TEMPORAL / LOOKAHEAD — PASS

DecisionSnapshot raises on information>decision timestamps. Trigger engine uses
only data ≤ evaluated bar (tested). Counterfactual uses decision-time entry;
both-targets-hit → INVALID. Backtest windows explicit.

## MODEL ROUTER — PASS (by design)

Phase 6 router serves the ADVISORY path only (LLMAdvisor). The decision path
is intentionally deterministic (no LLM in trigger/gate/volume/execution/
reconciliation). No inversion exists.

## BUDGET / ESCALATION — PASS

Cycle ledger reserve→commit/refund; advisor commits through supervisor budget;
router depth/fan-out/escalation caps; debate max_rounds. No unbounded path found.

## FAILURE SAFETY — PASS

Missing/stale data → WAIT/BLOCK/UNKNOWN at every boundary (tested Phases 1–4).
Trigger error → WAIT (no legacy fallback). Research crash isolated (queue).
Review failure never blocks trading (try/except at every hook).

## EXECUTION BOUNDARY — PASS

Only: validated decision → RiskGate → MoneyManager → OrderBuilder →
ExecutionEngine. Grep confirms no other live broker surface.

## LEARNING BOUNDARY — PASS (with P1-1 wiring fix)

Review→Research→Candidate exists in code; nothing mutates ACTIVE strategy
(ReadOnlyDict + gate + no setter surface; static audit clean).

## RESTART / DURABILITY — PASS

Order ledger, intents, kill-switch, entry context, lesson stores are durable
JSONL; idempotency consults the durable ledger; CanonicalStore reloads on init.

## CONCURRENCY — PASS

Entry claims (setup,trigger,candle) exactly-once across threads (tested 4/8/20
threads); engine registry lock; store locks.

## OBSERVABILITY — PASS with P2 note

Every boundary logs reason_codes/blocking/missing/evidence_refs; shadow
verdicts logged per zone cycle; telemetry per LLM call. Phase 5 canonical
records become queryable once the bridge lands (P1-1).

## COST/METADATA — PASS

SymbolSpecification → spread/commission → sizing → gate; UNKNOWN preserved
(commission_source, spread_known flags; cost_known=False ledgers).

## FILES CHANGED (this audit)

- `src/learning/review_bridge.py` (NEW): best-effort live-review →
  canonical DecisionReview/TradeReview + CanonicalStore + ResearchQueue.
- `src/main.py`: wire bridge into `_on_review` (try/except, never blocks).
- `src/orchestration/pipeline.py`: best-effort setup_id passthrough on
  proposals (no behavior change when absent).
- `tests/test_e2e_integration.py` (NEW): E2E-01..E2E-12.

## REMAINING TECHNICAL DEBT

P3 items 4–7 above; orchestrator unification deferred; EntryPlan unification
deferred; session/ATR windows configured-inactive.

## LIVE TRADING — DISABLED
