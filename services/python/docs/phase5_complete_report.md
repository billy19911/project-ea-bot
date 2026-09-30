# PHASE 5 — Learning, Research, Counterfactual & Strategy Evolution

## STATUS

COMPLETE

## DISCOVERY

- **existing components**: review/ (TradeReviewer MAE/MFE+scores, advanced_review
  root-cause/attribution/patterns/session/committee, thin CounterfactualReview,
  DecisionGraph, entry_context bridge, performance_intelligence), research/
  (ResearchEngine: Hypothesis/Experiment/BacktestResult + walk-forward + store +
  endpoints), memory/, learning/ (engine_v2, lesson_store JSONL, feedback, loop),
  paper/, demo/, live_readiness/ (certification gate), strategy/ (registry
  ReadOnlyDict ACTIVE, lifecycle governor with gated promotion).
- **storage**: JSONL append-only (lessons, entry_context, research_state,
  intents, order_state); DecisionGraphStore; LearningJournal in-memory only.
- **gaps**: no canonical immutable DecisionSnapshot w/ point-in-time guard; no
  persisted idempotent DecisionReview store; counterfactual not point-in-time
  safe + no WOULD_* taxonomy; no sample-size-disciplined PatternObservation;
  no deterministic research query surface; no unified negative-knowledge ledger;
  no async review→research queue.
- **overlaps (reused, not forked)**: MAE/MFE + scores, Hypothesis/Experiment/
  Backtest, walk-forward, strategy lifecycle/promotion, lessons, paper/demo.

Full detail: `docs/phase5_discovery_report.md`.

## IMPLEMENTATION

- `src/learning/canonical.py` — 11 frozen dataclasses (DecisionSnapshot,
  TradeReview, DecisionReview, CounterfactualReview, PatternObservation,
  HypothesisRecord, ExperimentRecord, WalkForwardRecord, StrategyCandidateRecord,
  PromotionRecord, NegativeKnowledgeRecord) + taxonomies.
- `src/learning/review_store.py` — CanonicalStore (durable idempotent JSONL),
  ReviewBuilder (deterministic review construction + point-in-time counterfactual),
  ResearchQueue (async, failure-isolated).
- `src/learning/research_phase5.py` — PatternObserver (sample-size aware),
  ResearchQueries (deterministic, no LLM), PromotionGate (8-metric, manual only).

- **TradeReview**: outcome-class split (GOOD/BAD × WIN/LOSS + BREAKEVEN) from
  deterministic criteria (decision_quality threshold + pnl sign).
- **DecisionReview**: WAIT/NO_TRADE/REJECTED/EXPIRED/INVALIDATED persisted,
  idempotent by event identity.
- **Counterfactual**: decision-time entry model, WOULD_HAVE_WON/LOST/
  BREAKEVEN/NOT_TRIGGERED/INSUFFICIENT_FUTURE_DATA/INVALID_COUNTERFACTUAL.
- **Pattern**: grouping by symbol/direction/zone/trigger/regime/session/…,
  wins/losses/BE, avg/median R, expectancy, PF, MAE/MFE, uncertainty,
  INSUFFICIENT_SAMPLE < 30.
- **Hypothesis**: testable/falsifiable with source pattern/review lineage.
- **Experiment**: reproducible (seed, dataset, window, cost/slippage model).
- **Backtest/Walk-forward**: reuse ResearchEngine + WalkForwardValidator;
  records carry dataset/version + TRAIN<VALIDATION<TEST order.
- **Paper/Demo**: reuse existing paper/demo (immutable strategy version).
- **Candidate/Version**: StrategyCandidateRecord PROPOSAL_ONLY; strategy
  registry/lifecycle immutable-by-construction (ReadOnlyDict ACTIVE).
- **Promotion Gate**: PromotionGate.evaluate → 8 separate metric checks,
  approval_required ALWAYS True, decision PENDING; approve() needs a human
  identity + gate_passed, else raises.

## DATA SAFETY

- point-in-time: DecisionSnapshot raises on information_timestamp >
  decision_timestamp; counterfactual entry = decision-time price only.
- lookahead protection: future high/low used ONLY for outcome classification;
  both-targets-reachable → INVALID_COUNTERFACTUAL.
- dataset versioning: ExperimentRecord carries dataset_id/window/cost/slippage/
  seed; WalkForwardRecord carries explicit windows.

## STRATEGY SAFETY

- immutable versions: frozen dataclasses + registry ReadOnlyDict for ACTIVE.
- no auto mutation: no setter/activate/apply API exists (static-audited).
- no auto promotion: PromotionGate.decision stays PENDING; approve() is the
  only path and requires a human identity + passing gate.
- manual approval: enforced (test_llm_recommendation_does_not_mutate_strategy,
  test_excellent_backtest_never_auto_activates).

## TESTS

```
Phase 5: 23 passed (18 required §25 + 5 adversarial)
Full Python: 2784 passed
Node/API: 61 passed
Adversarial: duplicate events → 1 record; future data blocked; small sample →
  INSUFFICIENT_SAMPLE; excellent backtest → candidate only; LLM change → no
  mutation; repeated losses → review only; candidate cannot touch RiskGate/
  broker constraints; research crash isolated; counterfactual point-in-time;
  EXPIRED/INVALIDATED no resurrect; reproducible experiment; walk-forward order;
  UNKNOWN stays UNKNOWN; lineage preserved.
```

## TECHNICAL DEBT

- The engine_v2/learning loop and the new canonical records coexist; unifying
  them into one runtime seam is future work.
- Backtest cost model detail depends on SymbolSpecification completeness
  (commission often UNKNOWN → recorded as such).
- DecisionGraph (PRD §45) and DecisionSnapshot overlap; a future phase can make
  DecisionGraph consume DecisionSnapshot as its MARKET_SNAPSHOT stage.
- LearningJournal remains in-memory; could migrate to CanonicalStore.

## LIVE TRADING

DISABLED (unchanged; no Phase 5 code path reaches MT5/RiskGate/ExecutionEngine).

## NEXT

STOP — do not start Phase 6 automatically.
