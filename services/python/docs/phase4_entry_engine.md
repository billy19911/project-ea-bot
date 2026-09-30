# Phase 4 — Entry Engine

> A zone gives the system a place to look. A trigger gives the system evidence
> to act. RiskGate decides whether it is allowed to act.

## Pipeline

```
EVENT → (committee) → SetupCandidate + Zone
   → ZONE_TOUCH → WAIT_TRIGGER
   → TRIGGER ENGINE (rejection / displacement / micro-BOS / momentum / candle-close)
   → EXECUTION FILTERS (spread / freshness / session / news)
   → EntryAssessment (ENTRY_READY | WAIT_TRIGGER | INVALID | EXPIRED | UNKNOWN)
   → DecisionState → deterministic validation → RiskGate → Execution
```

Distinction (§3): ZONE ≠ SETUP ≠ TRIGGER ≠ ENTRY ≠ ORDER.

## Modules (src/trading/)

| Module | Responsibility |
|--------|----------------|
| `entry_config.py` | `ZoneConfig` / `TriggerConfig` / `TimeframeConfig` / `EntryEngineConfig` — all thresholds centralized (§46) |
| `entry_zones.py` | `Zone` (stable id + lifecycle), `detect_zone_touch`, `evaluate_invalidation`, `is_zone_expired` |
| `entry_detectors.py` | `detect_order_blocks`, `detect_fvgs` — strict, displacement/quality gated |
| `trigger_engine.py` | `evaluate_triggers` + 5 detectors → `TriggerResult` + `TriggerEvidence` |
| `entry_lifecycle.py` | `EntryLifecycleManager` — setup registry, idempotency, expiry/invalidation |

## OB (§6–§8)

`detect_order_blocks`: last opposite-colour origin candle immediately before a
DISPLACEMENT candle (body ≥ `ob_min_displacement_atr × ATR`, default 0.5). Zone =
origin candle high/low; invalidation = far edge (bullish → close below low).
Every opposite candle is NOT an OB — displacement is mandatory.

## FVG (§9–§10)

`detect_fvgs`: real 3-candle imbalance (`highs[i-1] < lows[i+1]` bullish,
mirror bearish). Gap must be ≥ `fvg_min_gap_atr × ATR` (default 0.1) — tiny
gaps rejected as noise. Quality stored as `gap_atr`.

## Trigger (§14–§25)

`evaluate_triggers(direction, zone, OHLC, atr, ...)` evaluates independently:
- **rejection** — wick penetrates zone, body closes back, wick-ratio threshold;
  a lone wick is NOT a trigger.
- **displacement** — body/ATR + range/ATR, directional.
- **micro_bos** — last bar breaks the prior `lookback` swing (no lookahead).
- **momentum_shift** — EMA fast/slow aligned (supporting only).
- **candle_close** — only True when the evaluated candle is closed (§19).

Conditions are explicit (`conditions_met` / `blocking`); NO black-box score
(§22). `is_fresh(max_age_s)` enforces the trigger freshness window (§25).
No future leakage (§44): only data at/before the evaluated bar is used; a
forming candle is excluded and never confirms.

## Lifecycle

```
CANDIDATE → ARMED → WAITING_TRIGGER → ENTRY_READY
                                    ↘ INVALID / EXPIRED
```

`EntryLifecycleManager.evaluate_lifecycle()` returns INVALID on a decisive
close beyond the boundary (§27) or EXPIRED on time expiry (§26). Terminal
statuses never resurrect. Mitigation: FRESH → TOUCHED → PARTIALLY_MITIGATED →
FULLY_MITIGATED → INVALIDATED (§28). Retests tracked; `max_retests` caps (§29).

## Multi-timeframe (§11)

`TimeframeConfig` (context M15 / trigger M5 / micro M1, configurable). The
trigger engine runs on the TRIGGER/MICRO series; context bias comes from the
committee. Contradictory timeframes are NOT averaged — a
`structure_invalidated` block condition stops the entry (TEST 13).

## Safety

- zone touch ≠ entry (EntryRole returns WAIT_TRIGGER on touch alone).
- AI cannot force ENTRY_READY: the deterministic trigger engine is authoritative
  (a caller-asserted flag cannot override a missing required trigger).
- RiskGate stays authoritative — ENTRY_READY still goes through the gate.
- AI cannot set final volume (MoneyManager cap unchanged).
- AI cannot submit an MT5 order (no broker path in any Phase 4 module).
- Stale/inverted/unknown spread → block (§30); expired setup → block (§26);
  invalidated setup → block (§27); unknown required data → block (§49).
- Idempotent + concurrency-safe entry claims: `(setup_id, trigger_id,
  candle_ts)` fires exactly once across threads (§40–§41).

## Events (§38)

`event_dispatch.py` extended: ZONE_TOUCH / TRIGGER_CANDIDATE / MICRO_BOS /
DISPLACEMENT / REJECTION / CANDLE_CLOSE → LEVEL_ENTRY (targeted, entry role);
SETUP_INVALIDATED / SETUP_EXPIRED → deterministic.

## Bid/ask semantics (§34)

`detect_zone_touch`: LONG uses executable **bid**, SHORT uses **ask**; candle
range intersection also counts as a touch (wick), which is NOT confirmation.
Invalidation uses **close**, never wick.

## Phase 5 integration

`TriggerEvidence` (provenance: source_id/source_type/derived_from),
`EntryAssessment` (met/missing/blocking conditions), and `Zone` lifecycle
metadata feed future learning/review without further interface changes.
