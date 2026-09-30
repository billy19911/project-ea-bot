# Phase 3 — Debate Protocol

## Lifecycle (src/agents/debate.py)

```
INITIAL_ANALYSIS → HYPOTHESIS → CONFLICT_DETECTION → TARGETED_CHALLENGE
→ SPECIALIST_RESPONSE → RESOLUTION
```

Implemented by `DebateEngine.run(setup, conflicts, hypothesis_direction, role_outputs, context)`.

## Targeting (§8)

Only the OPPOSING domain's specialist is asked a targeted question, e.g.
"structure bullish vs momentum bearish" asks momentum: *is your evidence enough
to invalidate the structure?* The whole committee is NOT re-invoked.

## Bounded loop (§9–§10, §17)

`DebateConfig` centralizes limits:

| Limit | Default |
|-------|---------|
| max_rounds | 2 |
| max_challenges_per_cycle | 3 |
| max_specialists_per_cycle | 6 |
| max_total_calls | 12 |
| max_cycle_duration_s | 30.0 |

No infinite loops: the loop runs at most `max_rounds`, challenges at most
`max_challenges_per_cycle`.

## Termination outcomes (§10)

- `RESOLVED` — conflict survived the challenge (marked resolved).
- `WAIT` — conflict unresolved after the bounded loop → NO automatic trade.
- `INVALID` — challenger refuted the hypothesis → setup invalid.
- `EXPIRED` / `DATA_UNAVAILABLE` — evidence unusable.

## Conflict severity (§11)

| Severity | Action |
|----------|--------|
| LOW | observation only |
| MEDIUM | targeted challenge recommended |
| HIGH | targeted challenge required |
| CRITICAL | trade blocked unless resolved by sufficient evidence |

Unresolved HIGH/CRITICAL always yields WAIT/NO_TRADE (fail-closed).

## Debate record (§23)

Every round emits a `DebateRecord`:
debate_id, setup_id, round, trigger, hypothesis, challenge, challenger,
response, evidence_refs, conflict_refs, outcome, timestamp.

Records are returned in `DebateOutcome.to_dict()` for dashboard/review/learning.

## Advisory-only second opinions

A `specialist_runner(role, context)` callable may fetch a targeted second
opinion. It is OPTIONAL: without it, challenges are still recorded and
HIGH/CRITICAL conflicts still block. The debate never votes on the outcome.
