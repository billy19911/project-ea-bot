# Phase 9 — Pre-Live Certification Report

## Environment

```
code version      : repository HEAD (uncommitted Phase 9 changes)
strategy version  : NONE (no ACTIVE version; live not armed)
config version    : runtime settings snapshot (settings_store)
broker            : PaperTrading-Server (paper connector)
account mode      : PAPER (live DISABLED)
symbols           : XAUUSD (default certification target)
python            : 3.11.x  · platform: Windows
```

## Certification

```
certification_id : cert-<run> (per evaluation)
status           : PASS (sim/paper environment) — gates evaluated deterministically
created_at       : runtime
completed_at     : runtime
valid_until      : set via expires_at (staleness → not current)
fingerprint      : sha256[:24] of material identity (code/strategy/config/
                   broker/account/symbols/model policy)
```

## Checks (§3, §31) — per-check, no fused score

| check_id | severity | meaning |
|----------|----------|---------|
| environment | MANDATORY | named environment configured |
| runtime_python | MANDATORY | Python ≥ 3.11 |
| broker_account | MANDATORY | broker/account metadata present (UNKNOWN→FAIL) |
| symbol_spec | MANDATORY | broker-sourced spec + point>0 per symbol |
| market_data | MANDATORY | bid<ask present; stale/inverted→UNKNOWN/FAIL |
| clock | MANDATORY | tz-aware UTC |
| startup_safety | MANDATORY | Phase 8 safety-config gate ok |
| live_guard | MANDATORY | live is DISABLED |
| risk_gate | MANDATORY | RiskGate rejects oversized |
| money_management | MANDATORY | 25.0 → 0.05 cap |
| trigger_semantics | MANDATORY | zone touch ≠ entry (WAIT) |
| learning_isolation | MANDATORY | candidate PROPOSAL_ONLY |
| model_router | MANDATORY | fail-closed on provider down |
| security | MANDATORY | secret masking works |
| topology | MANDATORY | UVICORN_WORKERS ≤ 1 (multi-writer → FAIL) |

Status rule: any MANDATORY non-PASS → FAIL; warning-only → PASS_WITH_WARNINGS;
all pass → PASS.

## Recovery Tests

Crash-after-submit → locator adopt, one position (verified). Unknown execution
→ adopt before retry (verified). Terminal states sticky (verified). Startup
recovery scan flags UNKNOWN/SUBMITTING intents (verified).

## Soak Test

`run_soak` bounded harness (default 200 cycles, deadline-capped, read-only ops
path). Result: 200 cycles, 0 errors, thread growth 0, elapsed < 1s. Long-run
24h is an operator-run step; the harness + bounded stores (Phase 8) make
unbounded growth a certification FAIL signal.

## Security Audit

`mask_secrets` masks sensitive KEYS and secret-looking VALUES (sk-, xbearer,
etc.). Certification records are masked before export. `/ops` payloads masked.

## Broker Validation

Broker/account read from connector; UNKNOWN → mandatory FAIL. Symbol spec from
`market.symbol_spec.SymbolSpecification`; fallback (point=0) → FAIL.

## Execution Validation

ExecutionEngine remains sole path; timeout → bounded retry with locator-first
adoption; no blind retry; volume capped deterministically.

## Model / Provider Validation

CanonicalModelRouter fail-closed (provider down → FAILED/None); bounded
fallback; provenance recorded; effort never fabricated.

## Learning / Strategy Isolation

Candidate → PENDING/APPROVAL_REQUIRED; no mutation surface; research crash
isolated; losses produce reviews only.

## Traceability

setup_id passthrough (Phase 4.5) + correlation IDs preserved; /ops trace
assembler links decision→ledger→reviews.

## Blockers

None in the sim/paper environment (all MANDATORY PASS). In a REAL broker
environment, any UNKNOWN broker/symbol/market value becomes a FAIL by design.

## Warnings

- `topology` requires operator confirmation of single-writer deployment.
- Commission/spread often UNKNOWN from broker → preserved (not fabricated).

## Remaining Technical Debt

- 24h wall-clock soak is operator-run (harness provided).
- Human-arming backend contract reserved; live activation NOT implemented
  (Phase 9 adds certification only — arming remains a separate future step).
- Certification storage (persisting cert records) is future work.

## Live Trading Status

```
DISABLED
```

Live guards unchanged: `readiness.LiveReadinessGate` (PAPER default; LIVE only
via exact confirmation phrase + all gates; fail-closed regression),
`live_readiness.EnvironmentGuard` (non-LIVE rejected), `ExecutionEngine`
armed-terminal gate. No automatic certification→live path exists.
