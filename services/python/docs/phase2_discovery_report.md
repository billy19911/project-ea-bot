# PHASE 2 DISCOVERY REPORT — XynnBot Decision Architecture

## CURRENT DECISION PIPELINE

### 1. Entry point
`SupervisorAgent.analyze(context)` in `src/agents/supervisor.py` line 436.

### 2. Event source
Pipeline event → context.event_type (e.g., "BREAKOUT", "TREND_BULLISH").  
Source: `orchestration/pipeline.py` `_build_analysis_context()`.

### 3. Supervisor
`SupervisorAgent` (EPIC 03):
- Routes events to department leads (if available) or matches routes.
- Applies routing_policy: first_match, all_match, priority_based.
- Dispatches agents with concurrency control.
- Token budget tracking.

### 4. Agent registry
`Registry` (`agents/registry.py`) stores agents by role/type.  
Production wiring: `orchestration/runtime.py` injects registry into Supervisor.

### 5. Agent invocation
Two paths:
- Direct: `agent_list` from context.analysts → map[agent.name].analyze().
- Delegation: Supervisor delegates to department leads (DepartmentLead), who select specialists and call them.

### 6. Agent output schema
Normalized via `normalize_agent_output()` (supervisor.py line 58):
- signal (str, upper-cased, default NEUTRAL)
- confidence (float, 0–1)
- reasoning/reasons (str/list)
- evidence (list)
- source metadata for each agent result.

Specialist outputs may include additional fields (regime, structure, etc.).

### 7. Synthesis
`AgentSynthesizer.generate_proposal()` (synthesis.py line 293):
- Calls `aggregate_signals()` (lines 194–257): counts bullish/bearish/neutral.
- Computes agreement_score = majority / total.
- Direction determined by majority (buy > sell + buy >= neutral → BUY).
- Weighted confidence computed per direction.
- Conflicts detected via pairwise opposition checks (detect_conflicts()).

### 8. Signal creation
Department lead (e.g., `MarketLead`) synthesizes specialist results:
- Uses regime-weighted vote aggregation: weight = regime_weight × confidence.
- Winner = max(votes.items()) by weighted score.
- Unresolved conflict flagged (line 799).

Output includes:
```python
{
    "agent": "MarketLead",
    "signal": "BUY"|"SELL"|"NEUTRAL",
    "confidence": ...,
    "reasons": [...],
    "regime": ...,
    "specialist_results": {...},
    "dissent": [...],
    "unresolved_conflict": bool,
}
```

### 9. Proposal creation
`Supervisor._synthesise()` (line 624):
- Calls AgentSynthesizer.generate_proposal().
- Extracts TradeProposal from synthesis_dict["proposal"].
- Converts target_sl/target_tp → stop_loss/take_profit.
- Suppresses proposal if unresolved_conflict AND weak consensus (lines 664–668).
- Returns (synthesis_dict, proposal_dict) or (None, None).

### 10. Risk Gate boundary
Pipeline passes proposal to `RiskGate.validate_proposal()` (gate.py line 64).
Proposal must contain:
```python
{
    "symbol": str,
    "direction": "BUY"|"SELL",
    "entry_price": float,
    "stop_loss": float,
    "take_profit": float,
    "size": float,
    "risk_pct": float,
}
```

Risk Gate enforces hard limits before approval token is issued.

### 11. Execution boundary
`ExecutionEngine.execute_order(OrderRequest)` called only after Risk Gate approves.
OrderRequest carries approval_token stamped by pipeline (pipeline.py line 765).

---

## CURRENT MAJORITY / VOTING LOGIC

### Files containing voting logic

#### A. `src/agents/synthesis.py` lines 213–257 (aggregate_signals) & 332–348 (generate_proposal)
```python
bullish_count += 1 if signal in BULLISH_SIGNALS else 0
bearish_count += 1 if signal in BEARISH_SIGNALS else 0
neutral_count += 1 ...

majority = max(bullish, bearish, neutral)
agreement_score = majority / total

if bullish > bearish and bullish >= neutral:
    direction = TradeDirection.BUY
    ...
elif bearish > bullish and bearish >= neutral:
    direction = TradeDirection.SELL
else:
    direction = TradeDirection.HOLD
```

**Impact**: Majority headcount determines final trading direction (BUY/SELL).

#### B. `src/market/intelligence.py` lines 687–799 (MarketLead.analyze)
```python
votes: dict[str, float] = {}
for name, result in specialist_results.items():
    direction = self._direction_of(...)
    try:
        confidence = float(result.get("confidence", 0.0) or 0.0)
    except ...:
        confidence = 0.0
    weight = weights.get(name, 0.0) * confidence
    if weight <= 0:
        continue
    votes[direction] = votes.get(direction, 0.0) + weight

winner = sorted(votes.items(), key=lambda kv: (-kv[1], priority))[0][0]
```

**Impact**: Regime-weighted votes still aggregate by direction; winner = max(weight).  
This is NOT simple majority-headcount but still a form of committee voting that collapses multi-agent evidence into a single directional winner.

#### C. `src/agents/departments.py` lines 138–150 (_resolve_consensus)
```python
signals = {result.get("signal") for result in results.values() if ...}
if len(signals) == 1:
    return signals.pop(), False
if len(signals) > 1:
    return "UNRESOLVED", True
return "NEUTRAL", False
```

**Impact**: This does NOT use majority voting; it requires **unanimity**.  
If any two different non-neutral signals exist, unresolved_conflict=True.  
But the Supervisor may still proceed if only one leader reports conflict (depends on supervisor._has_unresolved_conflict() check).

---

## CALLERS OF VOTING LOGIC

### `synthesize.py` aggregate_signals → generate_proposal
Called by `Supervisor._synthesise()` (line 644).

### `intelligence.py` votes aggregation
Called internally by `MarketLead.analyze()`, which is invoked by Supervisor.

---

## CURRENT CONFIDENCE SEMANTICS

### Where confidence is created
- Specialist agents return `confidence` field in their output (LLM-based probability estimate).
- Normalized to [0, 1] via `normalize_agent_output()`.

### Where confidence is modified
- **synthesis.py**: 
  - `weighted_bullish += confidence` per bullish agent.
  - `confidence = votes[winner] / total_weight` for proposal.
  - `agreement_score = majority / total` (headcount fraction).
- **intelligence.py**: 
  - `weight = regime_weight × confidence` per agent.
  - `confidence = votes[winner] / total_weight` per direction.

### Where confidence affects decisions
- **Low-confidence escalation**: `prop.confidence < self.escalation_confidence_threshold` → escalate.
- **Weak consensus suppression**: `confidence < conflict_confidence_floor (0.6)` + unresolved_conflict → suppress proposal.
- **Overall_signal determination**: `overall_confidence = result["confidence"]` where `result.get("confidence", 0) > overall_confidence` (highest single-agent confidence wins; line 556–558 in supervisor).

### Whether it is treated as probability
- **Implicitly yes**: The code comments say `"confidence"` is LLM-provided, but no documentation prevents treating it as P(profit).
- **No explicit prohibition**: Comments do not clarify that confidence ≠ probability of profit.

---

## CURRENT SIGNAL STATES

### Existing states
Not explicitly implemented as a finite state machine.  
Only loose states:
- `pending` (signal_registry.pending)
- `executing` (pipeline status: EXECUTED/WAIT/NO_TRADE/BLOCKED)
- `OPEN` (position monitoring)

### State transitions
Manual assignment (pipeline.py):
- NEW: `PENDING` when analysis begins.
- EXECUTED: after execution success.
- BLOCKED: if risk gate rejects.
- NO_TRADE: if synthesis returns HOLD/NEUTRAL.

### Who changes them
- `SignalRegistry`: open_signal(...), get(...) returns pending/PENDING/OPEN/etc.
- `TradingPipeline.run()`: sets status per stage.

---

## ALTERNATIVE DECISION PATHS

### Path: direct agent → execute_order bypass?
Search found:
- `mt5/write_guard.py`: `send_order()` validates permission/volume/exposure but is NOT routed through the deterministic Risk Gate.
- `mt5/endpoints.py`: `/orders/execute` endpoint calls `connector.execute_order()` directly without Risk Gate or approval token.

**Risk**: These are **paper trading paths** (simulation_mode path in connector.py line 916–936). However, they should NEVER be reachable in live mode unless an operator arms a terminal.  
The native MT5 path has guard checks (`_native_execution_armed()`) ensuring execution blocked unless terminal is armed (engine.py line 1353–1368).

**Conclusion**: No unprotected live-execution path discovered, but the endpoints and write_guard remain separate from the main pipeline flow.

---

## IMPLEMENTATION GAP ANALYSIS

### What Phase 2 MUST address
1. **Remove majority voting as final authority**: Currently both synthesis.py (majority headcount) and intelligence.py (weighted direction votes) collapse multi-agent evidence into a single directional winner.
2. **Canonical evidence model**: `EvidenceItem` exists but is NOT required for all agent outputs. Many specialists return raw dicts with signal/confidence only.
3. **Explicit MarketAssessment/SetupCandidate/EntryAssessment objects**: These exist conceptually in PRD_V2 but are NOT implemented as canonical dataclasses.
4. **Decision state machine**: Not implemented; pipeline uses ad-hoc status strings.
5. **Conflict detection**: Already partially present (unresolved_conflict flag) but resolution strategy missing (no challenge/second-opinion flow).
6. **Confidence semantics**: Must document that confidence ≠ P(profit) and separate dimensions (evidence_quality, setup_quality, data_freshness).
7. **Traceability IDs**: trace_id, assessment_id, setup_id, decision_id not systematically generated and linked.

### What Phase 2 CAN PRESERVE
- `evidence.py` EvidenceItem/EvidenceBundle (good foundation).
- `decision_state.py` DecisionState (useful but needs augmentation).
- `departments.py` DepartmentLead pattern (keep; it enforces non-majority consensus requirement).
- Supervisor routing and specialization delegation (keep; adapt for evidence collection).
- MarketIntelligence regime-weighted approach (keep, but reframe as evidence weighting rather than voting).

---

## IMPLEMENTATION MAP (PHASE 2)

### Files to MODIFY
1. `src/agents/synthesis.py`: Remove majority_headcount logic; replace with evidence-based trade proposal generation.
2. `src/agents/supervisor.py`: Add evidence collection and canonical DecisionState construction.
3. `src/market/intelligence.py`: Change from weighted voting to evidence synthesis (no winner selection, preserve dissent).
4. `src/orchestration/pipeline.py`: Pass DecisionState → TradeProposal → Risk Gate with trace_id linkage.
5. `src/trading/event_engine.py` or similar: Add state machine for signal lifecycle (if not already).

### Files to CREATE
1. `src/agents/canonical.py`: Define MarketAssessment, SetupCandidate, EntryAssessment, DecisionState (expanded), TradeProposal.
2. `src/trading/state_machine.py`: Explicit state machine for signals (if not existing).

### Files to ADD TESTS FOR
1. tests/test_canonical_decision_objects.py
2. tests/test_phase2_majority_removal.py
3. tests/test_phase2_evidence_requirement.py
4. tests/test_phase2_conflict_resolution.py
5. tests/test_phase2_state_machine.py

---

## KEY ARCHITECTURE RULES TO ENFORCE
1. AI never submits MT5 order directly.
2. TradeProposal always goes through Risk Gate.
3. Final volume determined by MoneyManager cap, not LLM.
4. Confidence ≠ P(profit); separate evidence_quality/setup_quality/data_quality.
5. Every decision must have traceable evidence ref.
6. Resolved conflicts required for actionable trades; unresolved → WAIT.

STOP AFTER THIS DISCOVERY. AWAITING GO-AHEAD FOR IMPLEMENTATION.