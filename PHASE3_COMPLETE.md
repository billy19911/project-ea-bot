# PHASE 3 — COMMITTEE & DEBATE ENGINE

## STATUS

COMPLETE

## ARCHITECTURE

Phase 3 turns the agent system into a hierarchical, evidence-driven committee
with targeted debate, wired into the real decision path as an additive
canonical layer (existing supervisor/synthesis paths keep working).

```
EVENT → EventClassifier → relevant ROLES (1..6 per trigger) → evidence
→ MarketAssessment → SetupCandidate (only if directional evidence consistent)
→ conflict detection → BOUNDED DEBATE (targeted challenge, max 2 rounds)
→ EntryCommittee gate → DecisionState → (pipeline) Risk Gate → Execution
```

Core principle enforced: specialists provide evidence → lead forms hypothesis
→ challenger attacks hypothesis → committee resolves uncertainty →
deterministic systems enforce risk. NEVER: agents vote → majority wins → trade.

New modules:
- `src/agents/roles.py` — 8 canonical roles with normalized `RoleOutput`.
- `src/agents/debate.py` — `DebateEngine` (bounded loop) + `DebateRecord`.
- `src/agents/event_dispatch.py` — trigger taxonomy + analysis levels (§15–16).
- `src/agents/orchestrator.py` — `CommitteeOrchestrator` tying it together.
- Provenance fields added to `EvidenceItem` (`source_id/source_type/derived_from`).

Docs:
- `docs/phase3_discovery_report.md` (Step 1)
- `docs/phase3_committee_architecture.md`
- `docs/phase3_debate_protocol.md`

## SPECIALISTS

| Role | Path | Real vs new |
|------|------|-------------|
| regime | `roles.RegimeRole` (ADX/trend/ATR deterministic) | NEW (was inline in MarketLead) |
| structure | `role_from_specialist('structure', StructureAnalystAgent)` | ADAPTED existing |
| liquidity | `roles.LiquidityRole` (equal-high/low sweep detection) | NEW |
| momentum | `role_from_specialist('momentum', MomentumAnalystAgent)` | ADAPTED existing |
| volatility | `role_from_specialist('volatility', VolatilityAnalystAgent)` | ADAPTED existing |
| news | `role_from_specialist('news', NewsSentimentAgent)` | ADAPTED existing; UNKNOWN stays UNKNOWN |
| entry | `roles.EntryRole` | NEW interface (Phase 4 builds full triggers) |
| challenger | `roles.ChallengerRole` | NEW adversarial reviewer |

Each is wired into the real path: `CommitteeOrchestrator.run()` invokes each
role's `.analyze()` for its trigger, and its `RoleOutput.signal/evidence`
directly drives assessment → setup → debate → decision. Verified end-to-end
with production specialists (smoke test: TREND_BULLISH → ran, roles emitted,
conflict surfaced, debate INVALID → decision WAIT).

## DEBATE

`DebateEngine.run(setup, conflicts)`:
- Only HIGH/CRITICAL (optionally MEDIUM) conflicts trigger challenges.
- Each round asks the OPPOSING domain's specialist a targeted question
  (never re-runs the whole committee).
- Challenger outcomes: CHALLENGE_PASSED (survived → resolve) /
  CHALLENGE_FAILED (refuted → INVALID) / CHALLENGE_UNRESOLVED (→ next round or WAIT).
- Bounded: `max_rounds=2`, `max_challenges_per_cycle=3` (centralized `DebateConfig`).
- Every round emits a `DebateRecord` (debate_id, setup_id, round, trigger,
  hypothesis, challenge, challenger, response, evidence_refs, conflict_refs,
  outcome, timestamp) — traceable for review/learning/dashboard.

## EVENTS

Trigger taxonomy + levels (`event_dispatch.py`):
- BOS/CHOCH → structure+regime specialists; LIQUIDITY_SWEEP → liquidity;
  NEWS_HIGH_IMPACT → news; VOLATILITY_SPIKE → volatility;
  ZONE_TOUCH → entry committee; SETUP_FORMED → market lead.
- Deterministic-only (no committee): POSITION_OPENED/CLOSED, TRADE_CLOSE,
  unknown noise.
- `state_changed=False` → `NO_FULL_COMMITTEE` (cached evidence reused).

## CONFLICT

Severity: LOW (observation) / MEDIUM (challenge recommended) / HIGH
(challenge required) / CRITICAL (trade blocked unless resolved).
Unresolved HIGH/CRITICAL → WAIT/NO_TRADE (fail-closed), enforced in BOTH the
supervisor path (Phase 2 hardening) and the orchestrator path
(debate gate + INVALID-setup gate added in Phase 3 smoke-test fix).

## EVIDENCE

- Every role emits canonical `EvidenceItem`s (kind, content, source,
  timestamp, timeframe, quality, freshness, metric, domain + provenance
  source_id/source_type/derived_from).
- Directional claims without facts are marked `[INCOMPLETE]` with reduced
  quality (adapter) — never trusted blindly.
- Assessment links `evidence_bundle`; decisions link `evidence_bundle_ref`;
  proposals carry `reason_codes` + `evidence_refs`.
- Provenance metadata (`rsi_14/indicator/close_prices`) lets future work
  detect correlated evidence (tested: five agents, one source → one source_id).

## TESTS

```text
Phase 3 tests: 46 passed
  test_phase3_committee.py: 18 (roles, orchestrator, dispatch, inadmissible states)
  test_phase3_debate.py: 9 (bounded loop, severity, caps, traceability)
  test_phase3_event_dispatch.py: 10 (triggers, levels, cache gating)
  test_phase3_failure_modes.py: 9 (crash, correlation, malformed, gate/volume authority)
Full Python: 2690 passed
Node/API: 61 passed
```

Adversarial results: strong-vs-weak evidence → evidence wins (not headcount);
unresolved HIGH → WAIT/INVALID; news UNKNOWN → flagged, never CLEAR;
specialist crash → UNKNOWN + WAIT when required; debate caps respected;
malformed outputs → empty bundle, no trade; RiskGate still rejects oversized
proposals; AI-suggested 25.0 lots → capped to 0.05.

## SAFETY

- A: AI cannot bypass RiskGate — orchestrator produces structure only; the only
  execution path remains pipeline → proposal → RiskGate → approval token →
  ExecutionEngine. VERIFIED (grep: no order paths in new committee code).
- B: AI cannot determine final volume — no lot/volume authority in any role;
  MoneyManager `_cap_lot` remains final boundary. VERIFIED (test: 25.0 → 0.05).
- C: AI cannot directly submit MT5 orders — VERIFIED (no MT5 imports/calls).
- D: HIGH/CRITICAL unresolved conflict cannot auto-trade — VERIFIED (supervisor
  suppress + debate INVALID/WAIT gates; tests).
- E: UNKNOWN data cannot silently become known — VERIFIED (regime/entry/news
  UNKNOWN paths tested; freshness STALE factor).
- F: No majority vote controls the decision — VERIFIED (grep: no counts/
  max-votes/winner logic in orchestrator/debate/roles/event_dispatch;
  legacy counts remain observability-only).
- G: Debate has deterministic termination — VERIFIED (max_rounds/challenges
  caps tested; perpetual conflict → WAIT at max_rounds).
- H: M1 ticks don't trigger full committee — VERIFIED (dispatch tests:
  no-change → cache; position events → deterministic-only).
- I: Every setup has stable setup_id — `setup_<assessment_id>` within a
  lifecycle; derivation documented.
- J: Decision reconstructible from trace — CommitteeResult.to_dict() carries
  dispatch → assessment → setup → debate → entry → decision + role outputs.

## LIMITATIONS

- `MarketLead.analyze()` (legacy supervisor path) still uses its own
  evidence-weight collapse; the canonical orchestrator is additive, not yet
  the default runtime path — operator opts in. Unifying them is future work.
- `intelligence.synthesize()` legacy classmethod retains a max-weight winner
  pattern; callers are tests + risk-lead wiring. Not authoritative for trades,
  but should be deprecated or aligned later.
- Canonical objects are in-memory per cycle (restart loses intermediate
  debate state); durable debate persistence is future work if needed.
- Liquidity detection is simple fractal equal-high/low (no session/OB context
  yet); sufficient for Phase 3 structure, Phase 4 will deepen it.
- `max_cycle_duration_s` is configured but not yet enforced with a wall-clock
  (per-agent timeouts + round caps bound it in practice).
- News feeds depend on provider wiring; UNKNOWN is common and handled safely.
- Commission metadata missing from MT5 connector (UNKNOWN unless configured).

## NEXT PHASE

Phase 4 — Entry Engine can safely build on:
- `SetupCandidate.required_conditions` (trigger contracts),
- `EntryRole` READY/WAIT/INVALID interface,
- `ZONE_TOUCH → ENTRY_COMMITTEE` dispatch,
- `DebateRecord.evidence_refs` for post-trigger review.
No Phase 3 interface changes expected for Phase 4 triggers.
