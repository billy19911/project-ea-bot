# PHASE 5 DISCOVERY REPORT — Learning, Research & Strategy Evolution

## Existing Components

### Review (`src/review/`)
| File | Class / Function | Status |
|------|------------------|--------|
| trade_review.py | `TradeReviewer` (MAE/MFE, win/loss, timing/decision/execution scores) | REAL, tested |
| advanced_review.py | `classify_root_cause`, `attribute_strategy_vs_execution` (setup vs exec quality split) | REAL |
| advanced_review.py | `TradePattern`, `extract_patterns` | REAL (basic grouping) |
| advanced_review.py | `SessionAnalysis`, `analyze_by_time` | REAL |
| advanced_review.py | `CounterfactualReview`, `review_no_trade` (counterfactual_pnl, avoided/missed flags) | REAL but THIN — uses subsequent price move, no point-in-time guard, no WOULD_* taxonomy |
| advanced_review.py | `CommitteeQuality`, `evaluate_committee_quality` | REAL |
| advanced_review.py | `LearningJournal`, `JournalEntry` (in-memory) | REAL but in-memory only |
| decision_graph.py | `DecisionGraph`/`DecisionGraphStore` (EVENT→…→REVIEW stages, replay from snapshots) | REAL, PRD §45 |
| entry_context.py + persistence/entry_context_store.py | ticket-keyed entry context bridge (JSONL) | REAL, durable |
| close_detector.py, auto_trigger.py, r_multiple.py, intelligence.py, performance_intelligence.py | close detection, R-multiple, bucket stats (INSUFFICIENT_SAMPLE aware) | REAL |

### Research (`src/research/`)
| File | Status |
|------|--------|
| engine.py `ResearchEngine` | REAL: Hypothesis/StrategyVersion/Experiment/BacktestResult dataclasses, `create_*`, `compute_metrics`, `run_backtest`, `_simulate` (ema/rsi/macd), `_walk_forward`, provenance store |
| backtest_v2.py, walk_forward_v2.py (`WalkForwardValidator`), monte_carlo.py | REAL |
| store.py `ResearchStore`, scheduler.py, endpoints.py | REAL (persist + API) |

### Memory / Learning / Paper / Demo / Live-readiness / Strategy
| Area | Status |
|------|--------|
| memory/ (trade/semantic/strategy/research/working) | REAL stores |
| learning/ (engine_v2, lesson_store JSONL, feedback, loop) | REAL persistent lessons |
| paper/ (paper_account, simulated_execution) | REAL simulation |
| demo/ (demo_trading, stability) | REAL |
| live_readiness/ (certification gate + evidence) | REAL |
| strategy/registry.py (`VersionedStrategy`, StrategyStatus lifecycle, ReadOnlyDict for ACTIVE) | REAL |
| strategy/lifecycle.py (`LifecycleGovernor`: DRAFT→…→PRODUCTION, REJECTED→ARCHIVED; promotion proposal/result) | REAL |

## Storage

- JSONL append-only: lessons, engine_v2, entry_context, research_state, intents, order_state.
- `ResearchStore` (research persistence), `DecisionGraphStore` (in-memory + replay).
- `LearningJournal` in-memory only (gap: not durable).

## Lineage (existing, partial)

DecisionGraph: EVENT→MARKET_SNAPSHOT→…→TRADE_PROPOSAL→RISK_CHECKS→EXECUTION→
BROKER_RESULT→POSITION→RESULT→REVIEW with shared decision_id/event_id/trade_id/
execution_id/strategy_version. Entry context bridged by ticket. Research runs
carry hypothesis/experiment/dataset provenance. Strategy lifecycle has audit[].

GAP: no single immutable `DecisionSnapshot` object with
information_timestamp ≤ decision_timestamp enforcement; no canonical lineage
chain review→pattern→hypothesis→experiment→candidate→approval in ONE traceable
record (pieces exist in separate stores).

## Gaps (must build in Phase 5)

1. **DecisionSnapshot immutable + point-in-time guard** — none exists as a
   canonical frozen object; decision_graph nodes are mutable dicts without
   timestamp enforcement.
2. **DecisionReview store (non-trade)** — `review_no_trade` is a one-shot
   function, not a persisted idempotent record keyed by event identity.
3. **Counterfactual point-in-time safety** — existing `review_no_trade` takes
   `subsequent_price_move` as an argument (caller could inject future-best
   prices); no WOULD_HAVE_WON/LOST/BREAKEVEN/NOT_TRIGGERED/INSUFFICIENT_DATA
   taxonomy; no decision-time entry-model rule.
4. **PatternObservation canonical** — `TradePattern`/`extract_patterns` are
   basic; no sample-size/uncertainty discipline object, no regime×setup×
   trigger×session matrix object, no INSUFFICIENT_SAMPLE status on the object.
5. **Research query capability** — metrics exist per-module; no single
   deterministic query surface (setup/trigger/regime/session/WAIT/reject).
6. **Negative knowledge store** — rejected/failed records exist implicitly
   (status fields) but no unified KNOWN_FALSE/UNCERTAIN/SUPPORTED ledger.
7. **Review→research async queue** — no queue; review runs inline or not at all.

## Overlaps (do NOT duplicate)

- Hypothesis/Experiment/BacktestResult/WalkForward → REUSE `research.engine`
  (extend, don't rewrite).
- StrategyVersion/lifecycle/promotion → REUSE `strategy.registry` +
  `strategy.lifecycle` (extend statuses/evidence, don't fork).
- TradeReview MAE/MFE/scores → REUSE `review.trade_review` (extend with
  canonical fields, don't rewrite).
- Counterfactual thin impl → EXTEND `review.advanced_review` semantics via a
  new point-in-time-safe module, keep old function for compat.
- Lessons → REUSE `learning.lesson_store` JSONL.
- Paper/demo → REUSE `paper/` + `demo/` (no new simulators).

## Migration / Adapter Plan

New module `src/learning/canonical.py` (frozen dataclasses):
`DecisionSnapshot`, `TradeReview`, `DecisionReview`, `CounterfactualReview`,
`PatternObservation`, `HypothesisRecord`, `ExperimentRecord`,
`WalkForwardRecord`, `StrategyCandidateRecord`, `PromotionRecord`,
`NegativeKnowledgeRecord` — all JSONL-persistable, idempotent by identity.

New module `src/learning/review_queue.py`: durable JSONL queue
TRADE_CLOSED → persist review → enqueue research (async, failure-isolated).

New module `src/learning/research_queries.py`: deterministic query surface
over the persisted records (no LLM needed).

Adapters: bridge existing `TradeReviewer`/`ResearchEngine`/`LifecycleGovernor`
outputs into canonical records (wrap, don't fork). Promotion gate stays in
`strategy/lifecycle.py` + `strategy/registry.py` (extend evidence checks;
manual approval stays mandatory; no auto-promote code added anywhere).
