# Phase 5 — Data Lineage & Counterfactual Protocol

## Lineage chain

```
event_id → DecisionSnapshot(snapshot_id, decision_timestamp, strategy/config version)
  → TradeReview(review_id, trade_id) | DecisionReview(review_id, event_id)
  → CounterfactualReview(counterfactual_id, review_id)
  → PatternObservation(pattern_id, grouping + stats)
  → HypothesisRecord(hypothesis_id, source_pattern_ids, source_review_ids)
  → ExperimentRecord(experiment_id, hypothesis_id, dataset, seed, cost model)
  → WalkForwardRecord(run_id, train<validation<test)
  → StrategyCandidateRecord(candidate_id, hypothesis_ids, experiment_ids)
  → PromotionRecord(promotion_id, candidate_id, gate, approval)
  → NegativeKnowledgeRecord(subject → KNOWN_*)
```

Stored in `CanonicalStore` (durable JSONL, identity-keyed, restart-safe).

## Point-in-time rules

1. `DecisionSnapshot` raises if `information_timestamp > decision_timestamp`.
2. Counterfactual entry MUST be the decision-time reference price; later best
   prices are never substituted.
3. Future high/low AFTER the decision classifies WOULD_HAVE_WON/LOST; if both
   SL and TP were reachable → INVALID_COUNTERFACTUAL (ambiguous order).
4. No counterfactual writes orders, intents, gate state, or strategy state.
5. Backtest/walk-forward dataset windows are explicit records; TRAIN <
   VALIDATION < TEST enforced by record construction.

## Research protocol

- Patterns are observations (sample size + uncertainty always shown);
  `INSUFFICIENT_SAMPLE` below 30 — no edge claims.
- Hypotheses must be testable + falsifiable (statement, assumptions,
  variables, expected effect, falsification condition).
- Experiments are never overwritten (failed/rejected kept as negative
  knowledge).
- Promotion requires the 8-metric gate + a human identity; loss/win loops
  NEVER mutate strategy (verified: no setter surface exists).

## Async isolation

TRADE_CLOSED → persist review → `ResearchQueue.submit` (non-blocking).
Worker drains separately; a research crash increments `errors`, never breaks
trading or safety (RiskGate/Execution unaffected).
