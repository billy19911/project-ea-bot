# Phase 7 — Observability Contract

## Correlation IDs (preserved in URLs/query state, §19)

run_id, event_id, setup_id, trigger_id, decision_id, trade_id,
execution_intent_id, position_id, review_id, research_run_id,
strategy_version_id, model_decision_id(request_id).

- `GET /ops/decisions/{id}`, `/ops/setups/{id}/trace`, `/ops/trades/{id}`,
  `/ops/search` accept these IDs.
- Trace assembler links: decision graph → order ledger → canonical reviews.

## Freshness (§27)

Every market/health read exposes `last_updated` / `staleness_s` / `fresh`.
Stale data renders as stale, never as live.

## UNKNOWN semantics (§28)

`UNKNOWN ≠ 0/False/HEALTHY`. Preserved end-to-end (unknown_if_none helper;
model cost absent → no fabrication; empty telemetry → "no calls recorded").

## Alerts (§13)

Categories: SYSTEM, MARKET_DATA, RISK, EXECUTION, RECONCILIATION, MODEL,
BUDGET, RESEARCH, STRATEGY. Severities INFO/WARNING/HIGH/CRITICAL.
Normal WAIT/NO_TRADE never fires. Dedup handled by AlertManager upstream.

## Realtime (§21)

No new websocket layer: the ops router is poll-friendly (paginated, bounded
limits, drill-down traces). Existing Telegram hooks remain the push surface
for CRITICAL events. UI detects stale data via freshness envelopes.

## Security (§31–§32)

`mask_secrets` redacts api_key/token/secret/password/authorization/credentials
recursively in every ops payload and audit record. Mutation audit logs
action/identity/timestamp/resource/before/requested/result. Model/provider
errors and research artifacts are treated as untrusted data (never executed).
