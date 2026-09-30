# Phase 5 — Learning Architecture

## Canonical pipeline (src/learning/)

```
DecisionSnapshot (frozen, information_timestamp ≤ decision_timestamp)
  → TradeReview (outcome vs decision-quality split) / DecisionReview (non-trade)
  → CounterfactualReview (decision-time entry model, WOULD_* taxonomy)
  → PatternObservation (sample-size-aware stats; INSUFFICIENT_SAMPLE < 30)
  → HypothesisRecord (testable, falsifiable, lineage)
  → ExperimentRecord (reproducible: seed, dataset, window, cost model)
  → WalkForwardRecord (TRAIN < VALIDATION < TEST)
  → StrategyCandidateRecord (PROPOSAL_ONLY, never auto-activated)
  → PromotionRecord (gate_passed + approval_required, human approves)
  → NegativeKnowledgeRecord (KNOWN_FALSE/UNCERTAIN/SUPPORTED)
```

## Modules

| File | Responsibility |
|------|----------------|
| `canonical.py` | 11 frozen dataclasses + taxonomies (outcome/counterfactual/knowledge/hypothesis) |
| `review_store.py` | `CanonicalStore` (durable JSONL, idempotent), `ReviewBuilder` (deterministic review construction), `ResearchQueue` (async, failure-isolated) |
| `research_phase5.py` | `PatternObserver` (§7–9), `ResearchQueries` (§23), `PromotionGate` (§17–18) |

## Reuse (not duplication)

- MAE/MFE timing/decision/execution scoring → `review.trade_review.TradeReviewer`.
- Hypothesis/Experiment/BacktestResult/WalkForward dataclasses + engine →
  `research.engine.ResearchEngine` (extended, not forked).
- WalkForward windows → `research.walk_forward_v2.WalkForwardValidator`.
- Strategy lifecycle → `strategy.lifecycle.LifecycleGovernor` (gated promotion,
  APPROVED/PRODUCTION only via `propose()`); versioning → `strategy.registry`
  (ReadOnlyDict for ACTIVE).
- Lessons → `learning.lesson_store` JSONL. Paper/demo → `paper/` + `demo/`.

## Data lineage

`review_id` links snapshot → trade/decision review → counterfactual →
patterns (`source_review_ids`) → hypothesis (`source_pattern_ids`) →
experiment (`hypothesis_id`) → candidate (`hypothesis_ids`, `experiment_ids`)
→ promotion (`candidate_id`). Every object carries strategy_version,
evidence_refs, reason_codes.

## Research queries (deterministic, no LLM)

`ResearchQueries(store).performance_by(dimension)` (setup/trigger/regime/
session), `.decision_outcomes()` (WAIT/NO_TRADE/REJECTED/EXPIRED/INVALIDATED
counts), `.risk_reject_reasons()` (gate/blocking histogram).

## Promotion safety

`PromotionGate.evaluate` checks 8 separate metrics (sample, expectancy,
drawdown, walk-forward, cost, regime/session/direction robustness) — never a
fused score. `decision` stays PENDING; `approve()` requires a non-empty human
identity AND gate_passed=True, else raises. No auto-promote code path exists
(static-audited).
