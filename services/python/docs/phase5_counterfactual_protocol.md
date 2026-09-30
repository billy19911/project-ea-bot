# Phase 5 — Counterfactual Protocol

Counterfactuals measure what would have happened after WAIT/NO_TRADE/REJECTED
if the decision had hypothetically been an entry. Builder:
`ReviewBuilder.build_counterfactual` (src/learning/review_store.py).

## Rules

1. Entry reference = the decision-time price (never a later best price).
2. Only the subsequent realized range (future_high/future_low AFTER the
   decision) classifies the outcome.
3. SL and TP both reachable → INVALID_COUNTERFACTUAL (ambiguous fill order;
   never guessed).
4. No price data → INSUFFICIENT_FUTURE_DATA.
5. Outcomes: WOULD_HAVE_WON / WOULD_HAVE_LOST / WOULD_HAVE_BEEN_BREAKEVEN /
   WOULD_NOT_HAVE_TRIGGERED / INSUFFICIENT_FUTURE_DATA / INVALID_COUNTERFACTUAL.

## Forbidden

Counterfactuals never send orders, call MT5, create execution intents, touch
RiskGate, change DecisionState, or activate strategy.
