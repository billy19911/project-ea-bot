# Phase 6 — Budget & Failure/Escalation Appendix

## Budget ledger API

```
ledger = router.budget_for_cycle(cycle_id)
ledger.max_tokens / max_cost   # config-derived ceilings
ledger.reserve(tokens, cost)   # pre-call reservation → bool
ledger.commit(tokens, cost)    # post-call commit (refunds reservation)
ledger.remaining_tokens()      # None when unbounded
ledger.cost_known              # False → UNKNOWN cost never blocks on cost
```

Unknown cost is preserved (never treated as 0). Aggregation:
`router.cost_summary()` → by_model / by_agent / by_task with `unknown_cost`
counters.

## Degradation ladder (§33)

```
LOW       → reduce optional summaries
MEDIUM    → skip non-critical specialist
HIGH      → preserve mandatory challenge
EXHAUSTED → stop optional AI calls
```

Never degraded: RiskGate, TriggerEngine, DecisionState, Execution safety.

## Failure matrix (§15)

| Failure | Action |
|---------|--------|
| provider unavailable | bounded fallback |
| model timeout | UNKNOWN/FAILED + bounded fallback |
| rate limit | backoff then fallback |
| invalid output | bounded repair (1) then reject |
| context overflow | context truncation (blocking kept) |
| tool failure | task failure (no fabrication) |
| network failure | bounded fallback |
| all down | AI task FAILED → WAIT/NO_TRADE |

## Escalation ladder (§14)

```
Model A → invalid output
Model B → disagreement
Targeted challenger → still unresolved
→ WAIT / NO_TRADE
```

Bounded by max_escalations and max_depth; a stop condition is always present
(§39): sufficient evidence, valid output, budget exhausted, max attempts,
resolved/unresolved conflict, missing data.
