# PHASE 9 DISCOVERY REPORT — Live Readiness / Pre-Live Certification

## Existing certification infrastructure

| Component | Provides |
|-----------|----------|
| `live_readiness/base.py` | `LiveReadinessStatus` (NOT_STARTED/PASSED/FAILED), `Phase30Gate` enum, `LiveReadinessGate`, `LiveReadinessSummary` (fail-closed overall) |
| `live_readiness/evaluator.py` | `LiveReadinessEvaluator` — deterministic, NEVER connects to broker, missing gates fail closed; report always `live_execution_enabled=False` |
| `live_readiness/environment.py` | `Environment` (DEV/PAPER/DEMO/LIVE), `EnvironmentGuard.can_execute_live()` — non-LIVE always rejected; LIVE requires terminal_armed + risk_gate_healthy; `EnvironmentViolation` |
| `live_readiness/account_manager.py` | Broker/Account/ExecutionContext models |
| `readiness/gate.py` | `LiveReadinessGate` (readiness pkg) — PAPER→LIVE only via `activate_live(confirmation)` with ALL gates PASSED + exact phrase; regression fail-closes back to PAPER; activation history |
| `readiness/gates.py` | `DEFAULT_GATE_NAMES`, `LIVE_CONFIRMATION_PHRASE`, `GateResult/GateStatus` |
| `system/certification.py` + `live_readiness/certification_gate.py` + `certification_evidence.py` | Production Certification Gate (Gates A–E: Engineering/Trading-Safety/Research/Operational/Forward); evidence from REAL artifacts/runtime/research/drills/forward; absent ⇒ unknown (never fabricated pass) |
| `trading/modes.py` | Mode manager delegating to gate; audited mode transitions |

## Live guards (verified)

- `readiness.LiveReadinessGate.activate_live` requires (a) no blockers, (b) exact
  `LIVE_CONFIRMATION_PHRASE`; else `ActivationBlockedError`. Gate regression
  while LIVE auto-reverts to PAPER (fail-closed).
- `live_readiness.EnvironmentGuard.can_execute_live`: non-LIVE ⇒ REJECT; LIVE ⇒
  requires preconditions.
- `ExecutionEngine._native_execution_armed`: armed+eligible terminal required
  (Phase 1), fail-closed.
- Static audit: no `enable_live`/`arm_live`/`promote_live` auto path; the only
  LIVE transitions are gated (+ confirmation) and always start from PAPER.

## Broker / symbol / account

- Broker metadata via `mt5/connector` + `market/symbol_spec.SymbolSpecification`
  (point/digits/tick/contract/min/max/step/spread_limit/commission).
- Account via connector get_account_info.
- UNKNOWN preserved where broker omits (commission/spread often UNKNOWN).

## Existing checks (startup/recovery/health)

Phase 8 `system/startup_checks.py` (safety-config gate + execution-recovery
scan); reconciliation guard; health probes (/ops/health); SLO evaluator;
incidents; alerts.

## Evidence stores

`logs/ops_drills.jsonl` (Gate D drills), `research_state.jsonl` (Gate C),
execution-quality + incident manager (Gate E), CI artifacts (Gate A).

## Missing checks (Phase 9 build list)

1. No single immutable `LiveReadinessCertification` record with expiry +
   invalidation-on-material-change.
2. No MANDATORY/WARNING/INFORMATIONAL classification aggregating into one
   deterministic gate output with per-check evidence.
3. No environment-identity fingerprint (code/strategy/config version + broker +
   account + symbols) freeze.
4. No soak-test harness (none exists).
5. No explicit multi-writer topology check.
6. No certification-report secret audit.

## Duplicate / overlapping checks

- Two "live readiness" systems: `live_readiness/` (Phase 30 gates) and
  `readiness/` (activation gate) and `system/certification.py` (A–E). They are
  complementary (evaluation vs activation vs production gate); Phase 9 adds ONE
  aggregator that CONSUMES them — no new parallel authority.

## Unsafe/bypassable paths found

NONE. All live transitions gated + confirmation + fail-closed regression; no
auto path. Phase 9 only adds certification/evidence + expiry; no arm path is
enabled.

## Safe hardening plan (minimal, no redesign)

- New `src/certification/` package: `checks.py` (individual checks with
  severity), `certification.py` (`LiveReadinessCertification` immutable +
  fingerprint + expiry/invalidation), `gate.py` (`CertificationGate.evaluate`
  deterministic aggregate), `soak.py` (bounded in-process soak harness for
  SIM/PAPER only).
- Consume existing gates/evaluators; never modify RiskGate/ExecutionEngine.
- Phase 9 tests + adversarial (15 cases). Live remains DISABLED.
