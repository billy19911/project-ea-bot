# Phase 3 — Committee Architecture

## Roles (src/agents/roles.py)

All roles emit a normalized `RoleOutput` (role, signal, confidence_dimensions,
EvidenceBundle, conflicts, invalidators, reason_codes, data_quality,
freshness, error). Roles never vote, never set volume, never touch MT5.

| Role | Implementation | Notes |
|------|---------------|-------|
| regime | `RegimeRole` (new, deterministic ADX/trend/ATR) | gap filled; UNKNOWN on missing input |
| structure | `role_from_specialist('structure', StructureAnalystAgent)` | adapts existing swings/BOS/CHOCH/S-R/FVG output into canonical evidence |
| liquidity | `LiquidityRole` (new, equal-high/low sweep detection) | gap filled; never converts detection into entry signal |
| momentum | `role_from_specialist('momentum', MomentumAnalystAgent)` | adapts existing multi-TF momentum |
| volatility | `role_from_specialist('volatility', VolatilityAnalystAgent)` | adapts existing ATR/regime/spread |
| news | `role_from_specialist('news', NewsSentimentAgent)` | UNKNOWN stays UNKNOWN; never fabricated CLEAR |
| entry | `EntryRole` (new) | ENTRY_READY/WAIT_TRIGGER/INVALID/UNKNOWN; zone touch ≠ confirmation |
| challenger | `ChallengerRole` (new, adversarial) | CHALLENGE_PASSED/FAILED/UNRESOLVED; searches contradictions |

Failure contract (§18): any role failure → `signal=UNKNOWN, data_quality=UNKNOWN,
error=True`. Direction is never fabricated.

## Orchestration (src/agents/orchestrator.py)

`CommitteeOrchestrator.run(context)`:
1. `decide_dispatch()` (§15–16) — only relevant roles per trigger; no-change →
   `NO_FULL_COMMITTEE` (cached evidence reused).
2. Level 1: run relevant roles only (+ news always, since UNKNOWN must surface).
3. Level 2: `CommitteeCoordinator.build_assessment()` → MarketAssessment.
4. SetupCandidate only when directional evidence is consistent (else none).
5. Level 3: `DebateEngine.run()` on conflicts (HIGH/CRITICAL → challenge).
6. Level 4: EntryRole gate → `EntryAssessment`; non-READY forces decision WAIT.
7. `build_decision()` → DecisionState (VALIDATED only when consistent + ready).

## Market Lead

`MarketLead.analyze()` (market/intelligence.py) remains the production
hypothesis builder: regime detection → adaptive weights → evidence weights →
dominance_ratio ≥ 0.6 else NEUTRAL. Output carries reasons + dissent.

CommitteeOrchestrator's assessment is additive (canonical path); MarketLead
continues to serve the legacy supervisor path. Both share the no-voting rule.

## Setup lifecycle

`CANDIDATE` → (debate) → `VALIDATED`/`CHALLENGED`/`INVALID`. `setup_id` is
derived from the assessment id (`setup_<assessment_id>`) so it is stable
within a single assessment lifecycle. Missing confirmations live in
`missing_conditions`; Phase 4 triggers consume `required_conditions`.

## Why majority voting is prohibited

Counts (`bullish_count`, `agreement_score`) remain as OBSERVABILITY metadata
only. Direction comes from `evidence_weight = relevance × quality × freshness
× independence`-style weighting (implemented as confidence ×
evidence_quality × freshness × evidence boost). A single high-quality fact
outweighs several weak observations; contradictory evidence becomes a Conflict,
not an outvoted minority.

## Phase 4 consumption

Phase 4 builds the OB/FVG trigger engine on:
- `SetupCandidate.required_conditions` (trigger contracts),
- `EntryRole` interface (already returns READY/WAIT/INVALID),
- `DebateRecord.evidence_refs` for post-trigger review.
No Phase 3 interface changes are expected for Phase 4 triggers.
