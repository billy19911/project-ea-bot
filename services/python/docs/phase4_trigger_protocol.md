# Phase 4 — Trigger Protocol

## Condition contract (§20–§22)

Every trigger evaluation returns explicit conditions — never a score:

```
conditions_met:    {zone_touch: true, rejection: true, micro_bos: false, ...}
missing_triggers:  [micro_bos]           # required but absent
blocking:          []                     # forbidden conditions present
evidence:          [TriggerEvidence...]   # one record per confirmed trigger
```

Authoritative decision = required conditions ALL met AND blocking empty.

## Required vs optional vs forbidden (§21)

- **required** (`TriggerConfig.required_triggers`, overridable per setup type
  via `EntryEngineConfig.required_for`): every one must be met → ENTRY_READY.
- **optional** (`optional_triggers`): descriptive context, never sufficient alone.
- **forbidden** (`forbidden_conditions`): any present blocks even a full
  required set (spread_too_wide, structure_invalidated, news_high_impact).

## Candle semantics (§19)

Detectors receive `is_closed`. When False, evaluation runs over `data[:-1]` —
the forming candle is excluded and `candle_close` is False. ENTRY_READY with
`require_candle_close=True` therefore needs a real close.

## Freshness (§25)

`TriggerResult.trigger_time_ts` is set when any non-zone trigger fires.
`is_fresh(max_age_s)` compares against `TriggerConfig.trigger_max_age_s`
(default 15 min). Stale triggers yield TRIGGER_EXPIRED downstream, never entry.

## No-future-leakage (§44)

For candle index `t`, only data `[0..t]` is consulted. `micro_bos` compares
the last bar against the prior `lookback` bars only. Backtest compatibility
(§45): detectors are pure functions of OHLC lists + config — identical on
live, simulation, backtest, paper, demo with different adapters.

## Evidence (§24)

Each confirmed trigger emits `TriggerEvidence(type, direction, timeframe,
detected_at_ts, trigger_price, break_price, detail, source_id, source_type,
derived_from)` — compatible with Phase 3 provenance (`rsi_14/indicator/...`).

## Failure (§49)

Crash / insufficient data / unknown prices → `blocking=["insufficient_data"]`,
all conditions False → UNKNOWN/BLOCK downstream. Never ENTRY_READY. Logs carry
setup_id, symbol, timeframe, trigger type, error, timestamp.
